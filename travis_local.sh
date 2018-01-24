#!/bin/bash
dpkg-query -s python3.6 >/dev/null
if [ $? -ne 0 ] ; then
  echo "make sure python 3.6 is installed" >&2
  exit 1
fi
if which pyenv ; then 
  pyenv shell 3.6
fi
set -e
PYTHON=python3
$PYTHON -c 'import sys; assert sys.version_info.major >= 3 and sys.version_info.minor >= 5, "version incompatible: " + sys.version'
export BUNDLE_REPOS_TESTS_SKIP_EXTERNAL=1
python3 -m unittest discover
