#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Script that archives multiple git repositories."""

# pylint: disable=C0301

import urllib.parse
import sys
import os.path
import os
import logging
import tempfile
import subprocess

_log = logging.getLogger(__name__)
_DEFAULT_USERNAME = 'git' # works for github.com and bitbucket.org, which is all we need for now
_SUPPORTED_SCHEMES = ('https',)
ERR_BUNDLE_FAIL = 2

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

def bundle(repo, treetop, tempdir=None, git='git'):
    _log.debug("bundling %s to %s", repo, treetop)
    with tempfile.TemporaryDirectory(prefix='clone-dest-parent', dir=tempdir) as clone_dest_dir_parent:
        clone_dest_dir = tempfile.mkdtemp(prefix='clone-dest', dir=clone_dest_dir_parent)
        cmd = ['git', 'clone', '--mirror', repo.url, clone_dest_dir]
        _log.debug("executing %s", cmd)
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, executable=git, env={'GIT_TERMINAL_PROMPT': '0'})
        if proc.returncode != 0:
            _log.error("cloning %s failed: %s", repo.url, proc)
            return None
        bundle_path = repo.make_bundle_path(treetop)
        bundle_dir = os.path.dirname(bundle_path)
        os.makedirs(bundle_dir, exist_ok=True)
        cmd = [git, 'bundle', 'create', bundle_path, '--all']
        _log.debug("executing %s", cmd)
        proc = subprocess.run(cmd, cwd=clone_dest_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, executable=git)
        if proc.returncode != 0:
            _log.error("bundling %s as %s (from %s) failed: %s", clone_dest_dir, bundle_path, repo, proc)
            return None
        _log.info("bundled %s as %s", repo, bundle_path)
        return bundle_path

def bundle_all(repo_urls, treetop, tempdir=None, git='git'):
    num_ok = 0
    repos = list(map(lambda url: Repository(url), repo_urls)) # fail fast if any repos are invalid
    for repo in repos:
        if bundle(repo, treetop, tempdir, git):
            num_ok += 1
    return num_ok

def main(): # pylint: disable=missing-docstring
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument('indexfile', help="file listing one repository URL per line")
    parser.add_argument('-l', '--log-level', choices=('DEBUG', 'INFO', 'WARN', 'ERROR'), default='INFO', help='set log level', metavar='LEVEL')
    parser.add_argument('--temp-dir', metavar='DIRNAME', help='set temp directory')
    parser.add_argument('--bundles-dir', default=os.path.join(os.getcwd(), 'repositories'), metavar='DIRNAME', help='set bundles tree top directory')
    args = parser.parse_args()
    logging.basicConfig(level=logging.__dict__[args.log_level])
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
