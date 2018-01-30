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
import shutil

KNOWN_SAMPLE_REPO_LATEST_COMMIT_HASH = '930e77627aa807266746f2795b59b890cba70499'
KNOWN_SAMPLE_REPO_BRANCHED_LATEST_COMMIT_HASH = 'bace9af693b7e502f8c40ca1bf9e281f00498004'

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
        assert (config is None) or isinstance(config, bundle_repos.BundleConfig)
        return bundle_repos.Bundler(tempdir, tempdir, git=self.git_script, config=config)

    def test_bundle(self):
        repo = Repository("https://localhost/hsolo/falcon.git")
        with tests.TemporaryDirectory() as treetop:
            bundle_name = self.make_bundler(treetop).bundle(repo)
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


class TestBundleFail(tests.EnhancedTestCase):

    def test_bundle_fail(self):
        """Tests bundling a repository that does not exist, causing a failure"""
        print("\ntest_bundle_fail")
        repo_urls = [
            "file:///path/to/nowhere.bundle"
        ]
        with tests.TemporaryDirectory() as tmpdir:
            bundles_dir = os.path.join(tmpdir, "repositories")
            os.mkdir(bundles_dir)
            num_ok = bundle_repos.Bundler(bundles_dir, tmpdir).bundle_all(repo_urls)
            self.assertEqual(0, num_ok, "num_ok")
            for url in repo_urls:
                potential_bundle_path = Repository(url).make_bundle_path(bundles_dir)
                self.assertFalse(os.path.exists(potential_bundle_path), "file exists at {} but shouldn't".format(potential_bundle_path))

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
    
    def test_clone_mirrored_clean(self):
        bundle_path = tests.get_data_dir('sample-repo-branched.bundle')
        with tests.TemporaryDirectory() as clone_dir:
            runner = bundle_repos.GitRunner('git')
            runner.clone_mirrored_clean(bundle_path, clone_dir)
            branch_list_lines = runner.run_clean(['git', 'branch', '-l'], cwd=clone_dir).stdout.decode('utf-8').split("\n")
            branch_list_lines = list(filter(lambda x: x, branch_list_lines))
            branch_list = [b.strip().split()[-1] for b in branch_list_lines]
            self.assertSetEqual(set(branch_list), {'master', 'other-branch'})


class TestReadGitLatestCommit(unittest.TestCase):

    def setUp(self):
        self.branched_bundle_path = tests.get_data_dir('sample-repo-branched.bundle')
        self.unbranched_bundle_path = tests.get_data_dir('sample-repo.bundle')

    def test_read_git_latest_commit(self):
        self.do_test_read_git_latest_commit(self.unbranched_bundle_path, KNOWN_SAMPLE_REPO_LATEST_COMMIT_HASH)

    def test_read_git_latest_commit_branched(self):
        self.do_test_read_git_latest_commit(self.branched_bundle_path, KNOWN_SAMPLE_REPO_BRANCHED_LATEST_COMMIT_HASH)

    def test_read_git_latest_commit_from_bundle(self):
        self.do_test_read_git_latest_commit_from_bundle(self.unbranched_bundle_path, KNOWN_SAMPLE_REPO_LATEST_COMMIT_HASH)

    def test_read_git_latest_commit_branched_from_bundle(self):
        self.do_test_read_git_latest_commit_from_bundle(self.branched_bundle_path, KNOWN_SAMPLE_REPO_BRANCHED_LATEST_COMMIT_HASH)

    def do_test_read_git_latest_commit_from_bundle(self, bundle_path, expected_hash):
        with tests.TemporaryDirectory() as tempdir:
            commit_hash = bundle_repos.read_git_latest_commit_from_bundle(bundle_path, tempdir)
            self.assertEqual(commit_hash, expected_hash)

    def do_test_read_git_latest_commit(self, bundle_path, expected_hash):
        with tests.TemporaryDirectory() as tempdir:
            git = bundle_repos.GitRunner('git')
            clone_dir = os.path.join(tempdir, 'cloned-bundle-directory')
            git.clone_mirrored_clean(bundle_path, clone_dir)
            commit_hash = bundle_repos.read_git_latest_commit(clone_dir)
            self.assertEqual(commit_hash, expected_hash)

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

class TestBundleConfig(tests.EnhancedTestCase):

    def test_kwargs(self):
        c = bundle_repos.BundleConfig(ignore_rev=True)
        self.assertTrue(c.ignore_rev)
    
    def test_kwargs_bad_arg(self):
        with self.assertRaises(AttributeError):
            bundle_repos.BundleConfig(foo='bar')


