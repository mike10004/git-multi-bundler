#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys

if sys.version_info[0] != 3:
    sys.stderr.write("requires Python 3\n")
    sys.exit(1)

if __name__ == '__main__':
    import bundle_repos
    exit(bundle_repos.main())
