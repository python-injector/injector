.. Injector documentation master file, created by
   sphinx-quickstart on Mon Sep 16 02:58:17 2013.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to Injector's documentation!
====================================

.. image:: https://github.com/alecthomas/injector/workflows/CI/badge.svg
   :alt: Build status
   :target: https://github.com/alecthomas/injector/actions?query=workflow%3ACI+branch%3Amaster
   
.. image:: https://codecov.io/gh/alecthomas/injector/branch/master/graph/badge.svg
   :alt: Covergage status
   :target: https://codecov.io/gh/alecthomas/injector


GitHub (code repository, issues): https://github.com/alecthomas/injector

PyPI (installable, stable distributions): https://pypi.org/project/injector. You can install Injector using pip::

    pip install injector

Injector works with CPython 3.6+ and PyPy 3 implementing Python 3.6+.

Introduction
------------

While dependency injection is easy to do in Python due to its support for keyword arguments, the ease with which objects can be mocked and its dynamic natura, a framework for assisting in this process can remove a lot of boiler-plate from larger applications. That's where Injector can help. It automatically and transitively provides dependencies for you. As an added benefit, Injector encourages nicely compartmentalised code through the use of :ref:`modules <module>`.

If you're not sure what dependency injection is or you'd like to learn more about it see:

* `The Clean Code Talks - Don't Look For Things! (a talk by Miško Hevery)
  <https://www.youtube.com/watch?v=RlfLCWKxHJ0>`_
* `Inversion of Control Containers and the Dependency Injection pattern (an article by Martin Fowler)
  <https://martinfowler.com/articles/injection.html>`_

The core values of Injector are:

* Simplicity - while being inspired by Guice, Injector does not slavishly replicate its API.
  Providing a Pythonic API trumps faithfulness. Additionally some features are ommitted
  because supporting them would be cumbersome and introduce a little bit too much "magic"
  (member injection, method injection).

  Connected to this, Injector tries to be as nonintrusive as possible. For example while you may
  declare a class' constructor to expect some injectable parameters, the class' constructor
  remains a standard constructor – you may instaniate the class just the same manually, if you want.

* No global state – you can have as many :class:`Injector` instances as you like, each with
  a different configuration and each with different objects in different scopes. Code like this
  won't work for this very reason::

    # This will NOT work:

    class MyClass:
        @inject
        def __init__(self, t: SomeType):
            # ...

    MyClass()

  This is simply because there's no global :class:`Injector` to use. You need to be explicit and use
  :meth:`Injector.get <injector.Injector.get>`,
  :meth:`Injector.create_object <injector.Injector.create_object>` or inject `MyClass` into the place
  that needs it.

* Cooperation with static type checking infrastructure – the API provides as much static type safety
  as possible and only breaks it where there's no other option. For example the
  :meth:`Injector.get <injector.Injector.get>` method is typed such that `injector.get(SomeType)`
  is statically declared to return an instance of `SomeType`, therefore making it possible for tools
  such as `mypy <https://github.com/python/mypy>`_ to type-check correctly the code using it.

Quick start
-----------

See `the project's README <https://github.com/alecthomas/injector/blob/master/README.md>`_ for an
example of Injector use.

Contents
--------

.. toctree::
   :maxdepth: 1

   changelog
   terminology
   testing
   scopes
   logging
   api
   faq
   practices
