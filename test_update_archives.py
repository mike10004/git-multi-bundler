#!/usr/bin/python3

# -*- coding: utf-8 -*-

# pylint: disable=missing-docstring,trailing-whitespace,line-too-long,invalid-name

import stat
import tempfile
import os
import os.path
import subprocess
import sys
import unittest
import update_archives
from update_archives import Repository
import collections

if sys.version_info[0] != 3:
    sys.stderr.write("requires Python 3\n")
    sys.exit(1)

def list_files_recursively(dirpath):
    all_files = []
    for root, dirs, files in os.walk(dirpath): # pylint: disable=unused-variable
        all_files += [os.path.join(root, f) for f in files]
    return all_files

class TestRepository(unittest.TestCase):

    def test_good(self):
        url = 'https://github.com/mike10004/test-child-repo-1.git'
        r = Repository(url)
        self.assertEqual(r.url, url)
        self.assertEqual(r.scheme, 'https')
        self.assertEqual(r.host, 'github.com')
        self.assertEqual(r.path_prefix, 'mike10004')
        self.assertEqual(r.repo_name, 'test-child-repo-1.git')
    
    def test_good2(self):
        url = 'https://somewhere.else/users/mike10004/test-child-repo-1'
        r = Repository(url)
        self.assertEqual(r.url, url)
        self.assertEqual(r.scheme, 'https')
        self.assertEqual(r.host, 'somewhere.else')
        self.assertEqual(r.path_prefix, 'users/mike10004')
        self.assertEqual(r.repo_name, 'test-child-repo-1')
    
    def test_bad(self):
        with self.assertRaises(AssertionError):
            Repository('https://github.com:443/foo/bar.git')
        with self.assertRaises(AssertionError):
            Repository('https://github.com:58671/foo/bar.git')
        with self.assertRaises(AssertionError):
            Repository('http://github.com/foo/bar.git')
        with self.assertRaises(AssertionError):
            Repository('git+ssh://git@github.com/foo/bar.git')
        with self.assertRaises(AssertionError):
            Repository('https://github.com/bar.git')
    
    def test_decoded_path_prefix(self):
        url = 'https://somewhere.else/hello%40world/test-child-repo-1.git'
        r = Repository(url)
        self.assertEqual(r.decoded_path_prefix(), "hello@world")
    
    def test_make_bundle_path(self):
        url = 'https://somewhere.else/mpsycho/hello.git'
        r = Repository(url)
        self.assertEqual(r.make_bundle_path('/home/maria/repos'), '/home/maria/repos/somewhere.else/mpsycho/hello.git.bundle')

GIT_REPLACER_SCRIPT_CONTENT = """#!/bin/bash
    set -e
    echo $0 $@
    CMD=$1
    if [ "$CMD" == "clone" ] ; then
      CLONE_DEST="${@: -1:1}"             # destination dir is last argument
      mkdir -vp "$CLONE_DEST"
    elif [ "$CMD" == "bundle" ] ; then
      BUNDLE_PATH="${@: -2:1}"            # bundle pathname is penultimate argument
      touch "$BUNDLE_PATH"
    else
      echo "$CMD is not a git command" >&2
      exit 1
    fi
"""

