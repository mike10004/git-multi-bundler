"""bundle_repos unit tests that touch external resources (e.g. github.com)"""

#!/usr/bin/python3

# -*- coding: utf-8 -*-

# pylint: disable=missing-docstring,trailing-whitespace,line-too-long,invalid-name

import unittest
import os.path
import bundle_repos
from bundle_repos import Repository
import tempfile
import tests

_TMP_PREFIX = os.path.join(tempfile.gettempdir(), 'bundle-repos-')

class TestBundleForReal(tests.EnhancedTestCase):

    def test_bundle_one(self):
        print("\ntest_bundle_one")
        with tempfile.TemporaryDirectory(prefix=_TMP_PREFIX) as tmpdir:
            bundles_dir = os.path.join(tmpdir, 'repositories')
            os.mkdir(bundles_dir)
            bundle_path = bundle_repos.Bundler(bundles_dir, tmpdir).bundle(Repository("https://github.com/octocat/Hello-World.git"))
            self.assertIsNotNone(bundle_path, "bundle returned None")
            self.assertBundleVerifies(bundle_path)

    def test_bundle_all(self):
        """Tests bundling multiple real repositories. This uses an array of URLs that 
           represent smallish repositories that are unlikely to go away."""
        print("\ntest_bundle_all")
        repo_urls = [
            "https://github.com/octocat/Hello-World.git",
            "https://github.com/octocat/git-consortium",
            "https://bitbucket.org/atlassian_tutorial/helloworld.git",
            "https://github.com/Microsoft/api-guidelines",
        ]
        throttler = bundle_repos.Throttler(2.0)
        config = bundle_repos.BundleConfig()
        config.throttler = throttler
        with tempfile.TemporaryDirectory(prefix=_TMP_PREFIX) as tmpdir:
            bundles_dir = os.path.join(tmpdir, 'repositories')
            os.mkdir(bundles_dir)
            print("bundles dir: {}".format(bundles_dir))
            num_ok = bundle_repos.Bundler(bundles_dir, tmpdir, config=config).bundle_all(repo_urls)
            self.assertEqual(num_ok, len(repo_urls))
            bundle_files = tests.list_files_recursively(bundles_dir)
            print("bundle files: {}".format(bundle_files))
            self.assertEqual(len(bundle_files), len(repo_urls))
            self.assertBundleVerifies((os.path.join(bundles_dir, 'github.com', 'octocat', 'Hello-World.git.bundle')))
            self.assertBundleVerifies((os.path.join(bundles_dir, 'github.com', 'octocat', 'git-consortium.bundle')))
            self.assertBundleVerifies((os.path.join(bundles_dir, 'github.com', 'Microsoft', 'api-guidelines.bundle')))
            self.assertBundleVerifies((os.path.join(bundles_dir, 'bitbucket.org', 'atlassian_tutorial', 'helloworld.git.bundle')))
    
    def test_bundle_fail(self):
        """Tests bundling a repository that does not exist, causing a failure"""
        print("\ntest_bundle_fail")
        repo_urls = [
            "https://github.com/mike10004/this-repo-does-not-exist.git"
        ]
        with tempfile.TemporaryDirectory(prefix=_TMP_PREFIX) as tmpdir:
            bundles_dir = os.path.join(tmpdir, "repositories")
            os.mkdir(bundles_dir)
            num_ok = bundle_repos.Bundler(bundles_dir, tmpdir).bundle_all(repo_urls)
            self.assertEqual(0, num_ok, "num_ok")
            for url in repo_urls:
                potential_bundle_path = Repository(url).make_bundle_path(bundles_dir)
                self.assertFalse(os.path.exists(potential_bundle_path), "file exists at {} but shouldn't".format(potential_bundle_path))
        
