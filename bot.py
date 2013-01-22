#!/usr/bin/env python
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.internet.endpoints import TCP4ClientEndpoint, SSL4ClientEndpoint
from twisted.internet.ssl import CertificateOptions

# For python <= 2.6 you can get this from pip:
# pip install ordereddict
from collections import OrderedDict

import os
import subprocess
import time
import logging
import re
import threading
import argparse

log = logging.getLogger(__name__)


# =============================================================================
# IRC stuff
# =============================================================================


class GitBot(irc.IRCClient):
    @property
    def args(self):
        return self.factory.args

    @property
    def nickname(self):
        return self.args.nickname

    @property
    def password(self):
        return self.args.password

    def signedOn(self):
        self.join(self.args.listen_channel)
        if self.args.listen_channel != self.args.speak_channel:
            self.join(self.args.speak_channel)
        log.info("Signed on as %s" % self.nickname)

    def joined(self, channel):
        log.info("Joined %s" % channel)
        if channel == self.args.listen_channel:
            log.debug("Starting %d workers" % self.args.num_workers)
            for i in range(self.args.num_workers):
                pp = lambda m: self.threadSafeMsg(self.args.speak_channel, m)
                t_args = (pp, self.args, self.factory.exc)
                t = threading.Thread(target=worker_entry, args=t_args)
                t.daemon = True
                t.start()

    def privmsg(self, user, channel, msg):
        log.debug("Message from %s at %s: %s" %
                (user.split("!")[0], channel, msg))
        if "!help" in msg:
            self.msg(channel, "I can answer !help and !queue_status")
        if "!queue_status" in msg:
            self.msg(channel, repr(self.factory.exc))
        if channel == self.args.listen_channel:
            pp = lambda m: self.threadSafeMsg(self.args.speak_channel, m)
            git_work(pp, msg, self.args.repo_owner, self.factory.exc)

    def threadSafeMsg(self, channel, message):
        reactor.callFromThread(self.msg, channel, message)


class GitBotFactory(protocol.ClientFactory):
    protocol = GitBot

    def __init__(self, args, exc):
        self.args, self.exc = args, exc

    def clientConnectionLost(self, connector, reason):
        err = reason.getErrorMessage()
        log.warn("Lost connection, reconnecting. Error: %s" % err)
        time.sleep(1)
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        err = reason.getErrorMessage()
        log.error("Could not connect, reconnecting. Error: %s" % err)
        time.sleep(1)
        connector.connect()


# =============================================================================
# Git work
# =============================================================================


class LaborExchange(object):
    def __init__(self):
        self.cond = threading.Condition(threading.Lock())
        self.q = OrderedDict()
        self.wip = set()

    def __repr__(self):
        with self.cond:
            return "Queue: %s, WIP: %s" % (self.q.keys(), list(self.wip))

    def add(self, repo, job):
        with self.cond:
            if not (repo in self.wip and repo in self.q.keys()):
                self.q[repo] = job
                self.cond.notifyAll()

    def get_and_start(self):
        self.cond.acquire()
        while not [repo for repo in self.q if repo not in self.wip]:
            self.cond.wait()
        repo, val = self.q.popitem(False)
        self.wip.add(repo)
        self.cond.release()
        return repo, val

    def finished(self, repo):
        with self.cond:
            self.wip.remove(repo)


def git_clone(pp, repo, attempt_no, args, exc):
    log.debug("Starting to clone %s for %d time" % (repo, attempt_no))
    repo_url = "git@github.com:%s/%s.git" % (args.repo_owner, repo)
    if attempt_no == 5:
        msg = "%d times failed to clone %s, giving up" % (attempt_no, repo)
        pp(msg), log.error(msg)
        exc.finished(repo)
        return

    cmd = ["git", "clone", "--quiet", "--bare", repo_url, repo_dir(args, repo)]
    if subprocess.call(cmd) == 0:
        msg = "%s successfully cloned" % repo_url
        log.info(msg), pp(msg)
        exc.finished(repo)
    else:
        msg = "%d'th error cloning %s. Enqueuing job after 60 secs" % \
                (attempt_no, repo)
        log.warn(msg), pp(msg)
        desc = {'pp': pp, 'repo': repo, 'attempt_no': attempt_no + 1}
        exc.finished(repo)
        threading.Timer(60, lambda: exc.add(repo, desc)).start()


