# README

If you have multiple git repositories that you would like to bundle, for 
archiving or cataloguing, this program may be for you.

## Usage

    ./update_archives.py INDEXFILE

...where `INDEXFILE` is a text file containing one repository URL per line, like

    https://github.com/octocat/Hello-World.git
    https://bitbucket.org/atlassian_tutorial/helloworld.git
    https://github.com/Microsoft/api-guidelines.git

There's currently a prohibition against URLs without HTTPS scheme, meaning no 
git@github.com (scheme-less) or HTTP (insecure) URLs. The URL is passed as
an argument to `git clone`, so in theory a `git@github.com:username/repo.git`
URL could work. URLs with scheme HTTP are disallowed for security reasons, but
also could work in theory.

The program ignores repositories where cloning fails, unless it fails for all 
of them, in which case it exits with a nonzero exit code. A common cause of
failure is a URL that specifies a repository that doesn't exist. Evidence of 
this error is a log message about a failure with exit code 128 and a message 
that a username could not be read. (I think this is because git assumes that
if gets a 404 response for an HTTP URL, the reason is that you lack 
authorization, not that the resource doesn't actually exist, so it asks for
credentials, but we disable the terminal prompt, so it can't get the 
credentials and aborts.)

## To do

* skip bundling from repositories where we already have a bundle with the latest commit
