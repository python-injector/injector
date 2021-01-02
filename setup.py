from setuptools import setup
import warnings


warnings.filterwarnings("always", module=__name__)


requirements_dev = []
with open('requirements_dev.txt') as fd_in:
    for line in fd_in:
        if '#' not in line:
            requirements_dev.append(line.strip())


def read_injector_variable(name):
    prefix = '%s = ' % (name,)
    with open('injector/__init__.py') as f:
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
    warnings.warn('Could not locate pandoc, using Markdown long_description.', ImportWarning)
    with open('README.md') as f:
        long_description = f.read()


description = long_description.splitlines()[0].strip()


setup(
    name='injector',
    url='https://github.com/alecthomas/injector',
    download_url='https://pypi.org/project/injector/',
    version=version,
    options=dict(egg_info=dict(tag_build=version_tag)),
    description=description,
    long_description=long_description,
    license='BSD',
    platforms=['any'],
    packages=['injector'],
    package_data={'injector': ['py.typed']},
    author='Alec Thomas',
    author_email='alec@swapoff.org',
    extras_require={'dev': requirements_dev},
    keywords=[
        'Dependency Injection',
        'DI',
        'Dependency Injection framework',
        'Inversion of Control',
        'IoC',
        'Inversion of Control container',
    ],
    install_requires=['typing_extensions>=3.7.4;python_version<"3.9"'],
)
