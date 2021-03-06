import os
import os.path
import sys
import unittest
import tempfile
import bundle_repos
import hashlib
import shutil

if sys.version_info[0] != 3:
    sys.stderr.write("requires Python 3\n")
    sys.exit(1)

def list_files_recursively(dirpath):
    all_files = []
    for root, dirs, files in os.walk(dirpath): # pylint: disable=unused-variable
        all_files += [os.path.join(root, f) for f in files]
    return all_files

def get_data_dir(relative_path=None):
    """Gets the pathname of the test data directory or an absolute path beneath the test data directory."""
    parent = os.path.dirname(os.path.dirname(__file__))
    test_data_dir = os.path.join(parent, 'testdata')
    assert os.path.isdir(test_data_dir)
    if relative_path is None:
        return test_data_dir
    filepath = os.path.join(test_data_dir, relative_path)
    assert os.path.exists(filepath), "not found: {}".format(filepath)
    return filepath

def hash_file(pathname):
    """Returns a byte string that is the SHA-256 hash of the file at the given pathname."""
    h = hashlib.sha256()
    with open(pathname, 'rb') as ifile:
        h.update(ifile.read())
    return h.digest()

def TemporaryDirectory():
    return tempfile.TemporaryDirectory(prefix='bundle-repos-tests-')

class TestGetDataDir(unittest.TestCase):

    def test_get_data_dir(self):
        pathname = get_data_dir()
        print("test data dir: {}".format(pathname))
        self.assertIsNotNone(pathname)
        self.assertTrue(os.path.isdir(pathname))

    def test_get_data_dir_file(self):
        pathname = get_data_dir('sample-repo.bundle')
        print("test data file: {}".format(pathname))
        self.assertIsNotNone(pathname)
        self.assertTrue(os.path.isfile(pathname))

class EnhancedTestCase(unittest.TestCase):

    def assertIsFile(self, pathname, min_size=0):
        assert isinstance(pathname, str)
        self.assertTrue(os.path.isfile(pathname), "expect file to exist at " + pathname)
        sz = os.path.getsize(pathname)
        self.assertGreaterEqual(sz, min_size, "file size is too small")

    def assertBundleVerifies(self, bundle_path):
        self.assertIsFile(bundle_path, 1)
        bundle_copy_path = os.path.join(tempfile.gettempdir(), 'git_bundle_for_verification.bundle')
        shutil.copyfile(bundle_path, bundle_copy_path)
        print("bundle copied to", bundle_copy_path)
        with TemporaryDirectory() as tmpdir:
            git_runner = bundle_repos.GitRunner('git')
            proc = git_runner.run(['git', 'init'], cwd=tmpdir) # must run `git bundle verify` inside a repo directory
            self.assertEqual(proc.returncode, 0, "git init return code nonzero")    
            proc = git_runner.run(['git', 'bundle', 'verify', bundle_path], cwd=tmpdir)
            if proc.returncode != 0:
                print("bundle verification failed on {}".format(bundle_path), file=sys.stderr)
                stdout_decoded = proc.stdout.decode('utf-8')
                stderr_decoded = proc.stderr.decode('utf-8')
                print("stdout:")
                print(stdout_decoded)
                print("stderr:")
                print(stderr_decoded)
                sys.stdout.flush()
            self.assertEqual(proc.returncode, 0, "git bundle return code nonzero")