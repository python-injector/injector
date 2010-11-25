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


__author__ = 'Alec Thomas <alec@swapoff.org>'
__version__ = '0.1'


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

    def append(self, provider):
        self._providers.append(provider)

    def get(self):
        return [provider.get() for provider in self._providers]


# These classes are used internally by the Binder.
class BindingKey(tuple):
    """A key mapping to a Binding."""

    def __new__(cls, what, annotation):
        return tuple.__new__(cls, (what, annotation))

    @property
    def interface(self):
        return self[0]

    @property
    def annotation(self):
        return self[1]


class Binding(tuple):
    """A binding from an (interface, annotation) to a provider in a scope."""

    def __new__(cls, interface, annotation, provider, scope):
        return tuple.__new__(cls, (interface, annotation, provider, scope))

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

    def bind(self, interface, to=None, annotation=None, scope=None):
        """Bind an interface to an implementation.

        :param interface: Interface or Key to bind.
        :param to: Instance or class to bind to, or an explicit
             :class:`Provider` subclass.
        :param annotation: Optional global annotation of interface.
        :param scope: Optional Scope in which to bind.
        """
        key = BindingKey(interface, annotation)
        self._bindings[key] = \
                self._create_binding(interface, to, annotation, scope)

    def multibind(self, interface, to, annotation=None, scope=None):
        """Creates or extends a multi-binding.

        A multi-binding is a mapping from an interface or Key to 

        See :meth:`bind` for argument descriptions.
        """
        key = BindingKey(interface, annotation)
        if key not in self._bindings:
            provider = ListOfProviders([])
            binding = self._create_binding(
                    interface, provider, annotation, scope)
            self._bindings[key] = binding
        else:
            provider = self._bindings[key].provider
            assert isinstance(provider, ListOfProviders)
        provider.append(self._provider_for(key.interface, to))

    def _create_binding(self, interface, to, annotation, scope):
        to = to or interface
        provider = self._provider_for(interface, to)
        if scope is None:
            scope = getattr(to, '__scope__', noscope)
        return Binding(interface, annotation, provider, scope)

    def _provider_for(self, interface, to):
        if isinstance(to, Provider):
            return to
        elif isinstance(to, interface):
            return InstanceProvider(to)
        elif type(to) is type:
            return ClassProvider(to, self._injector)
        elif type(interface) is type and issubclass(interface, BaseKey):
            if callable(to):
                return CallableProvider(to)
            return InstanceProvider(to)
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
        """Scopes may be used as class decorators."""
        cls.__scope__ = self
        return cls


class NoScope(Scope):
    """A binding without scope.

    This is the default. Every :meth:`Injector.get` results in a new instance
    being created.
    """
    def get(self, unused_key, provider):
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


noscope = NoScope()
singleton = SingletonScope()


class Module(object):
    """Configures injector and providers."""

    def __call__(self, binder):
        """Configure the binder."""
        self.__injector__ = binder._injector
        for unused_name, function in inspect.getmembers(self, inspect.ismethod):
            if hasattr(function, '__binding__'):
                what, provider, annotation, scope = function.__binding__
                binder.bind(what,
                        to=types.MethodType(provider, self, self.__class__),
                        annotation=annotation, scope=scope)
            elif hasattr(function, '__multibinding__'):
                what, provider, annotation, scope = function.__multibinding__
                binder.multibind(what,
                        to=types.MethodType(provider, self, self.__class__),
                        annotation=annotation, scope=scope)
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
        key = BindingKey(interface, annotation)
        binding = self._binder._get_binding(None, key)
        return (scope or binding.scope).get(key, binding.provider).get()

    def _create_object(self, cls):
        """Create a new instance, satisfying any dependencies on cls."""
        instance = cls.__new__(cls)
        instance.__injector__ = self
        instance.__init__()
        return instance


def provides(interface, annotation=None, scope=None):
    """Decorator for :class:`Module` methods, registering a provider of a type.

    >>> class MyModule(Module):
    ...   @provides(str, annotation='annotation')
    ...   def provide_name(self):
    ...     return 'Bob'

    :param interface: Interface to provide.
    :param annotation: Optional annotation value.
    :param scope: Optional scope of provided value.
    """
    def wrapper(provider):
        provider.__binding__ = (interface, provider, annotation, scope)
        return provider

    return wrapper


def extends(interface, annotation=None, scope=None):
    """A decorator for :class:`Module` methods, extending a
    :meth:`Module.multibind`.

    :param interface: Interface to provide.
    :param annotation: Optional annotation value.
    :param scope: Optional scope of provided value.
    """
    def wrapper(provider):
        provider.__multibinding__ = (interface, provider, annotation, scope)
        return provider

    return wrapper


def inject(**bindings):
    """Decorator declaring parameters to be injected.

    eg.

    >>> Sizes = Key('sizes')
    >>> Names = Key('names')

    >>> class A(object):
    ...     @inject(number=int, name=str, sizes=Sizes)
    ...     def __init__(self, number, name, sizes):
    ...         print number, name, sizes
    ...
    ...     @inject(names=Names)
    ...     def friends(self, names):
    ...       return ', '.join(names)

    >>> def configure(binder):
    ...     binder.bind(A)
    ...     binder.bind(int, to=123)
    ...     binder.bind(str, to='Bob')
    ...     binder.bind(Sizes, to=[1, 2, 3])
    ...     binder.bind(Names, to=['Fred', 'Barney'])

    Use the Injector to get a new instance of A:

    >>> a = Injector(configure).get(A)
    123 Bob [1, 2, 3]

    Call a method with arguments satisfied by the Injector:

    >>> a.friends()
    'Fred, Barney'
    """

    def wrapper(f):
        for key, value in bindings.iteritems():
            bindings[key] = BindingKey(value, None)

        @functools.wraps(f)
        def inject(self_, *args, **kwargs):
            injector = getattr(self_, '__injector__', None)
            if injector is None:
                return f(self_, *args, **kwargs)
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
                for arg, key in bindings.iteritems():
                    try:
                        instance = injector.get(key.interface,
                                annotation=key.annotation)
                    except UnsatisfiedRequirement, e:
                        if not e.args[0]:
                            e = UnsatisfiedRequirement(self_.__class__,
                                                        e.args[1])
                        raise e
                    dependencies[arg] = instance
            finally:
                injector._stack.pop()
            dependencies.update(kwargs)
            return f(self_, *args, **dependencies)
        if hasattr(f, '__binding__'):
            inject.__binding__ = f.__binding__
        return inject
    return wrapper


class BaseAnnotation(object):
    """Annotation base type."""


def Annotation(name):
    """Create a new annotation type.

    Useful for declaring a unique annotation type.

    :param name: Name of the annotation type.
    :returns: Newly created unique type.
    """
    return type(name, (BaseAnnotation,), {})


class BaseKey(object):
    """Base type for binding keys."""


def Key(name):
    """Create a new type key.

    Keys are a convenient alternative to binding to (type, annotation) pairs,
    particularly when non-unique types such as str or int are being bound.

    eg. if using @provides(str), chances of collision are almost guaranteed.
    One solution is to use @provides(str, annotation='unique') everywhere
    you wish to inject the value, but this is verbose and error prone. Keys
    solve this problem:

    >>> Age = Key('Age')
    >>> def configure(binder):
    ...   binder.bind(Age, to=90)
    >>> Injector(configure).get(Age)
    90
    """
    return type(name, (BaseKey,), {})


def _describe(c):
    if hasattr(c, '__name__'):
        return c.__name__
    if type(c) in (tuple, list):
        return '[%s]' % c[0].__name__
    return str(c)
