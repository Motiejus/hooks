# Github cloner

### Description

This bot listens for github IRC bot notifications and fetches pre-configured
repositories to the local machine. The local machine becomes read-only mirror
for speedy local fetching from CI, development, staging machines and etcetra.

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

---

### How it works

**Conclusions**
You cannot have >1 element in the queue (hence `OrderedDict` type for queue)
You can have a thread working on an item AND the item in the queue (assume
two changes come in a short interval). In that case the second job will be 
given out only after the first finishes (reason for `wip` set).

**High level description**

There are 5 worker threads (configurable). Once a message in `listen-channel`
is posted, it is matched against `".*https://github.com/%s/([\w_.-]+)/.*" %
repo_owner` regular expression. Then the `$1` part is added to the queue
(`exc`).

`LaborExchange` (instance name `exc`) works as follows:

A new job is added to the end of the queue by any producer, if it is not in the
queue already.

When a consumer (one of the 5 threads) asks for a job (`exc.get_and_start`), it
is both removed from the queue and is added to the "work in progress" (`wip`)
set. Only jobs that are in the queue and not in `wip` are given to a worker.

When worker is done with a job, it "finishes" the work by calling
`exc.finished` which removes the job from `wip`.

