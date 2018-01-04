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
import bundle_repos
from bundle_repos import Repository
import collections
import tests
import re
import pathlib

class TestRepository(unittest.TestCase):

    def test_good(self):
        url = 'https://github.com/mike10004/test-child-repo-1.git'
        r = Repository(url)
        self.assertEqual(r.url, url)
        self.assertEqual(r.get_repository_argument(), url)
        self.assertEqual(r.scheme, 'https')
        self.assertEqual(r.host, 'github.com')
        self.assertEqual(r.path_prefix, 'mike10004')
        self.assertEqual(r.repo_name, 'test-child-repo-1.git')
    
    def test_good_escapes(self):
        url = 'https://unscrupulous.com/Username%20With%20Spaces/good%40example.com.git'
        r = Repository(url)
        self.assertEqual(r.url, url)
        self.assertEqual(r.get_repository_argument(), url)
        self.assertEqual(r.scheme, 'https')
        self.assertEqual(r.host, 'unscrupulous.com')
        self.assertEqual(r.decoded_path_prefix(), 'Username With Spaces')
        self.assertEqual(r.decoded_repo_name(), 'good@example.com.git')

    def test_good_without_dot_git_suffix(self):
        url = 'https://somewhere.else/users/mike10004/test-child-repo-1'
        r = Repository(url)
        self.assertEqual(r.url, url)
        self.assertEqual(r.get_repository_argument(), url)
        self.assertEqual(r.scheme, 'https')
        self.assertEqual(r.host, 'somewhere.else')
        self.assertEqual(r.path_prefix, 'users/mike10004')
        self.assertEqual(r.repo_name, 'test-child-repo-1')
    
    def test_bad_bundle_file(self):
        filepath = '/home/josephine/Developer/bundles/my-project.bundle'
        with self.assertRaises(AssertionError):
            Repository(filepath) # because you must make the path a URI 

    def test_good_bundle_file(self):
        filepath = '/home/josephine/Developer/bundles/my-project.bundle'
        url = pathlib.PurePath(filepath).as_uri()
        r = Repository(url)
        self.assertEqual(r.url, url)
        self.assertEqual(r.get_repository_argument(), filepath)
        self.assertEqual(r.scheme, 'file')
        self.assertEqual(r.host, '_filesystem')
        self.assertEqual(r.path_prefix, os.path.dirname(filepath).lstrip('/'))
        self.assertEqual(r.repo_name, 'my-project.bundle')

    def test_good_bundle_file_escapes(self):
        filepath = '/home/josephine/My Projects/my-project.bundle'
        url = pathlib.PurePath(filepath).as_uri()
        r = Repository(url)
        self.assertEqual(r.url, url)
        self.assertEqual(r.get_repository_argument(), filepath)
        self.assertEqual(r.scheme, 'file')
        self.assertEqual(r.host, '_filesystem')
        self.assertEqual(r.decoded_path_prefix(), os.path.dirname(filepath).lstrip('/'), "path_prefix")
        self.assertEqual(r.decoded_repo_name(), 'my-project.bundle')

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

    def test_bad_url_has_separator_chars(self):
        with self.assertRaises(ValueError):
            Repository('https://unconscionable.com/User%2Fname/project.git')
        with self.assertRaises(ValueError):
            Repository('https://unconscionable.com/Username/My%2FProject.git')

    def test_decoded_path_prefix(self):
        url = 'https://somewhere.else/hello%40world/test-child-repo-1.git'
        r = Repository(url)
        self.assertEqual(r.decoded_path_prefix(), "hello@world")
    
    def test_make_bundle_path(self):
        url = 'https://somewhere.else/mpsycho/hello.git'
        r = Repository(url)
        treetop = '/home/maria/repos'
        self.assertEqual(r.make_bundle_path(treetop), os.path.join(treetop, 'somewhere.else/mpsycho/hello.git.bundle'))

    def test_make_bundle_path_file_uri(self):
        filepath = '/path/to/bundles/hello.git.bundle'
        url = pathlib.Path(filepath).as_uri()
        r = Repository(url)
        treetop = '/home/maria/repos'
        expected = os.path.join(treetop, bundle_repos.FILESYSTEM_DIR_BASENAME, filepath.lstrip('/') + '.bundle')
        actual = r.make_bundle_path(treetop)
        self.assertEqual(actual, expected, "expected {} but actual is {}".format(expected, actual))


