from setuptools import setup, Command
import sys


class PyTest(Command):
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        import subprocess
        errno = subprocess.call([sys.executable, 'runtest.py'])
        raise SystemExit(errno)


def read_injector_variable(name):
    prefix = '%s = ' % (name,)
    with open('injector.py') as f:
        for line in f:
            if line.startswith(prefix):
                return line.replace(prefix, '').strip().strip("'")
    raise AssertionError('variable %s not found' % (name,))


version = read_injector_variable('__version__')
version_tag = read_injector_variable('__version_tag__')

try:
    import pypandoc
    long_description = pypandoc.convert('README.md', 'rst')
except ImportError:
    print('WARNING: Could not locate pandoc, using Markdown long_description.')
    long_description = open('README.md').read()

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
        'typing',
    ],
    cmdclass={'test': PyTest},
    keywords=[
        'Dependency Injection', 'DI', 'Dependency Injection framework',
        'Inversion of Control', 'IoC', 'Inversion of Control container',
    ],
)
