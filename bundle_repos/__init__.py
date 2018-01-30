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
import pathlib
from collections import defaultdict


if sys.version_info[0] != 3:
    sys.stderr.write("requires Python 3\n")
    sys.exit(1)


_log = logging.getLogger(__name__)
_DEFAULT_USERNAME = 'git' # works for github.com and bitbucket.org, which is all we need for now
_SUPPORTED_SCHEMES = ('https', 'file')
ERR_USAGE = 1
ERR_BUNDLE_FAIL = 2
FILESYSTEM_DIR_BASENAME = '_filesystem'
_GIT_ENV = {'GIT_TERMINAL_PROMPT': '0'}
_GIT_VERSION_MAJOR_MIN = 2
_GIT_VERSION_MINOR_MIN = 3
_GIT_VERSION_MIN = (_GIT_VERSION_MAJOR_MIN, _GIT_VERSION_MINOR_MIN)
_ENV_THROTTLE_DELAY = 'BUNDLE_REPOS_THROTTLE'
_DEFAULT_THROTTLER_DELAY_SECONDS = 1.0
_GIT_CMD_PRINT_LATEST_COMMIT = ('git', 'for-each-ref', '--count', '1', '--sort=-committerdate', 'refs/heads/')


class BundleConfig(object):

    def __init__(self, **kwargs):
        # set defaults and then apply kwargs
        self.ignore_rev = False
        self.throttler = Throttler(_DEFAULT_THROTTLER_DELAY_SECONDS)
        for k in kwargs:
            getattr(self, k)  # make sure attribute default has been defined
            setattr(self, k, kwargs[k])


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


def check_no_file_separator_chars(parts):
    for p in parts:
        if '/' in p:
            raise ValueError("URL path must not contain / character (escaped as %2F)")


class Repository(object):

    """Class that represents a git repository."""

    def __init__(self, url):
        self.url = url
        result = urllib.parse.urlparse(url) # scheme://netloc/path;parameters?query#fragment
        self.scheme = result.scheme
        assert self.scheme in _SUPPORTED_SCHEMES, "not a supported scheme: {} (in {})".format(repr(result.scheme), url)
        assert result.port is None   # port not supported here for now; make_bundle_path naming convention would have to be adjusted
        self.host = '_filesystem' if result.scheme == 'file' else result.hostname
        assert self.scheme == 'file' or (self.host is not None and self.host != ''), "host is required if scheme is not 'file'"
        path_parts = list(filter(lambda p: p != '', result.path.split('/')))
        decoded_path_prefix_parts = [urllib.parse.unquote_plus(p, errors='strict') for p in path_parts[:-1]]
        self._decoded_path_prefix = '/'.join(decoded_path_prefix_parts)
        check_no_file_separator_chars(decoded_path_prefix_parts)
        self.path_prefix = '/'.join(path_parts[:-1])
        self.repo_name = path_parts[-1]
        self._decoded_repo_name = urllib.parse.unquote_plus(self.repo_name, errors='strict')
        check_no_file_separator_chars((self._decoded_repo_name,))
        self.username = result.username or _DEFAULT_USERNAME
        assert self.path_prefix
    
    def get_repository_argument(self):
        """Gets the string to be used as the `git clone` argument."""
        if self.scheme == 'file':
            parsed = urllib.parse.urlparse(self.url)
            return urllib.parse.unquote_plus(parsed.path)
        else:
            return self.url
    
    def decoded_path_prefix(self):
        return self._decoded_path_prefix

    def decoded_repo_name(self):
        return self._decoded_repo_name

    def make_bundle_path(self, parent):
        """Construct the pathname of the bundle that is to represent this repository
           in the filesystem beneath the given parent directory. Note that bundles created
           from source bundles will have a .bundle.bundle suffix."""
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

    def run_clean(self, cmd, **kwargs):
        proc = self.run(cmd, **kwargs)
        self._check_clean(proc)
        return proc

    def _check_clean(self, proc):
        if proc.returncode != 0:
            _log.error("exit code %s for %s:\n%s\n", proc.returncode, proc.args, proc.stderr)
            raise GitExitCodeException(proc)

    def _clone_mirrored(self, repo_arg, clone_dest_dir, clean):
        os.makedirs(clone_dest_dir, exist_ok=True)
        clone_dest_git_dir = os.path.join(clone_dest_dir, '.git')
        clone_proc = self.run(['git', 'clone', '--mirror', repo_arg, clone_dest_git_dir])
        if clean:
            self._check_clean(clone_proc)
        elif clone_proc.returncode != 0:
            return clone_proc
        config_proc = self.run(['git', 'config', '--bool', 'core.bare', 'false'], cwd=clone_dest_dir)
        if clean:
            self._check_clean(config_proc)
        return clone_proc

    def clone_mirrored(self, repo_arg, clone_dest_dir):
        return self._clone_mirrored(repo_arg, clone_dest_dir, False)

    def clone_mirrored_clean(self, repo_arg, clone_dest_dir):
        return self._clone_mirrored(repo_arg, clone_dest_dir, True)