def git_fetch(pp, repo, attempt_no, args, exc):
    log.debug("Starting to fetch %s for %d time" % (repo, attempt_no))
    repo_url = "git@github.com:%s/%s.git" % (args.repo_owner, repo)
    if attempt_no == 5:
        msg = "5 times failed to fetch %s, giving up" % repo
        pp(msg), log.error(msg)
        exc.finished(repo)
        return

    env = os.environ.copy()
    env['GIT_DIR'] = repo_dir(args, repo)
    cmd = ["git", "fetch", "--prune", "--tags", "--quiet", repo_url]
    if subprocess.call(cmd, env=env) == 0:
        msg = "%s successfully fetched" % repo_url
        log.info(msg), pp(msg)
        exc.finished(repo)
    else:
        msg = "%d'th error fetching %s. Queuing retry in 60 secs" % \
                (attempt_no, repo)
        pp(msg), log.warn(msg)
        desc = {'pp': pp, 'repo': repo, 'attempt_no': attempt_no + 1}
        exc.finished(repo)
        threading.Timer(60, lambda: exc.add(repo, desc)).start()


def git_work(pp, msg, repo_owner, exc):
    """IRC-unaware git worker. pp is a status printer function"""
    ma = re.match(".*https://github.com/%s/([\w_.-]+)/.*" % repo_owner, msg)
    if ma:
        repo = ma.group(1)
        pp("enqueueing %s/%s" % (repo_owner, repo))
        exc.add(repo, {'pp': pp, 'repo': ma.group(1), 'attempt_no': 0})


def worker_entry(pp, args, exc):
    "Entry to worker thread. Gets operations from exc and does work"
    log.debug("Started worker")
    while True:
        repo, v = exc.get_and_start()
        if os.path.exists(repo_dir(args, repo)):
            pp("repository %s already on disk. Fetching..." % repo)
            git_fetch(pp, repo, v['attempt_no'], args, exc)
        else:
            pp("repository %s does not exist yet. Cloning..." % repo)
            git_clone(pp, repo, v['attempt_no'], args, exc)


def repo_dir(args, repo):
    return os.path.join(args.git_dir, args.repo_owner, "%s.git" % repo)


def parse_args():
    parser = argparse.ArgumentParser(
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    irc_gr = parser.add_argument_group("IRC options")
    irc_gr.add_argument('-s', '--server', default='irc.freenode.net',
            help="IRC host")
    irc_gr.add_argument('-P', '--port', default=6667, type=int,
            help="IRC port")
    irc_gr.add_argument('-p', '--password', help="Server password")
    irc_gr.add_argument('--ssl', action='store_true', default=False,
            help="Use SSL")
    irc_gr.add_argument('-n', '--nickname', default='dcvsyoda',
            help="Bot nickname")
    irc_gr.add_argument('-c', '--speak-channel', default='#dcvs',
            help="Where bot speaks up")
    irc_gr.add_argument('-l', '--listen-channel', default='#github',
            help="Where bot listens for requests")

    git_gr = parser.add_argument_group("Git options")
    git_gr.add_argument('-o', '--repo-owner', default='spilgames',
            help="Whos repositories to match and clone")
    git_gr.add_argument('-d', '--git-dir', default='/bigdisk/git',
            help="Directory for repositories and log files")

    parser.add_argument('-w', '--num-workers', default=5,
            help="Number of git workers")
    return parser.parse_args()


def main():
    args = parse_args()

    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    fh = logging.FileHandler(os.path.join(args.git_dir, 'dcvs.debug.log'))
    ch.setLevel(logging.INFO)
    fh.setLevel(logging.DEBUG)
    log.addHandler(fh)
    log.addHandler(ch)
    chf = logging.Formatter(('[%(process)d] %(asctime)s - '
        '%(levelname)s - %(message)s'), "%H:%M:%S")
    ch.setFormatter(chf)
    fhf = logging.Formatter('[%(process)d] %(asctime)s - '
        '%(levelname)s - %(message)s')
    fh.setFormatter(fhf)

    if args.ssl:
        point = SSL4ClientEndpoint(reactor, args.server, args.port,
                CertificateOptions())
    else:
        point = TCP4ClientEndpoint(reactor, args.server, args.port)
    exc = LaborExchange()
    point.connect(GitBotFactory(args, exc))
    reactor.run()

if __name__ == '__main__':
    main()
