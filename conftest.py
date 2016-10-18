import sys
import os.path

test_sources = ['injector_test.py']


if sys.version_info[0] >= 3:
    test_sources.extend(['injector.py', 'injector_test_py3.py', 'README.md'])


def pytest_ignore_collect(path, config):
    return not os.path.basename(str(path)) in test_sources
