# encoding: utf-8
#
# Copyright (C) 2010 Alec Thomas <alec@swapoff.org>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#
# Author: Alec Thomas <alec@swapoff.org>

"""Dependency injection framework.

This is based heavily on snake-guice, but is hopefully much simplified.

:copyright: (c) 2010 by Alec Thomas
:license: BSD
"""

import functools
import inspect
import types


class Error(Exception):
    """Base exception."""


class UnsatisfiedRequirement(Error):
    """Requirement could not be satisfied."""

    def __str__(self):
        on = '%s has an ' % _describe(self.args[0]) if self.args[0] else ''
        return '%sunsatisfied requirement on %s%s' % (
                on, self.args[1].annotation + '=' if self.args[1].annotation else '',
                _describe(self.args[1].interface))


class CircularDependency(Error):
    """Circular dependency detected."""


class Provider(object):
    """Provides class instances."""

    def get(self):
        raise NotImplementedError


class ClassProvider(Provider):
    """Provides instances from a given class, created using an Injector.
    """

    def __init__(self, cls, injector):
        self._cls = cls
        self._injector = injector

    def get(self):
        return self._injector._create_object(self._cls)


class CallableProvider(Provider):
    """Provides something using a callable."""

    def __init__(self, callable):
        self._callable = callable

    def get(self):
        return self._callable()


class InstanceProvider(Provider):
    """Provide a specific instance."""

    def __init__(self, instance):
        self._instance = instance

    def get(self):
        return self._instance


class ListOfProviders(Provider):
    """Provide a list of instances via other Providers."""

    def __init__(self, providers):
        self._providers = list(providers)

    def get(self):
        return [provider.get() for provider in self._providers]


# These classes are used internally by the Binder.
class Key(tuple):
    """A key mapping to a Binding.

    Keys can be used directly when bind()ing, as a convenience:

    >>> Name = Key(str, 'name')
    >>> def configure(binder):
    ...   binder.bind(Name, to='Bob')
    >>> Injector(configure).get(Name)
    'Bob'
    """

    def __new__(cls, interface, annotation=None):
        if type(interface) is list:
            interface = tuple(interface)
        t = tuple.__new__(cls, [interface, annotation])
        return t

    @property
    def interface(self):
        return self[0]

    @property
    def annotation(self):
        return self[1]


class Binding(tuple):
    """A binding from an (interface, annotation) to a provider in a scope."""

    def __new__(cls, *args):
        return tuple.__new__(cls, args)

    @property
    def interface(self):
        return self[0]

    @property
    def annotation(self):
        return self[1]

    @property
    def provider(self):
        return self[2]

    @property
    def scope(self):
        return self[3]


class Binder(object):
    """Bind interfaces to implementations."""

    def __init__(self, injector):
        self._injector = injector
        self._bindings = {}

    #def install(self, module):
        #"""Install bindings from another :class:`Module`."""
        ## TODO(alec) Confirm this is sufficient...
        #self._bindings.update(module._bindings)

    def mapbind(self, interface, key, to, annotation=None, scope=None):
        """Bind """

    def multibind(self, interface, to, annotation=None, scope=None):
        pass

    def bind(self, interface, to=None, annotation=None, scope=None):
        """Bind an interface to an implementation.

        :param interface: Interface, Key, or list of interfaces, to bind.
        :param to: Instance or class to bind to.
        :param annotation: Optional global annotation of interface.
        :param scope: Optional Scope in which to bind.
        """
        if type(interface) is Key:
            interface, annotation = interface.interface, interface.annotation
        to = to or interface
        if isinstance(interface, (list, tuple)):
            interface = tuple(interface)
            provider = ListOfProviders([self._provider_for(i, interface[0])
                                        for i in to])
        else:
            provider = self._provider_for(to, interface)
        if scope is None:
            scope = getattr(to, '__scope__', no_scope)
        binding = Binding(interface, annotation, provider, scope)
        self._bindings[Key(interface, annotation)] = binding

    def _provider_for(self, to, interface):
        if isinstance(to, Provider):
            return to
        elif isinstance(to, interface):
            return InstanceProvider(to)
        elif type(to) is type:
            return ClassProvider(to, self._injector)
        else:
            return CallableProvider(to)

    def _get_binding(self, cls, key):
        try:
            return self._bindings[key]
        except KeyError:
            raise UnsatisfiedRequirement(cls, key)


class Scope(object):
    """A Scope looks up the Provider for a binding.

    By default (ie. NoScope) this simply returns the default Provider.
    """
    def get(self, key, provider):
        raise NotImplementedError

    def __call__(self, cls):
        """Scopes may be used as a class decorator."""
        cls.__scope__ = self
        return cls


class NoScope(Scope):
    def get(self, key, provider):
        return provider


class SingletonScope(Scope):
    def __init__(self):
        self._cache = {}

    def get(self, key, provider):
        try:
            return self._cache[key]
        except KeyError:
            provider = InstanceProvider(provider.get())
            self._cache[key] = provider
            return provider


no_scope = NoScope()
singleton = SingletonScope()


