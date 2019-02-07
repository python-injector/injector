import os.path

test_sources = ['injector', 'injector_test.py', 'README.md']


def pytest_ignore_collect(path, config):
    return not os.path.basename(str(path)) in test_sources
