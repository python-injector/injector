# encoding: utf-8
#
# Copyright (C) 2010 Alec Thomas <alec@swapoff.org>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#
# Author: Alec Thomas <alec@swapoff.org>

"""Injector - Python dependency injection framework, inspired by Guice

See http://pypi.python.org/pypi/injector for documentation.

:copyright: (c) 2012 by Alec Thomas
:license: BSD
"""

import functools
import inspect
import types


__author__ = 'Alec Thomas <alec@swapoff.org>'
__version__ = '0.4.1'
__version_tag__ = ''


class Error(Exception):
    """Base exception."""


class UnsatisfiedRequirement(Error):
    """Requirement could not be satisfied."""

    def __str__(self):
        on = '%s has an ' % _describe(self.args[0]) if self.args[0] else ''
        return '%sunsatisfied requirement on %s%s' % (on,
                self.args[1].annotation + '='
                if self.args[1].annotation else '',
                _describe(self.args[1].interface))


class CircularDependency(Error):
    """Circular dependency detected."""


class UnknownProvider(Error):
    """Tried to bind to a type whose provider couldn't be determined."""


class Provider(object):
    """Provides class instances."""

    def get(self):
        raise NotImplementedError


class ClassProvider(Provider):
    """Provides instances from a given class, created using an Injector."""

    def __init__(self, cls, injector):
        self._cls = cls
        self.injector = injector

    def get(self):
        return self.injector.create_object(self._cls)


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

    def __init__(self):
        self._providers = []

    def append(self, provider):
        self._providers.append(provider)

    def get(self):
        return [provider.get() for provider in self._providers]


class MultiBindProvider(ListOfProviders):
    """Used by :meth:`Binder.multibind` to flatten results of providers that
    return sequences."""

    def get(self):
        return [i for provider in self._providers for i in provider.get()]


class MapBindProvider(ListOfProviders):
    """A provider for map bindings."""

    def get(self):
        map = {}
        for provider in self._providers:
            map.update(provider.get())
        return map

# These classes are used internally by the Binder.
class BindingKey(tuple):
    """A key mapping to a Binding."""

    def __new__(cls, what, annotation):
        if isinstance(what, list):
            if len(what) != 1:
                raise Error('list bindings must have a single interface '
                            'element')
            what = (list, BindingKey(what[0], None))
        elif isinstance(what, dict):
            if len(what) != 1:
                raise Error('dictionary bindings must have a single interface '
                            'key and value')
            what = (dict, BindingKey(what.items()[0], None))
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

    def __init__(self, injector, auto_bind=True):
        """Create a new Binder.

        :param injector: Injector we are binding for.
        """
        self.injector = injector
        self._auto_bind = auto_bind
        self._bindings = {}

    def bind(self, interface, to=None, annotation=None, scope=None):
        """Bind an interface to an implementation.

        :param interface: Interface or :func:`Key` to bind.
        :param to: Instance or class to bind to, or an explicit
             :class:`Provider` subclass.
        :param annotation: Optional global annotation of interface.
        :param scope: Optional :class:`Scope` in which to bind.
        """
        key = BindingKey(interface, annotation)
        self._bindings[key] = \
                self.create_binding(interface, to, annotation, scope)

    def bind_scope(self, scope):
        """Bind a Scope.

        :param scope: Scope class.
        """
        self.bind(scope, to=scope(self.injector))

    def multibind(self, interface, to, annotation=None, scope=None):
        """Creates or extends a multi-binding.

        A multi-binding maps from a key to a sequence, where each element in
        the sequence is provided separately.

        :param interface: Interface or :func:`Key` to bind.
        :param to: Instance, class to bind to, or an explicit :class:`Provider`
                subclass. Must provide a sequence.
        :param annotation: Optional global annotation of interface.
        :param scope: Optional Scope in which to bind.
        """
        key = BindingKey(interface, annotation)
        if key not in self._bindings:
            if isinstance(interface, dict):
                provider = MapBindProvider()
            else:
                provider = MultiBindProvider()
            binding = self.create_binding(
                    interface, provider, annotation, scope)
            self._bindings[key] = binding
        else:
            provider = self._bindings[key].provider
            assert isinstance(provider, ListOfProviders)
        provider.append(self.provider_for(key.interface, to))

    def install(self, module):
        """Install a module into this binder."""
        module(self)

    def create_binding(self, interface, to=None, annotation=None, scope=None):
        to = to or interface
        provider = self.provider_for(interface, to)
        if scope is None:
            scope = getattr(to, '__scope__', NoScope)
        if isinstance(scope, ScopeDecorator):
            scope = scope.scope
        return Binding(interface, annotation, provider, scope)

    def provider_for(self, interface, to=None):
        if isinstance(to, Provider):
            return to
        elif isinstance(to, (types.FunctionType, types.LambdaType,
                             types.MethodType, types.BuiltinFunctionType,
                             types.BuiltinMethodType)):
            return CallableProvider(to)
        elif issubclass(type(to), type):
            return ClassProvider(to, self.injector)
        elif isinstance(to, interface):
            return InstanceProvider(to)
        elif issubclass(type(interface), type):
            if issubclass(interface, BaseKey):
                return InstanceProvider(to)
            return ClassProvider(interface, self.injector)
        else:
            raise UnknownProvider('couldn\'t determine provider for %r to %r' %
                                  (interface, to))

    def get_binding(self, cls, key):
        try:
            return self._bindings[key]
        except KeyError:
            if self._auto_bind:
                binding = self.create_binding(key.interface,
                        annotation=key.annotation)
                self._bindings[key] = binding
                return binding
            raise UnsatisfiedRequirement(cls, key)