class TestBundleRevisionCheck(tests.EnhancedTestCase):

    def test_bundle_required(self):
        source_bundle_path = tests.get_data_dir('sample-repo-branched.bundle')
        source_bundle_uri = pathlib.PurePath(source_bundle_path).as_uri()
        original_bundle_path = tests.get_data_dir('sample-repo.bundle')
        original_hash = tests.hash_file(original_bundle_path)
        with tests.TemporaryDirectory() as tmpdir:
            repo = Repository(source_bundle_uri)
            dest_bundle_path = repo.make_bundle_path(tmpdir)
            os.makedirs(os.path.dirname(dest_bundle_path))
            shutil.copyfile(original_bundle_path, dest_bundle_path)
            old_metadata = os.stat(dest_bundle_path)
            bundler = bundle_repos.Bundler(tmpdir, tmpdir)
            old_latest_commit = bundle_repos.read_git_latest_commit_from_bundle(dest_bundle_path, tmpdir, bundler.git_runner)
            assert old_latest_commit == KNOWN_SAMPLE_REPO_LATEST_COMMIT_HASH
            new_bundle_path = bundler.bundle(repo)
            self.assertEqual(new_bundle_path, dest_bundle_path)
            new_latest_commit = bundle_repos.read_git_latest_commit_from_bundle(new_bundle_path, tmpdir, bundler.git_runner)
            self.assertEqual(new_latest_commit, KNOWN_SAMPLE_REPO_BRANCHED_LATEST_COMMIT_HASH, "latest commit hash from sample-repo-branched is incorrect")
            new_hash = tests.hash_file(new_bundle_path)
            new_metadata = os.stat(new_bundle_path)
            self.assertNotEqual(new_metadata, old_metadata, "metadata should have changed")
            self.assertNotEqual(new_hash, original_hash, "hash should have changed")
    
    def test_bundle_not_required_skip(self):
        source_bundle_path = tests.get_data_dir('sample-repo.bundle')
        source_bundle_uri = pathlib.PurePath(source_bundle_path).as_uri()
        original_bundle_path = tests.get_data_dir('sample-repo.bundle')
        original_hash = tests.hash_file(original_bundle_path)
        with tests.TemporaryDirectory() as tmpdir:
            repo = Repository(source_bundle_uri)
            dest_bundle_path = repo.make_bundle_path(tmpdir)
            os.makedirs(os.path.dirname(dest_bundle_path))
            shutil.copyfile(original_bundle_path, dest_bundle_path)
            original_metadata = os.stat(dest_bundle_path)
            new_bundle_path = bundle_repos.Bundler(tmpdir, tmpdir).bundle(repo)
            self.assertEqual(new_bundle_path, dest_bundle_path)
            new_hash = tests.hash_file(new_bundle_path)
            self.assertEqual(new_hash, original_hash, "hash should NOT have changed")
            new_metadata = os.stat(new_bundle_path)
            self.assertEqual(new_metadata, original_metadata, "file metadata should NOT have changed")

    def test_bundle_not_required_force(self):
        source_bundle_path = tests.get_data_dir('sample-repo.bundle')
        source_bundle_uri = pathlib.PurePath(source_bundle_path).as_uri()
        original_bundle_path = tests.get_data_dir('sample-repo.bundle')
        with tests.TemporaryDirectory() as tmpdir:
            repo = Repository(source_bundle_uri)
            dest_bundle_path = repo.make_bundle_path(tmpdir)
            os.makedirs(os.path.dirname(dest_bundle_path))
            shutil.copyfile(original_bundle_path, dest_bundle_path)
            original_metadata = os.stat(dest_bundle_path)
            config = bundle_repos.BundleConfig(ignore_rev=True)
            new_bundle_path = bundle_repos.Bundler(tmpdir, tmpdir, config=config).bundle(repo)
            self.assertEqual(new_bundle_path, dest_bundle_path)
            new_metadata = os.stat(new_bundle_path)
            self.assertNotEqual(new_metadata, original_metadata, "file metadata should have changed")


class TestCli(unittest.TestCase):

    def test_clean_index_urls(self):
        test_cases = [
            {
                'input': ["https://hello.com/world", "https://foo.bar/baz"],
                'output': ["https://hello.com/world", "https://foo.bar/baz"]
            },
            {
                'input': ["https://hello.com/world", "", "https://foo.bar/baz", "    "],
                'output': ["https://hello.com/world", "https://foo.bar/baz"]
            },
            {
                'input': ["https://hello.com/world", "#https://foo.bar/baz", "#", "https://what.ever/hella", "#   "],
                'output': ["https://hello.com/world", "https://what.ever/hella"]
            },
        ]
        for test_case in test_cases:
            output = bundle_repos.clean_index_urls(test_case['input'])
            self.assertListEqual(output, test_case['output'], 'cleaned output URL list is not what is expected')
    
    def test_main(self):
        source_bundle_path = tests.get_data_dir('sample-repo-branched.bundle')
        source_bundle_uri = pathlib.PurePath(source_bundle_path).as_uri()
        with tempfile.TemporaryDirectory() as tempdir:
            indexfile = os.path.join(tempdir, 'remote_urls.txt')
            bundles_dir = os.path.join(tempdir, "bundles_destination")
            os.makedirs(bundles_dir)
            with open(indexfile, 'w') as ofile:
                print(source_bundle_uri, file=ofile)
            args = ['--log-level', 'DEBUG', '--bundles-dir', bundles_dir, indexfile]
            returncode = bundle_repos.main(args)
        self.assertEquals(returncode, 0, "return code from main()")
