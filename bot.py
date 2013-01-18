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

log = logging.getLogger(__name__)

IRC_SSL = bool(os.environ.get("IRC_SSL", False))
IRC_NICKNAME = os.environ.get("IRC_NICKNAME", "dcvsyoda")
IRC_PASSWORD = os.environ.get("IRC_PASSWORD", None)
IRC_SPEAK_CHANNEL = os.environ.get("IRC_SPEAK_CHANNEL", "#dcvs")
IRC_LISTEN_CHANNEL = os.environ.get("IRC_LISTEN_CHANNEL", "#github")
IRC_HOST = os.environ.get("IRC_HOST", "irc.freenode.net")
IRC_PORT = int(os.environ.get("IRC_PORT", 6667))

NUM_WORKERS = int(os.environ.get("NUM_WORKERS", 5))
REPO_OWNER = os.environ.get("REPO_OWNER", "Motiejus")
GIT_DIR = "/bigdisk/git"

# =============================================================================
# IRC stuff
# =============================================================================


class GitBot(irc.IRCClient):
    nickname = IRC_NICKNAME
    password = IRC_PASSWORD

    def signedOn(self):
        self.join(IRC_LISTEN_CHANNEL)
        if IRC_LISTEN_CHANNEL != IRC_SPEAK_CHANNEL:
            self.join(IRC_SPEAK_CHANNEL)
        log.info("Signed on as %s" % self.nickname)

    def joined(self, channel):
        log.info("Joined %s" % channel)
        if channel == IRC_LISTEN_CHANNEL:
            log.debug("Starting %d workers" % NUM_WORKERS)
            for i in range(NUM_WORKERS):
                pp = lambda m: self.threadSafeMsg(IRC_SPEAK_CHANNEL, m)
                threading.Thread(target=worker_entry, args=(pp,)).start()

    def privmsg(self, user, channel, msg):
        log.debug("Message from %s at %s: %s" %
                (user.split("!")[0], channel, msg))
        if "!help" in msg:
            self.threadSafeMsg(channel, "I can answer !help and !queue_status")
        if "!queue_status" in msg:
            self.threadSafeMsg(channel, repr(exc))
        if channel == IRC_LISTEN_CHANNEL:
            git_work(lambda m: self.threadSafeMsg(IRC_SPEAK_CHANNEL, m), msg)

    def threadSafeMsg(self, channel, message):
        reactor.callFromThread(self.msg, channel, message)


class GitBotFactory(protocol.ClientFactory):
    protocol = GitBot

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
        self.wip.remove(repo)


exc = LaborExchange()


def git_clone(pp, repo, attempt_no):
    log.debug("Starting to clone %s for %d time" % (repo, attempt_no))
    repo_url = "git@github.com:%s/%s.git" % (REPO_OWNER, repo)
    if attempt_no == 5:
        pp("%d times failed to clone %s, giving up" % attempt_no)
        log.error("Given up on cloning %s after %d times" % (repo, attempt_no))
        exc.finished(repo)
        return

    cmd = ["git", "clone", "--quiet", "--bare", repo_url, repo_dir(repo)]
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
        threading.Timer(60, lambda: exc.add(repo, desc))


def git_fetch(pp, repo, attempt_no):
    log.debug("Starting to fetch %s for %d time" % (repo, attempt_no))
    repo_url = "git@github.com:%s/%s.git" % (REPO_OWNER, repo)
    if attempt_no == 5:
        msg = "5 times failed to fetch %s, giving up" % repo
        pp(msg), log.error(msg)
        exc.finished(repo)
        return

    env = os.environ.copy()
    env['GIT_DIR'] = repo_dir(repo)
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
        threading.Timer(60, lambda: exc.add(repo, desc))


def git_work(pp, msg):
    """IRC-unaware git worker. pp is a status printer function"""
    ma = re.match(".*https://github.com/%s/([\w_.-]+)/.*" % REPO_OWNER, msg)
    if ma:
        repo = ma.group(1)
        pp("enqueueing %s/%s" % (REPO_OWNER, repo))
        exc.add(repo, {'pp': pp, 'repo': ma.group(1), 'attempt_no': 0})


def worker_entry(pp):
    log.debug("Started worker")
    while True:
        "Entry to worker thread. Gets operations from exc and does work"
        repo, v = exc.get_and_start()
        if os.path.exists(repo_dir(repo)):
            pp("repository %s already on disk. Fetching..." % repo)
            git_fetch(pp, repo, v['attempt_no'])
        else:
            pp("repository %s does not exist yet. Cloning..." % repo)
            git_clone(pp, repo, v['attempt_no'])


def repo_dir(repo):
    return os.path.join(GIT_DIR, REPO_OWNER, "%s.git" % repo)


def main():
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    fh = logging.FileHandler(os.path.join(GIT_DIR, 'dcvs.debug.log'))
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

    if IRC_SSL:
        point = SSL4ClientEndpoint(reactor, IRC_HOST, IRC_PORT,
                CertificateOptions())
    else:
        point = TCP4ClientEndpoint(reactor, IRC_HOST, IRC_PORT)
    point.connect(GitBotFactory())
    reactor.run()

if __name__ == '__main__':
    main()