GIT_REPLACER_SCRIPT_CONTENT = """#!/bin/bash
    set -e
    CMD=$1
    if [ "$CMD" == "clone" ] ; then
      echo $0 $@
      CLONE_DEST="${@: -1:1}"             # destination dir is last argument
      mkdir -vp "$CLONE_DEST"
    elif [ "$CMD" == "bundle" ] ; then
      echo $0 $@
      BUNDLE_PATH="${@: -2:1}"            # bundle pathname is penultimate argument
      touch "$BUNDLE_PATH"
    elif [ "$CMD" == "for-each-ref" ] ; then
      echo -n "$PWD" | sha1sum | cut -f1 -d' '
    else
      echo $0 $@
      echo "$CMD is not a git command" >&2
      exit 1
    fi
"""

def create_script_file(content):
    fd, scriptpath = tempfile.mkstemp(".sh", "test_bundle_repos_script")
    os.write(fd, content.encode('utf-8'))
    os.close(fd)
    os.chmod(scriptpath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return scriptpath    

class FakeGitUsingTestCase(unittest.TestCase):

    def setUp(self):
        self.git_script = create_script_file(GIT_REPLACER_SCRIPT_CONTENT)
        self.git_runner = bundle_repos.GitRunner(self.git_script)
    
    def tearDown(self):
        try:
            os.remove(self.git_script)
        except FileNotFoundError as ex:
            print(ex, file=sys.stderr)

class FakeGitUsingTestCaseTest(FakeGitUsingTestCase):

    def test_git_script_clone(self):
        with tests.TemporaryDirectory() as tempdir:
            clone_dest = os.path.join(tempdir, 'clone-destination')
            proc = self.git_runner.run(['git', 'clone', 'REMOTE_URL', clone_dest])
            print(proc.stdout.decode('utf-8'))
            print(proc.stderr.decode('utf-8'), file=sys.stderr)
            self.assertEqual(proc.returncode, 0)
    
    def test_git_script_bundle(self):
        with tests.TemporaryDirectory() as tempdir:
            bundle_path = os.path.join(tempdir, 'my.bundle')
            proc = self.git_runner.run(['git', 'bundle', 'create', bundle_path, "--all"])
            print(proc.stdout.decode('utf-8'))
            print(proc.stderr.decode('utf-8'), file=sys.stderr)
            self.assertEqual(proc.returncode, 0)
            self.assertTrue(os.path.isfile(bundle_path), "bundle not created: " + bundle_path)

    def test_git_script_print_latest_commit(self):
        with tests.TemporaryDirectory() as tempdir:
            clone_dir = os.path.join(tempdir, 'cloned-dir')
            os.makedirs(clone_dir)
            proc = self.git_runner.run(bundle_repos._GIT_CMD_PRINT_LATEST_COMMIT, cwd=clone_dir)
            self.assertEqual(proc.returncode, 0)
            self.assertRegex(proc.stdout.decode('utf-8'), r'^[a-f0-9]{40}')

    def test_git_script_fail(self):
        proc = self.git_runner.run(['git', 'fail', 'yolo'])
        print(proc.stdout.decode('utf-8'))
        print(proc.stderr.decode('utf-8'), file=sys.stderr)
        self.assertEqual(proc.returncode, 1)

class CountingThrottler(bundle_repos.Throttler):

    def __init__(self, category=''):
        super(CountingThrottler, self).__init__(0.0)
        self.counts = collections.defaultdict(int)
        self.tag = 'COUNTER'
    
    def throttle(self, category):
        self.counts[category] = self.counts[category] + 1
        super(CountingThrottler, self).throttle(category)

class TestBundle(FakeGitUsingTestCase):

    def make_bundler(self, tempdir, config=None):
        return bundle_repos.Bundler(tempdir, tempdir, self.git_script, config)

    def test_bundle(self):
        repo = Repository("https://localhost/hsolo/falcon.git")
        with tests.TemporaryDirectory() as treetop:
            bundle_name = self.make_bundler(treetop, treetop).bundle(repo)
            print("created {}".format(bundle_name))
            expected = os.path.join(treetop, 'localhost', 'hsolo', 'falcon.git.bundle')
            self.assertEqual(bundle_name, expected)
            if not os.path.isfile(bundle_name):
                print("contents of directory {}".format(treetop), file=sys.stderr)
                for f in tests.list_files_recursively(treetop):
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
        config = bundle_repos.BundleConfig()
        config.throttler = counter
        with tests.TemporaryDirectory() as tmpdir:
            self.make_bundler(tmpdir, config).bundle_all(repo_urls)
        print("counts: {}".format(counter.counts))
        self.assertEqual(counter.counts['github.com'], 2)
        self.assertEqual(counter.counts['bitbucket.org'], 1)
        self.assertEqual(counter.counts['localhost'], 1)

class TestGitVersionTest(unittest.TestCase):

    def test_read(self):
        version = bundle_repos.read_git_version()
        self.assertTrue(isinstance(version, tuple))
        self.assertTrue(len(version) >= 2)
        self.assertTrue(isinstance(version[0], int))
        self.assertTrue(isinstance(version[1], int))
        self.assertGreaterEqual(version[0], 0)
        self.assertGreaterEqual(version[1], 0)

class TestCheckGitVersion(unittest.TestCase):
    def test_check_bad(self):
        for version in [(1, 7, 0), (0, 0, 0), (1, 7), (0, 0), (2, 1), (2, 1, 29)]:
            with self.assertRaises(bundle_repos.GitVersionException):
                bundle_repos.check_git_version(version)
    
    def test_check_good(self):
        for version in [(2, 3, 0), (2, 3), (2, 3, 9), (2, 11, 0), (2, 11), (3, 0), (3, 0, 0)]:
            bundle_repos.check_git_version(version)

class TestGitRunner(unittest.TestCase):

    def test_cwd(self):
        with tests.TemporaryDirectory() as tempdir:
            runner = bundle_repos.GitRunner('pwd')
            proc = runner.run(['pwd'], cwd=tempdir)
            self.assertEqual(proc.returncode, 0)
            actual = proc.stdout.decode('utf8').strip()
            self.assertEqual(actual, tempdir)

class TestReadGitLatestCommit(unittest.TestCase):

    def test_read_git_latest_commit(self):
        bundle_path = tests.get_data_dir('sample-repo.bundle')
        with tests.TemporaryDirectory() as tempdir:
            git = bundle_repos.GitRunner('git')
            clone_dir = os.path.join(tempdir, 'cloned-bundle-directory')
            proc = git.run(['git', 'clone', bundle_path, clone_dir])
            if proc.returncode != 0: 
                print(proc.stderr, file=sys.stderr)
            self.assertEqual(proc.returncode, 0)
            commit_hash = bundle_repos.read_git_latest_commit(clone_dir)
            KNOWN_COMMIT_HASH = '930e77627aa807266746f2795b59b890cba70499'
            self.assertEqual(commit_hash, KNOWN_COMMIT_HASH)

class TestBundleFromBundleSource(tests.EnhancedTestCase):

    def test_bundle_from_bundle_source(self):
        source_bundle_path = tests.get_data_dir('sample-repo.bundle')
        assert os.path.isfile(source_bundle_path)
        repo = Repository(pathlib.Path(source_bundle_path).as_uri())
        with tests.TemporaryDirectory() as tmpdir:
            bundler = bundle_repos.Bundler(tmpdir, tmpdir)
            bundle_path = bundler.bundle(repo)
            # not sure of an independent way to check that this bundle is correct
            self.assertIsNotNone(bundle_path, "bundle path is None")
            self.assertBundleVerifies(bundle_path)

@unittest.skip
class TestBundleRevisionCheck(unittest.TestCase):

    def test_bundle_required(self):
        raise NotImplementedError()
    
    def test_bundle_not_required(self):
        raise NotImplementedError()
