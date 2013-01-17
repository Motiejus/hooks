#!/usr/bin/env python
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.internet.threads import deferToThread

import os
import subprocess
import time
import logging
import re

log = logging.getLogger(__name__)

IRC_PASSWORD = os.environ.get("IRC_PASSWORD", None)
IRC_CHANNEL = os.environ.get("IRC_CHANNEL", "#yadda")
IRC_HOST = os.environ.get("IRC_HOST", "irc.freenode.net")
IRC_PORT = os.environ.get("IRC_HOST", 6667)

REPO_OWNER = os.environ.get("REPO_OWNER", "Motiejus")
GIT_DIR = "/bigdisk/git"

# =============================================================================
# IRC stuff
# =============================================================================


def aSillyBlockingMethod(bot):
    while True:
        time.sleep(10)
        msg = "10 secs passed!"
        bot.threadSafeMsg("#yadda", msg)


class MomBot(irc.IRCClient):
    def _get_nickname(self):
        return self.factory.nickname
    nickname = property(_get_nickname)

    def signedOn(self):
        self.join(self.factory.channel)
        log.info("Signed on as %s" % self.nickname)

    def joined(self, channel):
        log.info("Joined %s" % channel)
        #threads.deferToThread(aSillyBlockingMethod, self)

    def privmsg(self, user, channel, msg):
        log.debug("Message from %s: %s" % (user.split("!")[0], msg))
        git_work(lambda m: self.threadSafeMsg(IRC_CHANNEL, m), msg)

    def threadSafeMsg(self, channel, message):
        reactor.callFromThread(self.msg, channel, message)


class MomBotFactory(protocol.ClientFactory):
    protocol = MomBot

    def __init__(self, channel, nickname='yoda'):
        self.channel = channel
        self.nickname = nickname

    def clientConnectionLost(self, connector, reason):
        err = reason.getErrorMessage()
        log.info("Lost connection, reconnecting. Error: %s" % err)
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
    for i in range(1, 11):
        cmd = ["git", "clone", "--quiet", "--bare", repo_url, repo_dir]
        if subprocess.call(cmd) == 0:
            pp("%s successfully cloned" % cloning_now.pop(key))
            return
        else:
            pp("%d'th error cloning %s. Retrying after 10 secs" % (i, key))
            log.warn("error cloning %s for %d'th time" % (key, i))
            # just in case if there is some junk there
            subprocess.call(["rm", "-f", "-r", repo_dir])
            time.sleep(10)
    pp("10 times failed to clone %s, giving up")
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
            pp("%d'th error fetching %s. Retrying after 10 secs" % (i, key))
            time.sleep(10)
    pp("5 times failed to fetch %s, giving up")
    log.error("Given up on cloning %s" % key)


def git_matched(pp, repo):
    repo_url = "git@github.com:%s/%s.git" % (REPO_OWNER, repo)
    key = "%s/%s.git" % (REPO_OWNER, repo)
    if key in cloning_now:
        pp("%s is in progress. Not doing anything" % key)
    else:
        cloning_now[key] = True
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
    consoleHandler = logging.StreamHandler()
    log.addHandler(consoleHandler)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
            "%H:%M:%S")
    consoleHandler.setFormatter(formatter)

    reactor.connectTCP(IRC_HOST, IRC_PORT, MomBotFactory(IRC_CHANNEL))
    reactor.run()

if __name__ == '__main__':
    main()
