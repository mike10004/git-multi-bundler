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

_log = logging.getLogger(__name__)
_DEFAULT_USERNAME = 'git' # works for github.com and bitbucket.org, which is all we need for now
_SUPPORTED_SCHEMES = ('https',)
ERR_BUNDLE_FAIL = 2
_GIT_ENV = {'GIT_TERMINAL_PROMPT': '0'}
_GIT_VERSION_MAJOR_MIN = 2
_GIT_VERSION_MINOR_MIN = 3
_GIT_VERSION_MIN = (_GIT_VERSION_MAJOR_MIN, _GIT_VERSION_MINOR_MIN)

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

def bundle(repo, treetop, tempdir=None, git='git'):
    _log.debug("bundling %s to %s", repo, treetop)
    with tempfile.TemporaryDirectory(prefix='clone-dest-parent', dir=tempdir) as clone_dest_dir_parent:
        clone_dest_dir = tempfile.mkdtemp(prefix='clone-dest', dir=clone_dest_dir_parent)
        cmd = ['git', 'clone', '--mirror', repo.url, clone_dest_dir]
        _log.debug("executing %s", cmd)
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, executable=git, env=_GIT_ENV)
        if proc.returncode != 0:
            _log.error("cloning %s failed: %s", repo.url, proc)
            return None
        bundle_path = repo.make_bundle_path(treetop)
        bundle_dir = os.path.dirname(bundle_path)
        os.makedirs(bundle_dir, exist_ok=True)
        cmd = [git, 'bundle', 'create', bundle_path, '--all']
        _log.debug("executing %s", cmd)
        proc = subprocess.run(cmd, cwd=clone_dest_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, executable=git, env=_GIT_ENV)
        if proc.returncode != 0:
            _log.error("bundling %s as %s (from %s) failed: %s", clone_dest_dir, bundle_path, repo, proc)
            return None
        _log.info("bundled %s as %s", repo, bundle_path)
        return bundle_path

_DEFAULT_THROTTLER_DELAY_SECONDS = 1.0

def bundle_all(repo_urls, treetop, tempdir=None, git='git', throttler=None):
    if throttler is None: 
        throttler = Throttler(_DEFAULT_THROTTLER_DELAY_SECONDS)
    num_ok = 0
    repos = list(map(lambda url: Repository(url), repo_urls)) # fail fast if any repos are invalid
    for repo in repos:
        throttler.throttle(repo.host)
        if bundle(repo, treetop, tempdir, git):
            num_ok += 1
    return num_ok

class GitExecutionException(Exception):
    pass

class GitVersionException(Exception):
    
    def __init__(self, version):
        super(GitVersionException, self).__init__("git version >= {} is required; actual version is {}", _GIT_VERSION_MIN, version), 

def read_git_version():
    """Execute `git --version` and return a tuple of ints representing the version"""
    proc = subprocess.run(['git', '--version'], stdout=subprocess.PIPE, stderr=sys.stderr, env=_GIT_ENV)
    if proc.returncode != 0:
        raise GitExecutionException("git returned {}".format(proc.returncode));
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
    parser.add_argument('--delay', default=1.0, type=float, help="set per-host throttling delay", metavar='SECONDS')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.__dict__[args.log_level])
    check_git_version(read_git_version())
    with open(args.indexfile, 'rb') as ifile:
        urls = ifile.read().decode('utf-8', 'strict').split()
    urls = list(filter(lambda url: len(url.strip()) > 0, urls)) # ignore blank lines
    _log.debug("%s repository urls in %s", len(urls), args.indexfile)
    num_ok = bundle_all(urls, args.bundles_dir, args.temp_dir)
    if num_ok == 0:
        _log.error("no bundlings succeeded out of %s urls", len(urls))
        return ERR_BUNDLE_FAIL
    if num_ok < len(urls):
        _log.warn("only %s of %s bundlings succeeded", num_ok, len(urls))
    return 0

if __name__ == '__main__':
    exit(main())
