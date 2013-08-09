import sys
import os.path

test_sources = ['injector.py', 'injector_test.py', 'README.md']


if sys.version_info[0] >= 3:
    test_sources.append('injector_test_py3.py')


def pytest_ignore_collect(path, config):
    return not os.path.basename(str(path)) in test_sources
