# Github cloner

### Description

This bot listens for github IRC bot notifications and fetches pre-configured
repositories.

For example, if someone in a channel says:

    [pu] Motiejus pushed 3 new commits to pu: https://github.com/spilgames/rebar/compare/pu~3...spilgames:pu

The bot will start downloading (cloning if it is new, fetching otherwise) the
repository `git@github.com/spilgames/rebar.git`.

Then the repository can be safely and speedily be served locally.

### Usage

`./bot.py` by default connects to `irc.freenet.net:6667` with nick `dcvsyoda`
in channels `#dcvs` and `#github`. To change these (and other) settings, please
do:

    ./bot.py --help

To start github joining the channel and giving benefit, you should configure an
IRC service hook for your project (Settings →  Service Hooks →  IRC).

### Dependencies

This bot depends on following modules:
* `argparse` (in standard library since 2.7)
* `ordereddict` (in standard library since 2.7)
* `twisted` (irc protocol)
* git in `$PATH`

It has been tested with Python 2.7, but should work fine with Python 2.6.
