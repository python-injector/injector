Injector - Python dependency injection framework, inspired by Guice
######################################################################

Introduction
============

Dependency injection as a formal pattern is less useful in Python than in other
languages, primarily due to its support for keyword arguments, the ease with
which objects can be mocked, and its dynamic nature.

That said, a framework for assisting in this process can remove a lot of
boiler-plate from larger applications. That's where Injector can help. It
automatically and transitively provides keyword arguments with their values. As
an added benefit, Injector encourages nicely compartmentalised code through the
use of :class:`Module` s.

While being inspired by Guice, it does not slavishly replicate its API.
Providing a Pythonic API trumps faithfulness.

Terminology
===========
At its heart, Injector is simply a dictionary for mapping types to things that
create instances of those types. This could be as simple as::

    {str: 'an instance of a string'}

For those new to dependency-injection and/or Guice, though, some of the
terminology used may not be obvious.

Provider
--------
A means of providing an instance of a type. Built-in providers include
:class:`ClassProvider` (creates a new instance from a class),
:class:`InstanceProvider` (returns an existing instance directly) and
:class:`CallableProvider` (provides an instance by calling a function).

Scope
-----
By default, providers are executed each time an instance is required. Scopes
allow this behaviour to be customised. For example, :class:`SingletonScope`
(typically used through the class decorator :data:`singleton`), can be used to
always provide the same instance of a class.

Other examples of where scopes might be a threading scope, where instances are
provided per-thread, or a request scope, where instances are provided
per-HTTP-request.

The default scope is :class:`NoScope`.

Binding Key
-----------
A binding key uniquely identifies a provider of a type. It is effectively a
tuple of ``(type, annotation)`` where ``type`` is the type to be provided and
``annotation`` is additional, optional, uniquely identifying information for
the type.

For example, the following are all unique binding keys for ``str``::

    (str, 'name')
    (str, 'description')

For a generic type such as ``str``, annotations are very useful for unique
identification.

As an *alternative* convenience to using annotations, :func:`Key` may be used
to create unique types as necessary::

    >>> Name = Key('name')
    >>> Description = Key('description')

Which may then be used as binding keys, without annotations, as they already
uniquely identify a particular provider::

    (Name, None)
    (Description, None)

Though of course, annotations may still be used with these types, like any
other type.

Annotation
----------
An annotation is additional unique information about a type to avoid binding
key collisions. It creates a new unique binding key for an existing type.

Binding
-------
A binding is the mapping of a unique binding key to a corresponding provider.
For example::

    >>> bindings = {
    ...   (Name, None): InstanceProvider('Sherlock'),
    ...   (Description, None): InstanceProvider('A man of astounding insight')}
    ... }

Binder
------
The :class:`Binder` is simply a convenient wrapper around the dictionary
that maps types to providers. It provides methods that make declaring bindings
easier.

Module
------
A :class:`Module` configures bindings. It provides methods that simplify the
process of binding a key to a provider. For example the above bindings would be
created with::

    >>> class MyModule(Module):
    ...     def configure(self, binder):
    ...         binder.bind(Name, to='Sherlock')
    ...         binder.bind(Description, to='A man of astounding insight')

For more complex instance construction, methods decorated with
``@provides`` will be called to resolve binding keys::

    >>> class MyModule(Module):
    ...     def configure(self, binder):
    ...         binder.bind(Name, to='Sherlock')
    ...
    ...     @provides(Description)
    ...     def describe(self):
    ...         return 'A man of astounding insight (at %s)' % time.time()

Injection
---------
Injection is the process of providing an instance of a type, to a method that
uses that instance. It is achieved with the :func:`inject` decorator. Keyword
arguments to inject define which arguments in its decorated method should be
injected, and with what.

Here is an example of injection on a module provider method, and on the
constructor of a normal class::

    >>> class User(object):
    ...     @inject(name=Name, description=Description)
    ...     def __init__(self, name, description):
    ...         self.name = name
    ...         self.description = description

    >>> class UserModule(Module):
    ...     def configure(self, binder):
    ...        binder.bind(User)

    >>> class UserAttributeModule(Module):
    ...     def configure(self, binder):
    ...         binder.bind(Name, to='Sherlock')
    ...
    ...     @provides(Description)
    ...     @inject(name=Name)
    ...     def describe(self, name):
    ...         return '%s is a man of astounding insight' % name

Injector
--------
The :class:`Injector` brings everything together. It takes a list of
:class:`Module` s, and configures them with a binder, effectively creating a
dependency graph::

    >>> injector = Injector([UserModule(), UserAttributeModule()])

The injector can then be used to acquire instances of a type, either directly::

    >>> injector.get(Name)
    'Sherlock'
    >>> injector.get(Description)
    'Sherlock is a man of astounding insight'

Or transitively::

    >>> user = injector.get(User)
    >>> isinstance(user, User)
    True
    >>> user.name
    'Sherlock'
    >>> user.description
    'Sherlock is a man of astounding insight'

Implementing new Scopes
=======================
In the above description of scopes, we glossed over a lot of detail. In
particular, how one would go about implementing our own scopes.

Basically, there are two steps. First, subclass :class:`Scope` and implement
:meth:`Scope.get`::

    >>> class CustomScope(Scope):
    ...   def get(self, key, provider):
    ...     return provider

Then create a global instance of :class:`ScopeDecorator` to allow classes to be
easily annotated with your scope::

    >>> customscope = ScopeDecorator(CustomScope)

This can be used like so:

    >>> @customscope
    ... class MyClass(object):
    ...   pass

Scopes are bound in modules with the :meth:`Binder.bind_scope` method::

    >>> class MyModule(Module):
    ...   def configure(self, binder):
    ...     binder.bind_scope(CustomScope)

Scopes can be retrieved from the injector, as with any other instance. They are
singletons across the life of the injector::

    >>> injector = Injector([MyModule()])
    >>> injector.get(CustomScope) is injector.get(CustomScope)
    True

For scopes with a transient lifetime, such as those tied to HTTP requests, the
usual solution is to use a thread or greenlet-local cache inside the scope. The
scope is "entered" in some low-level code by calling a method on the scope
instance that creates this cache. Once the request is complete, the scope is
"left" and the cache cleared.

Footnote
========
This framework is similar to snake-guice, but aims for simplification.

:copyright: (c) 2010 by Alec Thomas
:license: BSD