class Module(object):
    """Configures injector and providers."""

    def __call__(self, binder):
        """Configure the binder."""
        self.__injector__ = binder._injector
        bindings = []
        for unused_name, function in inspect.getmembers(self, inspect.ismethod):
            if hasattr(function, '__binding__'):
                bindings.append(function.__binding__)
        for what, provider, annotation, scope in bindings:
            binder.bind(what,
                        to=types.MethodType(provider, self, self.__class__),
                        annotation=annotation,
                        scope=scope)
        self.configure(binder)

    def configure(self, binder):
        """Override to configure bindings."""


class Injector(object):
    """Creates object graph and injects dependencies."""

    def __init__(self, modules=None):
        """Construct a new Injector.

        :param modules: A callable, or list of callables, used to configure the
                        Binder associated with this Injector. Signature is
                        ``configure(binder)``.
        """
        self._stack = []
        self._binder = Binder(self)
        if not modules:
            modules = []
        elif not hasattr(modules, '__iter__'):
            modules = [modules]
        self._modules = modules
        self._binder.bind(Injector, to=self)
        self._binder.bind(Binder, to=self._binder)
        for module in self._modules:
            module(self._binder)

    def get(self, interface, annotation=None, scope=None):
        """Get an instance of the given interface.

        :param interface: Interface whose implementation we want.
        :param annotation: Optional annotation of the specific implementation.
        :param scope: Instance scope.
        :returns: An implementation of interface.
        """
        if type(interface) is Key:
            key = interface
        else:
            key = Key(interface, annotation)
        binding = self._binder._get_binding(None, key)
        return (scope or binding.scope).get(key, binding.provider).get()

    def _create_object(self, cls):
        """Create a new instance, satisfying any dependencies on cls."""
        instance = cls.__new__(cls)
        instance.__injector__ = self
        instance.__init__()
        return instance


def provides(what, annotation=None, scope=None):
    """Register a provider of a type.

    This decorator should be applied to Module subclass methods.

    >>> class MyModule(Module):
    ...   @provides(str, annotation='annotation')
    ...   def provide_name(self):
    ...     return 'Bob'
    """
    def wrapper(provider):
        provider.__binding__ = (what, provider, annotation, scope)
        return provider

    return wrapper


def inject(*anonymous_bindings, **named_bindings):
    """Decorator declaring parameters to be injected.

    Bindings can be anonymous, corresponding to positional arguments to
    inject(), or annotation, corresponding to keyword arguments to inject().

    Bound values can be in two forms: a class, or a one-element
    list of a type (eg. [str]).

    eg.

    >>> class A(object):
    ...     @inject(int, name=str, sizes=[int])
    ...     def __init__(self, number, name, sizes):
    ...         print number, name, sizes
    ...
    ...     @inject(names=[str])
    ...     def friends(self, names):
    ...       return ', '.join(names)

    >>> def configure(binder):
    ...     binder.bind(A)
    ...     binder.bind(int, to=123)
    ...     binder.bind(str, annotation='name', to='Bob')
    ...     binder.bind([int], annotation='sizes', to=[1, 2, 3])
    ...     binder.bind([str], annotation='names', to=['Fred', 'Barney'])

    Use the Injector to get a new instance of A:

    >>> a = Injector(configure).get(A)
    123 Bob [1, 2, 3]

    Call a method with arguments satisfied by the Injector:

    >>> a.friends()
    'Fred, Barney'
    """

    def wrapper(f):
        bindings = [Key(to) for to in anonymous_bindings] + \
                   [Key(to, annotation)
                    for annotation, to in named_bindings.items()]

        @functools.wraps(f)
        def inject(self_, *args, **kwargs):
            injector = getattr(self_, '__injector__', None)
            if injector is None:
                return f(self_, *args, **kwargs)
            else:
                assert not args and not kwargs
            anonymous_dependencies = []
            dependencies = {}
            key = (self_.__class__, f)

            def repr_key(k):
                return '%s.%s()' % tuple(map(_describe, k))

            if key in injector._stack:
                raise CircularDependency(
                        'circular dependency detected: %s -> %s' %
                        (' -> '.join(map(repr_key, injector._stack)),
                         repr_key(key)))

            injector._stack.append(key)
            try:
                for key in bindings:
                    try:
                        instance = injector.get(
                                key.interface, annotation=key.annotation)
                    except UnsatisfiedRequirement, e:
                        if not e.args[0]:
                            e = UnsatisfiedRequirement(self_.__class__,
                                                        e.args[1])
                        raise e
                    if key.annotation is None:
                        anonymous_dependencies.append(instance)
                    else:
                        dependencies[key.annotation] = instance
            finally:
                injector._stack.pop()
            return f(self_, *anonymous_dependencies, **dependencies)
        if hasattr(f, '__binding__'):
            inject.__binding__ = f.__binding__
        return inject
    return wrapper


class Annotation(object):
    """Annotation base type."""


def annotation(name):
    """Create a new :class:`Annotation` subclass.

    :param name: Name of the annotation type.
    :returns: Newly created unique type.
    """
    return type(name, (Annotation,), {})


def _describe(c):
    if hasattr(c, '__name__'):
        return c.__name__
    if type(c) in (tuple, list):
        return '[%s]' % c[0].__name__
    return str(c)
