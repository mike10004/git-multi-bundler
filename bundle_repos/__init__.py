#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script that archives multiple git repositories."""

# pylint: disable=C0301
# pylint: disable=missing-docstring

import time
import re
import urllib.parse
import sys
import os.path
import os
import logging
import tempfile
import subprocess
from collections import defaultdict

if sys.version_info[0] != 3:
    sys.stderr.write("requires Python 3\n")
    sys.exit(1)

_log = logging.getLogger(__name__)
_DEFAULT_USERNAME = 'git' # works for github.com and bitbucket.org, which is all we need for now
_SUPPORTED_SCHEMES = ('https',)
ERR_USAGE = 1
ERR_BUNDLE_FAIL = 2
_GIT_ENV = {'GIT_TERMINAL_PROMPT': '0'}
_GIT_VERSION_MAJOR_MIN = 2
_GIT_VERSION_MINOR_MIN = 3
_GIT_VERSION_MIN = (_GIT_VERSION_MAJOR_MIN, _GIT_VERSION_MINOR_MIN)
_ENV_THROTTLE_DELAY = 'BUNDLE_REPOS_THROTTLE'
_DEFAULT_THROTTLER_DELAY_SECONDS = 1.0

class BundleConfig(object):

    def __init__(self):
        self.ignore_rev = False
        self.throttler = Throttler(_DEFAULT_THROTTLER_DELAY_SECONDS)

class GitExecutionException(Exception):
    pass

class GitExitCodeException(GitExecutionException):

    def __init__(self, proc):
        if isinstance(proc, subprocess.CompletedProcess):
            super(GitExitCodeException, self).__init__("git exit code = {}".format(proc.returncode))
        else:
            super(GitExitCodeException, self).__init__(proc)

class GitVersionException(GitExecutionException):
    
    def __init__(self, version):
        super(GitVersionException, self).__init__("git version >= {} is required; actual version is {}", _GIT_VERSION_MIN, version), 

class Repository(object):

    """Class that represents a git repository."""

    def __init__(self, url):
        self.url = url
        result = urllib.parse.urlparse(url) # scheme://netloc/path;parameters?query#fragment
        assert result.port is None   # port not supported here
        self.host = result.hostname
        assert self.host is not None and self.host != ''
        path_parts = list(filter(lambda p: p != '', result.path.split('/')))
        self.path_prefix = '/'.join(path_parts[:-1])
        self.repo_name = path_parts[-1]
        self.username = result.username or _DEFAULT_USERNAME
        assert self.path_prefix
        self.scheme = result.scheme
        assert self.scheme in _SUPPORTED_SCHEMES

    def decoded_path_prefix(self):
        return urllib.parse.unquote_plus(self.path_prefix, errors='strict')

    def decoded_repo_name(self):
        return urllib.parse.unquote_plus(self.repo_name, errors='strict')

    def make_bundle_path(self, parent):
        return os.path.join(parent, self.host, self.decoded_path_prefix(), self.decoded_repo_name() + '.bundle')

    def __str__(self):
        return "Repository{{{}}}".format(self.url)

class Throttler(object):

    def __init__(self, delay_seconds):
        """Construct an instance with the given delay"""
        self.delay = float(delay_seconds)
        assert self.delay >= 0, "delay must be >= 0: {}".format(self.delay)
        self.most_recent = defaultdict(float)
    
    def throttle(self, category=''):
        last_call = self.most_recent[category]
        current = time.time()
        interval = current - last_call
        if interval < self.delay:
            self.sleep(self.delay - interval, category)
        self.most_recent[category] = time.time()
    
    def sleep(self, duration, category):
        _log.debug("category=%s; sleeping for %s", category, duration)
        time.sleep(duration)

    @classmethod
    def no_delay(cls):
        return Throttler(0.0)

class GitRunner(object):

    """Shortcut for invoking subprocess.run"""

    def __init__(self, executable, env=_GIT_ENV):
        self.executable = executable
        self.env = env

    def run(self, cmd, **kwargs):
        _log.debug("executing %s", cmd)
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, executable=self.executable, env=self.env, **kwargs)

_GIT_CMD_PRINT_LATEST_COMMIT = ['git', 'for-each-ref', '--count', '1', '--sort=committerdate', 'refs/heads/']

def read_git_latest_commit(clone_dir, git_runner=None):
    git_runner = git_runner or GitRunner('git')
    proc = git_runner.run(_GIT_CMD_PRINT_LATEST_COMMIT, cwd=clone_dir)
    if proc.returncode != 0:
        _log.error(proc.stderr)
        raise GitExitCodeException(proc)
    return proc.stdout.decode('utf-8').split()[0]

def check_bundle_required(config, remote_clone_path, bundle_path, clone_dest_dir_parent, git_runner):
    """Checks whether the latest commit on any branch is the same for a repository path and a bundle"""
    if config.ignore_rev or not os.path.exists(bundle_path):
        return True
    remote_clone_revision = read_git_latest_commit(remote_clone_path, git_runner)
    bundle_clone_dir = tempfile.mkdtemp(prefix='bundle-clone-', dir=clone_dest_dir_parent)
    proc = git_runner.run(['git', 'clone', '-ns', bundle_path, bundle_clone_dir])
    if proc.returncode != 0:
        _log.error(proc.stderr)
        raise GitExitCodeException(proc)
    bundle_revision = read_git_latest_commit(bundle_clone_dir, git_runner)
    return bundle_revision != remote_clone_revision

