#!/usr/bin/env python
from twisted.words.protocols import irc
from twisted.internet import reactor, protocol
from twisted.internet import threads

import time
import sys
import logging

log = logging.getLogger(__name__)

class MomBot(irc.IRCClient):
    def _get_nickname(self):
        return self.factory.nickname
    nickname = property(_get_nickname)

    def signedOn(self):
        self.join(self.factory.channel)
        log.info("Signed on as %s" % self.nickname)

    def joined(self, channel):
        log.info("Joined %s" % channel)

    def privmsg(self, user, channel, msg):
        log.debug("Got message from %s: %s" % (user, msg))

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


def main():
    log.setLevel(logging.DEBUG)
    consoleHandler = logging.StreamHandler()
    log.addHandler(consoleHandler)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s',
            "%H:%M:%S")
    consoleHandler.setFormatter(formatter)

    reactor.connectTCP('irc.freenode.net', 6667, MomBotFactory('#yadda'))
    reactor.run()

if __name__ == '__main__':
    main()
