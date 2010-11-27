try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

import sys
sys.path.insert(0, '.')
import injector

version = injector.__version__
version_tag = injector.__version_tag__
long_description = open('README.rst').read()
description = long_description.splitlines()[0].strip()


setup(
    name='injector',
    url='http://github.com/alecthomas/injector',
    download_url='http://pypi.python.org/pypi/injector',
    version=version,
    options=dict(egg_info=dict(tag_build=version_tag)),
    description=description,
    long_description=long_description,
    license='BSD',
    platforms=['any'],
    py_modules=['injector'],
    author='Alec Thomas',
    author_email='alec@swapoff.org',
    install_requires=[
        'setuptools >= 0.6b1',
    ],
    )
