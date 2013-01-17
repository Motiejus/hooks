#!/usr/bin/env python
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.internet.threads import deferToThread
from twisted.internet.endpoints import TCP4ClientEndpoint, SSL4ClientEndpoint
from twisted.internet.ssl import CertificateOptions

import os
import subprocess
import time
import logging
import re

log = logging.getLogger(__name__)

IRC_SSL = bool(os.environ.get("IRC_SSL", False))
IRC_NICKNAME = os.environ.get("IRC_NICKNAME", "dcvsyoda")
IRC_PASSWORD = os.environ.get("IRC_PASSWORD", None)
IRC_SPEAK_CHANNEL = os.environ.get("IRC_SPEAK_CHANNEL", "#dcvs")
IRC_LISTEN_CHANNEL = os.environ.get("IRC_LISTEN_CHANNEL", "#github")
IRC_HOST = os.environ.get("IRC_HOST", "irc.freenode.net")
IRC_PORT = int(os.environ.get("IRC_PORT", 6667))

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

    def privmsg(self, user, channel, msg):
        log.debug("Message from %s at %s: %s" %
                (user.split("!")[0], channel, msg))
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

cloning_now = {}


def git_clone(pp, key, repo_dir, repo_url):
    for i in range(1, 6):
        cmd = ["git", "clone", "--quiet", "--bare", repo_url, repo_dir]
        if subprocess.call(cmd) == 0:
            pp("%s successfully cloned" % cloning_now.pop(key))
            return
        else:
            pp("%d'th error cloning %s. Retrying after 60 secs" % (i, key))
            log.warn("error cloning %s for %d'th time" % (key, i))
            # just in case if there is some junk there
            subprocess.call(["rm", "-f", "-r", repo_dir])
            time.sleep(60)
    pp("5 times failed to clone %s, giving up")
    log.error("Given up on cloning %s" % key)


def git_fetch(pp, key, repo_dir, repo_url):
    for i in range(1, 6):
        env = os.environ.copy()
        env['GIT_DIR'] = repo_dir
        cmd = ["git", "fetch", "--prune", "--tags", "--quiet", repo_url]
        if subprocess.call(cmd, env=env) == 0:
            pp("%s successfully fetched" % cloning_now.pop(key))
            return
        else:
            pp("%d'th error fetching %s. Retrying after 60 secs" % (i, key))
            time.sleep(60)
    pp("5 times failed to fetch %s, giving up")
    log.error("Given up on cloning %s" % key)


def git_matched(pp, repo):
    repo_url = "git@github.com:%s/%s.git" % (REPO_OWNER, repo)
    key = "%s/%s.git" % (REPO_OWNER, repo)
    if key in cloning_now:
        pp("%s is in progress. Not doing anything" % key)
    else:
        cloning_now[key] = repo_url
        repo_dir = os.path.join(GIT_DIR, REPO_OWNER, "%s.git" % repo)
        if os.path.exists(repo_dir):
            pp("repository %s already on disk. Fetching %s..." %
                    (key, repo_url))
            deferToThread(lambda: git_fetch(pp, key, repo_dir, repo_url))
        else:
            pp("repository %s does not exist yet. Cloning %s..." %
                    (key, repo_url))
            deferToThread(lambda: git_clone(pp, key, repo_dir, repo_url))


def git_work(pp, msg):
    """IRC-unaware git worker. pp is a status printer function"""
    ma = re.match(".*https://github.com/%s/([\w_.-]+)/.*" % REPO_OWNER, msg)
    if ma:
        git_matched(pp, ma.group(1))


def main():
    log.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    fh = logging.FileHandler(os.path.join(GIT_DIR, 'dcvs.debug.log'))
    ch.setLevel(logging.INFO)
    fh.setLevel(logging.DEBUG)
    log.addHandler(fh)
    log.addHandler(ch)
    chformatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
            "%H:%M:%S")
    ch.setFormatter(chformatter)
    fhformatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(fhformatter)


    if IRC_SSL:
        point = SSL4ClientEndpoint(reactor, IRC_HOST, IRC_PORT,
                CertificateOptions())
    else:
        point = TCP4ClientEndpoint(reactor, IRC_HOST, IRC_PORT)
    point.connect(GitBotFactory())
    reactor.run()

if __name__ == '__main__':
    main()
