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

import itertools
import functools
import inspect
import types
import threading
from abc import ABCMeta, abstractmethod
from collections import namedtuple


__author__ = 'Alec Thomas <alec@swapoff.org>'
__version__ = '0.5.2'
__version_tag__ = ''

def synchronized(lock):
    def outside_wrapper(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            with lock:
                return function(*args, **kwargs)
        return wrapper
    return outside_wrapper

lock = threading.RLock()


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

class CallError(Error):
    """Call to callable object fails."""

    def __str__(self):
        instance, method, args, kwargs, original_error = self.args
        if hasattr(method, 'im_class'):
            instance = method.__self__
            method_name = method.__func__.__name__
        else:
            method_name = method.__name__

        full_method = '.'.join((repr(instance) if instance else '', method_name)).strip('.')

        parameters = ', '.join(itertools.chain(
            (repr(arg) for arg in args),
            ('%s=%r' % (key, value) for (key, value) in kwargs.items())
        ))
        return 'Call to %s(%s) failed: %s' % (
            full_method, parameters, original_error)


class CircularDependency(Error):
    """Circular dependency detected."""


class UnknownProvider(Error):
    """Tried to bind to a type whose provider couldn't be determined."""


class Provider(object):
    """Provides class instances."""

    __metaclass__ = ABCMeta

    @abstractmethod
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
            what = (dict, BindingKey(list(what.items())[0], None))
        return tuple.__new__(cls, (what, annotation))

    @property
    def interface(self):
        return self[0]

    @property
    def annotation(self):
        return self[1]


BindingBase = namedtuple("BindingBase", 'interface annotation provider scope')


class Binding(BindingBase):
    """A binding from an (interface, annotation) to a provider in a scope."""


class Binder(object):
    """Bind interfaces to implementations.

    :attr injector: Injector this Binder is associated with.
    """

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
        elif isinstance(interface, AssistedBuilder):
            builder = AssistedBuilderImplementation(interface.interface, self.injector)
            return InstanceProvider(builder)
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

    __metaclass__ = ABCMeta

    def __init__(self, injector):
        self.injector = injector
        self.configure()

    def configure(self):
        """Configure the scope."""

    @abstractmethod
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
        self._context = {}

    @synchronized(lock)
    def get(self, key, provider):
        try:
            return self._context[key]
        except KeyError:
            provider = InstanceProvider(provider.get())
            self._context[key] = provider
            return provider


singleton = ScopeDecorator(SingletonScope)


class ThreadLocalScope(Scope):
    """A :class:`Scope` that returns a per-thread instance for a key."""
    def configure(self):
        self._locals = threading.local()

    def get(self, key, provider):
        try:
            return getattr(self._locals, repr(key))
        except AttributeError:
            provider = InstanceProvider(provider.get())
            setattr(self._locals, repr(key), provider)
            return provider


threadlocal = ScopeDecorator(ThreadLocalScope)


class Module(object):
    """Configures injector and providers."""

    def __call__(self, binder):
        """Configure the binder."""
        self.__injector__ = binder.injector
        for unused_name, function in inspect.getmembers(self, inspect.ismethod):
            binding = None
            if hasattr(function, '__binding__'):
                binding = function.__binding__
                binder.bind(binding.interface,
                        to=types.MethodType(binding.provider, self),
                        annotation=binding.annotation, scope=binding.scope)
            elif hasattr(function, '__multibinding__'):
                binding = function.__multibinding__
                binder.multibind(binding.interface,
                        to=types.MethodType(binding.provider, self),
                        annotation=binding.annotation, scope=binding.scope)
        self.configure(binder)

    def configure(self, binder):
        """Override to configure bindings."""


class Injector(object):
    """Initialise and use an object dependency graph."""

    def __init__(self, modules=None, auto_bind=True):
        """Construct a new Injector.

        :param modules: A callable, class, or list of callables/classes, used to configure the
                        Binder associated with this Injector. Typically these
                        callables will be subclasses of :class:`Module`.

                        In case of class, it's instance will be created using parameterless
                        constructor before the configuration process begins.

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
        self.binder.bind_scope(ThreadLocalScope)
        # Bind some useful types
        self.binder.bind(Injector, to=self)
        self.binder.bind(Binder, to=self.binder)
        # Initialise modules
        for module in modules:
            if isinstance(module, type):
                module = module()

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

    def create_object(self, cls, additional_kwargs=None):
        """Create a new instance, satisfying any dependencies on cls."""

        additional_kwargs = additional_kwargs or {}
        instance = cls.__new__(cls)
        try:
            self.install_into(instance)
        except AttributeError:
            # Some builtin types can not be modified.
            pass
        try:
            instance.__init__(**additional_kwargs)
        except TypeError as e:
            # The reason why getattr() fallback is used here is that
            # __init__.__func__ apparently doesn't exist for Key-type objects
            raise CallError(instance,
                getattr(instance.__init__, '__func__', instance.__init__),
                (), additional_kwargs, e)
        return instance

    def install_into(self, instance):
        """
        Puts injector reference in given object.
        """
        instance.__injector__ = self

    @synchronized(lock)
    def args_to_inject(self, function, bindings, owner_key):
        """Inject arguments into a function.

        :param function: The function.
        :param bindings: Map of argument name to binding key to inject.
        :param owner_key: A key uniquely identifying the *scope* of this function.
            For a method this will be the owning class.
        :returns: Dictionary of resolved arguments.
        """
        dependencies = {}
        key = (owner_key, function)

        def repr_key(k):
            return '%s.%s()' % tuple(map(_describe, k))

        if key in self._stack:
            raise CircularDependency(
                    'circular dependency detected: %s -> %s' %
                    (' -> '.join(map(repr_key, self._stack)),
                     repr_key(key)))

        self._stack.append(key)
        try:
            for arg, key in bindings.items():
                try:
                    instance = self.get(key.interface,
                            annotation=key.annotation)
                except UnsatisfiedRequirement as e:
                    if not e.args[0]:
                        e = UnsatisfiedRequirement(owner_key, e.args[1])
                    raise e
                dependencies[arg] = instance
        finally:
            self._stack.pop()

        return dependencies


def with_injector(*injector_args, **injector_kwargs):
    """
    Decorator for a method. Installs Injector object which the method belongs
    to before the decorated method is executed.

    Parameters are the same as for Injector constructor.
    """
    def wrapper(f):
        @functools.wraps(f)
        def setup(self_, *args, **kwargs):
            injector = Injector(*injector_args, **injector_kwargs)
            injector.install_into(self_)
            return f(self_, *args, **kwargs)

        return setup

    return wrapper


def provides(interface, annotation=None, scope=None, eager=False):
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
        provider.__binding__ = Binding(interface, annotation, provider, scope)
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
        provider.__multibinding__ = Binding(interface, annotation, provider, scope)
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
    ...         print([number, name, sizes])
    ...
    ...     @inject(names=Names)
    ...     def friends(self, names):
    ...       '''Get my friends'''
    ...       return ', '.join(names)

    >>> def configure(binder):
    ...     binder.bind(A)
    ...     binder.bind(int, to=123)
    ...     binder.bind(str, to='Bob')
    ...     binder.bind(Sizes, to=[1, 2, 3])
    ...     binder.bind(Names, to=['Fred', 'Barney'])

    Use the Injector to get a new instance of A:

    >>> a = Injector(configure).get(A)
    [123, 'Bob', [1, 2, 3]]

    Call a method with arguments satisfied by the Injector:

    >>> a.friends()
    'Fred, Barney'

    >>> a.friends.__doc__
    'Get my friends'
    """

    def wrapper(f):
        for key, value in bindings.items():
            bindings[key] = BindingKey(value, None)
        if hasattr(inspect, 'getfullargspec'):
            args = inspect.getfullargspec(f)
        else:
            args = inspect.getargspec(f)
        if args[0][0] == 'self':
            @functools.wraps(f)
            def inject(self_, *args, **kwargs):
                injector = getattr(self_, '__injector__', None)
                if injector is None:
                    try:
                        return f(self_, *args, **kwargs)
                    except TypeError as e:
                        raise CallError(self_, f, args, kwargs, e)
                dependencies = injector.args_to_inject(
                    function=f,
                    bindings=bindings,
                    owner_key=self_.__class__,
                    )
                dependencies.update(kwargs)
                try:
                    return f(self_, *args, **dependencies)
                except TypeError as e:
                    raise CallError(self_, f, args, dependencies, e)
            # Propagate @provides bindings to wrapper function
            if hasattr(f, '__binding__'):
                inject.__binding__ = f.__binding__
        else:
            inject = f
        inject.__bindings__ = bindings
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

    def __init__(self):
        raise Exception('Instantiation of %s prohibited - it is derived from BaseKey '
                        'so most likely you should bind it to something.' % (self.__class__,))


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
    try:
        if isinstance(name, unicode):
            name = name.encode('utf-8')
    except NameError:
        pass
    return type(name, (BaseKey,), {})

class AssistedBuilder(object):
    def __init__(self, interface):
        self.interface = interface

class AssistedBuilderImplementation(object):
    def __init__(self, interface, injector):
        self.interface = interface
        self.injector = injector

    def build(self, **kwargs):
        key = BindingKey(self.interface, None)
        binder = self.injector.binder
        binding = binder.get_binding(None, key)
        provider = binding.provider
        try:
            cls = provider._cls
        except AttributeError:
            raise Error('Assisted building works only with ClassProviders, '
                        'got %r for %r' % (provider, self.interface))
        return self.injector.create_object(cls, additional_kwargs=kwargs)

def _describe(c):
    if hasattr(c, '__name__'):
        return c.__name__
    if type(c) in (tuple, list):
        return '[%s]' % c[0].__name__
    return str(c)
