import os.path

test_sources = ['injector.py', 'injector_test.py', 'injector_test_py3.py', 'README.md']


def pytest_ignore_collect(path, config):
    return not os.path.basename(str(path)) in test_sources