def read_git_latest_commit(clone_dir, git_runner=None):
    git_runner = git_runner or GitRunner('git')
    proc = git_runner.run(_GIT_CMD_PRINT_LATEST_COMMIT, cwd=clone_dir)
    if proc.returncode != 0:
        _log.error(proc.stderr)
        raise GitExitCodeException(proc)
    return proc.stdout.decode('utf-8').split()[0]


def read_git_latest_commit_from_bundle(bundle_path, tempdir, git_runner=None):
    git_runner = git_runner or GitRunner('git')
    with tempfile.TemporaryDirectory(dir=tempdir) as bundle_clone_dir:
        git_runner.clone_mirrored_clean(bundle_path, bundle_clone_dir)
        return read_git_latest_commit(bundle_clone_dir, git_runner)


class Bundler(object):

    def __init__(self, treetop, tempdir, git='git', config=None):
        self.config = config or BundleConfig()
        assert isinstance(self.config, BundleConfig), "config must be a BundleConfig instance"
        self.treetop = treetop
        assert treetop, "treetop must be nonempty string"
        self.tempdir = tempdir
        assert tempdir is None or os.path.isdir(tempdir), "not a directory: {}".format(tempdir[:128])
        self.git_runner = GitRunner(git)

    def check_bundle_required(self, remote_clone_path, bundle_path, clone_dest_dir_parent):
        """Checks whether the latest commit on any branch is the same for a repository path and a bundle."""
        if self.config.ignore_rev or not os.path.exists(bundle_path):
            return True
        remote_clone_revision = read_git_latest_commit(remote_clone_path, self.git_runner)
        bundle_revision = read_git_latest_commit_from_bundle(bundle_path, clone_dest_dir_parent, self.git_runner)
        return bundle_revision != remote_clone_revision

    def bundle(self, repo):
        _log.debug("bundling %s to %s", repo, self.treetop)
        with tempfile.TemporaryDirectory(prefix='clone-dest-parent', dir=self.tempdir) as clone_dest_dir_parent:
            clone_dest_dir = tempfile.mkdtemp(prefix='clone-dest', dir=clone_dest_dir_parent)
            repo_arg = repo.get_repository_argument()
            proc = self.git_runner.clone_mirrored(repo_arg, clone_dest_dir)
            if proc.returncode != 0:
                _log.error("exit code %s indicates failure to clone %s using command %s", proc.returncode, repo, proc.args)
                _log.error(proc.stderr)
                return None
            bundle_path = repo.make_bundle_path(self.treetop)
            if self.check_bundle_required(clone_dest_dir, bundle_path, clone_dest_dir_parent):
                bundle_dir = os.path.dirname(bundle_path)
                os.makedirs(bundle_dir, exist_ok=True)
                proc = self.git_runner.run(['git', 'bundle', 'create', bundle_path, '--all'], cwd=clone_dest_dir)
                if proc.returncode != 0:
                    _log.error("bundling %s as %s (from %s) failed: %s", clone_dest_dir, bundle_path, repo, proc)
                    return None
                _log.info("bundled %s as %s", repo, bundle_path)
            else:
                _log.info("skipped bundling %s because synchronized bundle already exists at %s", repo, bundle_path)
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


def clean_index_urls(urls):
    urls = filter(lambda url: len(url.strip()) > 0, urls) # ignore blank lines
    urls = filter(lambda url: not url.lstrip().startswith('#'), urls)
    return list(urls)


def get_lines(text):
    return re.split(r'[\n\r]+', text)


def main(argv=None): 
    from argparse import ArgumentParser
    DEFAULT_BUNDLES_DIR = os.path.join(os.getcwd(), 'repositories')
    parser = ArgumentParser()
    parser.add_argument('indexfile', help="file listing one repository URL per line")
    parser.add_argument('-l', '--log-level', choices=('DEBUG', 'INFO', 'WARN', 'ERROR'), default='INFO', help="set log level", metavar='LEVEL')
    parser.add_argument('--temp-dir', metavar='DIRNAME', help="set temp directory")
    parser.add_argument('--bundles-dir', default=DEFAULT_BUNDLES_DIR, metavar='DIRNAME', help="set bundles tree top directory")
    parser.add_argument('--ignore-rev', default=False, action='store_true', help="force bundle creation whether or not existing bundle already has the latest commit")
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
        urls = get_lines(ifile.read().decode('utf-8', 'strict'))
    urls = clean_index_urls(urls)
    _log.debug("%s repository urls in %s", len(urls), args.indexfile)
    if len(urls) == 0:
        _log.error("index does not contain any repository URLs")
        return 1
    config = BundleConfig(ignore_rev=args.ignore_rev)
    bundler = Bundler(args.bundles_dir, args.temp_dir, 'git', config)
    num_ok = bundler.bundle_all(urls)
    if num_ok == 0:
        _log.error("no bundlings succeeded out of %s urls", len(urls))
        return ERR_BUNDLE_FAIL
    if num_ok < len(urls):
        _log.warn("only %s of %s bundlings succeeded", num_ok, len(urls))
    return 0