def create_script_file(content):
    fd, scriptpath = tempfile.mkstemp(".sh", "test_update_archives_script")
    os.write(fd, content.encode('utf-8'))
    os.close(fd)
    os.chmod(scriptpath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return scriptpath    

class FakeGitUsingTestCase(unittest.TestCase):

    def setUp(self):
        self.git_script = create_script_file(GIT_REPLACER_SCRIPT_CONTENT)
    
    def tearDown(self):
        try:
            os.remove(self.git_script)
        except FileNotFoundError as ex:
            print(ex, file=sys.stderr)

class FakeGitUsingTestCaseTest(FakeGitUsingTestCase):

    def test_git_script_clone(self):
        with tempfile.TemporaryDirectory() as tempdir:
            clone_dest = os.path.join(tempdir, 'clone-destination')
            proc = subprocess.run(['git', 'clone', 'REMOTE_URL', clone_dest], stdout=subprocess.PIPE, stderr=subprocess.PIPE, executable=self.git_script)
            print(proc.stdout.decode('utf-8'))
            print(proc.stderr.decode('utf-8'), file=sys.stderr)
            self.assertEqual(proc.returncode, 0)
    
    def test_git_script_bundle(self):
        with tempfile.TemporaryDirectory() as tempdir:
            bundle_path = os.path.join(tempdir, 'my.bundle')
            proc = subprocess.run(['git', 'bundle', 'create', bundle_path, "--all"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, executable=self.git_script)
            print(proc.stdout.decode('utf-8'))
            print(proc.stderr.decode('utf-8'), file=sys.stderr)
            self.assertEqual(proc.returncode, 0)
            self.assertTrue(os.path.isfile(bundle_path), "bundle not created: " + bundle_path)

    def test_git_script_fail(self):
        proc = subprocess.run(['git', 'fail', 'yolo'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, executable=self.git_script)
        print(proc.stdout.decode('utf-8'))
        print(proc.stderr.decode('utf-8'), file=sys.stderr)
        self.assertEqual(proc.returncode, 1)

class CountingThrottler(update_archives.Throttler):

    def __init__(self, category=''):
        super(CountingThrottler, self).__init__(0.0)
        self.counts = collections.defaultdict(int)
        self.tag = 'COUNTER'
    
    def throttle(self, category):
        self.counts[category] = self.counts[category] + 1
        super(CountingThrottler, self).throttle(category)

class TestBundle(FakeGitUsingTestCase):

    def test_bundle(self):
        repo = Repository("https://localhost/hsolo/falcon.git")
        with tempfile.TemporaryDirectory() as treetop:
            bundle_name = update_archives.bundle(repo, treetop, git=self.git_script)
            print("created {}".format(bundle_name))
            expected = os.path.join(treetop, 'localhost', 'hsolo', 'falcon.git.bundle')
            self.assertEqual(bundle_name, expected)
            if not os.path.isfile(bundle_name):
                print("contents of directory {}".format(treetop), file=sys.stderr)
                for f in list_files_recursively(treetop):
                    print("  '{}'".format(f), file=sys.stderr)
            self.assertTrue(os.path.isfile(bundle_name), "expected file to exist at " + bundle_name)
    
    def test_bundle_all_throttling(self):
        repo_urls = [
            "https://github.com/octocat/Hello-World.git",
            "https://localhost/foo/bar.git",
            "https://bitbucket.org/atlassian_tutorial/helloworld.git",
            "https://github.com/Microsoft/api-guidelines",
        ]
        counter = CountingThrottler(0)
        with tempfile.TemporaryDirectory() as tmpdir:
            update_archives.bundle_all(repo_urls, tmpdir, tmpdir, git=self.git_script, throttler=counter)
        print("counts: {}".format(counter.counts))
        self.assertEqual(counter.counts['github.com'], 2)
        self.assertEqual(counter.counts['bitbucket.org'], 1)
        self.assertEqual(counter.counts['localhost'], 1)

class TestBundleForReal(unittest.TestCase):

    def test_bundle_one(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bundles_dir = os.path.join(tmpdir, 'repositories')
            os.mkdir(bundles_dir)
            bundle_path = update_archives.bundle(Repository("https://github.com/octocat/Hello-World.git"), bundles_dir, tmpdir)
            filesize = os.path.getsize(bundle_path)
            print("made bundle: {} ({} bytes)".format(bundle_path, filesize))
            self.assertIsNotNone(bundle_path, "bundle_path is None")
            self.assertGreater(filesize, 0, "bundle file size too small")

    def assertIsFile(self, pathname, min_size=0):
        assert isinstance(pathname, str)
        self.assertTrue(os.path.isfile(pathname), "expect file to exist at " + pathname)
        sz = os.path.getsize(pathname)
        self.assertGreaterEqual(sz, min_size)

    def test_bundle_all(self):
        """Tests bundling multiple real repositories. This uses an array of URLs that 
           represent smallish repositories that are unlikely to go away."""
        print("test_bundle_all")
        repo_urls = [
            "https://github.com/octocat/Hello-World.git",
            "https://github.com/octocat/git-consortium",
            "https://bitbucket.org/atlassian_tutorial/helloworld.git",
            "https://github.com/Microsoft/api-guidelines",
        ]
        throttler = update_archives.Throttler(2.0)
        with tempfile.TemporaryDirectory() as tmpdir:
            bundles_dir = os.path.join(tmpdir, 'repositories')
            os.mkdir(bundles_dir)
            print("bundles dir: {}".format(bundles_dir))
            num_ok = update_archives.bundle_all(repo_urls, bundles_dir, tmpdir, throttler=throttler)
            self.assertEqual(num_ok, len(repo_urls))
            bundle_files = list_files_recursively(bundles_dir)
            print("bundle files: {}".format(bundle_files))
            self.assertEqual(len(bundle_files), len(repo_urls))
            self.assertIsFile((os.path.join(bundles_dir, 'github.com', 'octocat', 'Hello-World.git.bundle')), 1)
            self.assertIsFile((os.path.join(bundles_dir, 'github.com', 'octocat', 'git-consortium.bundle')), 1)
            self.assertIsFile((os.path.join(bundles_dir, 'github.com', 'Microsoft', 'api-guidelines.bundle')), 1)
            self.assertIsFile((os.path.join(bundles_dir, 'bitbucket.org', 'atlassian_tutorial', 'helloworld.git.bundle')), 1)
    
    def test_bundle_fail(self):
        """Tests bundling a repository that does not exist, causing a failure"""
        print("test_bundle_fail")
        repo_urls = [
            "https://github.com/mike10004/this-repo-does-not-exist.git"
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            bundles_dir = os.path.join(tmpdir, "repositories")
            os.mkdir(bundles_dir)
            num_ok = update_archives.bundle_all(repo_urls, bundles_dir, tmpdir)
        self.assertEqual(0, num_ok, "num_ok")

class TestGitVersionTest(unittest.TestCase):

    def test_read(self):
        version = update_archives.read_git_version()
        self.assertTrue(isinstance(version, tuple))
        self.assertTrue(len(version) >= 2)
        self.assertTrue(isinstance(version[0], int))
        self.assertTrue(isinstance(version[1], int))
        self.assertGreaterEqual(version[0], 0)
        self.assertGreaterEqual(version[1], 0)

class TestCheckGitVersion(unittest.TestCase):
    def test_check_bad(self):
        for version in [(1, 7, 0), (0, 0, 0), (1, 7), (0, 0), (2, 1), (2, 1, 29)]:
            with self.assertRaises(update_archives.GitVersionException):
                update_archives.check_git_version(version)
    
    def test_check_good(self):
        for version in [(2, 3, 0), (2, 3), (2, 3, 9), (2, 11, 0), (2, 11), (3, 0), (3, 0, 0)]:
            update_archives.check_git_version(version)

if __name__ == '__main__':
    from argparse import ArgumentParser
    import logging
    parser = ArgumentParser()
    parser.add_argument("-l", "--log-level", choices=('DEBUG', 'INFO', 'WARN', 'ERROR'))
    args = parser.parse_args()
    if args.log_level:
        stderr_handler = logging.StreamHandler()
        for logger_name in (update_archives.__name__,):
            logger = logging.getLogger(logger_name)
            logger.addHandler(stderr_handler)
            logger.setLevel(logging.__dict__[args.log_level])
    unittest.main(argv=sys.argv[0:1])
