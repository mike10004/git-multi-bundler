#!/usr/bin/env python3

import unittest
import bundle_repos
import sys
import tests
import tests.test_bundle_repos

if __name__ == '__main__':
    from argparse import ArgumentParser
    import logging
    parser = ArgumentParser()
    parser.add_argument("-l", "--log-level", choices=('DEBUG', 'INFO', 'WARN', 'ERROR'))
    parser.add_argument("-x", "--no-external", action="store_true", help="skip tests that touch external dependencies (e.g. github.com)")
    args = parser.parse_args()
    if args.log_level:
        stderr_handler = logging.StreamHandler()
        for logger_name in (bundle_repos.__name__,):
            logger = logging.getLogger(logger_name)
            logger.addHandler(stderr_handler)
            logger.setLevel(logging.__dict__[args.log_level])
    uargv = sys.argv[0:1]
    if args.no_external:
        uargv += [tests.test_bundle_repos.__name__]
    unittest.main(argv=uargv, module=None)