class Scope(object):
    """A Scope looks up the Provider for a binding.

    By default (ie. :class:`NoScope` ) this simply returns the default
    :class:`Provider` .
    """

    def __init__(self, injector):
        self.injector = injector
        self.configure()

    def configure(self):
        """Configure the scope."""

    def get(self, key, provider):
        """Get a :class:`Provider` for a key.

        :param key: The key to return a provider for.
        :param provider: The default Provider associated with the key.
        :returns: A Provider instance that can provide an instance of key.
        """
        raise NotImplementedError


class ScopeDecorator(object):
    def __init__(self, scope):
        self.scope = scope

    def __call__(self, cls):
        cls.__scope__ = self.scope
        return cls

    def __repr__(self):
        return 'ScopeDecorator(%s)' % self.scope.__name__


class NoScope(Scope):
    """An unscoped provider."""
    def __init__(self, injector=None):
        super(NoScope, self).__init__(injector)

    def get(self, unused_key, provider):
        return provider


noscope = ScopeDecorator(NoScope)


class SingletonScope(Scope):
    """A :class:`Scope` that returns a per-Injector instance for a key.

    :data:`singleton` can be used as a convenience class decorator.

    >>> class A(object): pass
    >>> injector = Injector()
    >>> provider = ClassProvider(A, injector)
    >>> singleton = SingletonScope(injector)
    >>> a = singleton.get(A, provider)
    >>> b = singleton.get(A, provider)
    >>> a is b
    True
    """
    def configure(self):
        self.context = {}

    def get(self, key, provider):
        try:
            return self.context[key]
        except KeyError:
            provider = InstanceProvider(provider.get())
            self.context[key] = provider
            return provider


singleton = ScopeDecorator(SingletonScope)


class Module(object):
    """Configures injector and providers."""

    def __call__(self, binder):
        """Configure the binder."""
        self.__injector__ = binder.injector
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
    """Initialise and use an object dependency graph."""

    def __init__(self, modules=None, auto_bind=True):
        """Construct a new Injector.

        :param modules: A callable, or list of callables, used to configure the
                        Binder associated with this Injector. Typically these
                        callables will be subclasses of :class:`Module` .
                        Signature is ``configure(binder)``.
        :param auto_bind: Whether to automatically bind missing types.
        """
        # Stack of keys currently being injected. Used to detect circular
        # dependencies.
        self._stack = []

        # Binder
        self.binder = Binder(self, auto_bind=auto_bind)

        if not modules:
            modules = []
        elif not hasattr(modules, '__iter__'):
            modules = [modules]

        # Bind scopes
        self.binder.bind_scope(NoScope)
        self.binder.bind_scope(SingletonScope)
        # Bind some useful types
        self.binder.bind(Injector, to=self)
        self.binder.bind(Binder, to=self.binder)
        # Initialise modules
        for module in modules:
            module(self.binder)

    def get(self, interface, annotation=None, scope=None):
        """Get an instance of the given interface.

        :param interface: Interface whose implementation we want.
        :param annotation: Optional annotation of the specific implementation.
        :param scope: Class of the Scope in which to resolve.
        :returns: An implementation of interface.
        """
        key = BindingKey(interface, annotation)
        binding = self.binder.get_binding(None, key)
        scope = scope or binding.scope
        if isinstance(scope, ScopeDecorator):
            scope = scope.scope
        # Fetch the corresponding Scope instance from the Binder.
        scope_key = BindingKey(scope, None)
        try:
            scope_binding = self.binder.get_binding(None, scope_key)
            scope_instance = scope_binding.provider.get()
        except UnsatisfiedRequirement as e:
            raise Error('%s; scopes must be explicitly bound '
                        'with Binder.bind_scope(scope_cls)' % e)
        return scope_instance.get(key, binding.provider).get()

    def create_object(self, cls):
        """Create a new instance, satisfying any dependencies on cls."""
        instance = cls.__new__(cls)
        try:
            instance.__injector__ = self
        except AttributeError:
            # Some builtin types can not be modified.
            pass
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
    """A decorator for :class:`Module` methods that return sequences of
    implementations of interface.

    This is a convenient way of declaring a :meth:`Module.multibind` .

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
                    except UnsatisfiedRequirement as e:
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

    Typically when using Injector, complex types can be bound to providers
    directly.

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