class Bundler(object):

    def __init__(self, treetop, tempdir, git='git', config=None):
        self.config = config or BundleConfig()
        self.treetop = treetop
        assert treetop, "treetop must be nonempty string"
        self.tempdir = tempdir
        assert os.path.isdir(tempdir), "not a directory: {}".format(tempdir[:128])
        self.git_runner = GitRunner(git)

    def bundle(self, repo):
        _log.debug("bundling %s to %s", repo, self.treetop)
        with tempfile.TemporaryDirectory(prefix='clone-dest-parent', dir=self.tempdir) as clone_dest_dir_parent:
            clone_dest_dir = tempfile.mkdtemp(prefix='clone-dest', dir=clone_dest_dir_parent)
            proc = self.git_runner.run(['git', 'clone', '--mirror', repo.url, clone_dest_dir])
            if proc.returncode != 0:
                _log.error("cloning %s failed: %s", repo.url, proc)
                return None
            bundle_path = repo.make_bundle_path(self.treetop)
            bundle_dir = os.path.dirname(bundle_path)
            os.makedirs(bundle_dir, exist_ok=True)
            proc = self.git_runner.run(['git', 'bundle', 'create', bundle_path, '--all'], cwd=clone_dest_dir)
            if proc.returncode != 0:
                _log.error("bundling %s as %s (from %s) failed: %s", clone_dest_dir, bundle_path, repo, proc)
                return None
            _log.info("bundled %s as %s", repo, bundle_path)
            return bundle_path

    def bundle_all(self, repo_urls):
        num_ok = 0
        repos = list(map(lambda url: Repository(url), repo_urls)) # fail fast if any repos are invalid
        for repo in repos:
            self.config.throttler.throttle(repo.host)
            if self.bundle(repo):
                num_ok += 1
        return num_ok

def read_git_version():
    """Execute `git --version` and return a tuple of ints representing the version"""
    proc = GitRunner('git').run(['git', '--version'])
    if proc.returncode != 0:
        _log.error(proc.stderr)
        raise GitExitCodeException(proc);
    text = proc.stdout.decode('utf-8', 'strict').strip()
    m = re.match(r'^git version (\d+)\.(\d+)(?:\.(\d+))?.*$', text)
    if m is None:
        raise ValueError("unexpected stdout from git --version: {}".format(text[:64]));
    return tuple(map(int, filter(lambda n: n is not None, m.groups())))

def check_git_version(git_version):
    """Check that the version of git that is available meets our minimum requirements (>=2.3)."""
    assert isinstance(git_version, tuple), "git_version must be a tuple of ints"
    assert len(tuple(filter(lambda n: 1 if isinstance(n, int) else 0, git_version))) == len(git_version), "all tuple values must be ints"
    major = git_version[0]
    if major < _GIT_VERSION_MAJOR_MIN:
        raise GitVersionException(git_version)
    if major == _GIT_VERSION_MAJOR_MIN:
        minor = git_version[1]
        if minor < _GIT_VERSION_MINOR_MIN:
            raise GitVersionException(git_version)

def main(argv=None): 
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument('indexfile', help="file listing one repository URL per line")
    parser.add_argument('-l', '--log-level', choices=('DEBUG', 'INFO', 'WARN', 'ERROR'), default='INFO', help='set log level', metavar='LEVEL')
    parser.add_argument('--temp-dir', metavar='DIRNAME', help='set temp directory')
    parser.add_argument('--bundles-dir', default=os.path.join(os.getcwd(), 'repositories'), metavar='DIRNAME', help='set bundles tree top directory')
    default_throttle_delay = os.getenv(_ENV_THROTTLE_DELAY, str(_DEFAULT_THROTTLER_DELAY_SECONDS))
    try:
        default_throttle_delay = float(default_throttle_delay)
    except ValueError:
        _log.error("could not parse value of {} environment variable {}".format(_ENV_THROTTLE_DELAY, default_throttle_delay[:32]))
        return ERR_USAGE
    parser.add_argument('--delay', default=default_throttle_delay, type=float, help="set per-host throttling delay (or use " + _ENV_THROTTLE_DELAY + " environment variable)", metavar='SECONDS')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.__dict__[args.log_level])
    check_git_version(read_git_version())
    with open(args.indexfile, 'rb') as ifile:
        urls = ifile.read().decode('utf-8', 'strict').split()
    urls = list(filter(lambda url: len(url.strip()) > 0, urls)) # ignore blank lines
    _log.debug("%s repository urls in %s", len(urls), args.indexfile)
    config = BundleConfig()
    bundler = Bundler(args.bundles_dir, args.temp_dir, 'git', config)
    num_ok = bundler.bundle_all(urls)
    if num_ok == 0:
        _log.error("no bundlings succeeded out of %s urls", len(urls))
        return ERR_BUNDLE_FAIL
    if num_ok < len(urls):
        _log.warn("only %s of %s bundlings succeeded", num_ok, len(urls))
    return 0
