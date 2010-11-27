Injector - Python dependency injection framework, inspired by Guice
======================================================================
Dependency injection as a formal pattern is less useful in Python than in other
languages, primarily due to its support for keyword arguments, the ease with
which objects can be mocked, and its dynamic nature.

That said, a framework for assisting in this process can remove a lot of
boiler-plate from larger applications. That's where Injector can help. As an
added benefit, Injector encourages nicely compartmentalised code through the
use of :class:`Module` s.

``foo``

While being inspired by Guice, it does not slavishly replicate its API.
Providing a Pythonic API trumps faithfulness.

Concepts
--------
For those new to dependency-injection and/or Guice, some of the terminology may
not be obvious. For clarification:

Injector:
    pass

:class:`Binding`:

:class:`Provider`:
    A means of providing an instance of a type. Built-in providers include
    :class:`ClassProvider` (creates a new instance from a class),
    :class:`InstanceProvider` (returns an instance directly)

At its heart, the :class:`Injector` is simply a dictionary, mapping types to
providers of instances of those types. This could be as simple as::

    {str: str}


Footnote
--------
This framework is similar to snake-guice, but aims for simplification.

:copyright: (c) 2010 by Alec Thomas
:license: BSD

