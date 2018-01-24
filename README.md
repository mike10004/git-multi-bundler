[![Travis build status](https://img.shields.io/travis/mike10004/git-multi-bundler.svg)](https://travis-ci.org/mike10004/git-multi-bundler)

# README

If you have multiple git repositories that you would like to bundle, for 
archiving or cataloguing, this program may be for you. Requires Python 3.

## Usage

    ./bundle_repos_exec.py INDEXFILE

...where `INDEXFILE` is a text file containing one repository URL per line, like

    https://github.com/octocat/Hello-World.git
    https://bitbucket.org/atlassian_tutorial/helloworld.git
    https://github.com/Microsoft/api-guidelines.git

Run the program with `--help` to see execution options. In normal operation, 
each repository is cloned with all branches and a corresponding bundle is 
created beneath the bundles directory (`./repositories` by default). The 
bundles are organized by host and path. 

For each repository URL, if a local bundle already exists, the latest commit 
in the fresh clone is compared to the latest commit in the local bundle, and 
the bundle is updated only if they differ. This comparison can be skipped with 
the `--ignore-rev` option. Note that a non-identical bundle may be created even
if the latest commit is the same if the local system's git configuration is 
different. (This is not intuitive, and I suspect the cause is the record of 
the username of the cloning user in the cloned repository's logs.)

There's currently a prohibition against URLs without HTTPS scheme, meaning no 
git@github.com (scheme-less) or HTTP (insecure) URLs. The URL is passed as
an argument to `git clone`, so in theory a `git@github.com:username/repo.git`
URL could work, but an explicit guard clause currently prohibits it. URLs with 
scheme HTTP are disallowed for security reasons, but also could work in 
theory. (For testing purposes, `file` URLs pointing to bundle file locations
on the local filesystem are also allowed, but I can't imagine a use case for 
outside of testing.)

The program ignores repositories where cloning fails, unless it fails for all 
of them, in which case it exits with a nonzero exit code. A common cause of
failure is a URL that specifies a repository that doesn't exist. Evidence of 
this error is a log message about a failure with exit code 128 and a message 
that a username could not be read. (I think this is because git assumes that
if gets a 404 response for an HTTP URL, the reason is that you lack 
authorization, not that the resource doesn't actually exist, so it asks for
credentials, but we disable the terminal prompt, so it can't get the 
credentials and aborts.)

Windows is not supported as an execution platform, but POSIX-like platforms
should all be supported, though testing is only performed on Linux.

## Unit Tests

From the cloned repository directory, execute:

    $ ./run_tests.py

Note that this will run all unit tests, including those that connect to 
external git repositories like GitHub. To run only the unit tests that 
stay local, add the `--no-external` flag. See `./run_tests.py --help`
for other options.
