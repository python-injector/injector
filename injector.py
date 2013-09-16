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

See https://github.com/alecthomas/injector for documentation.

:copyright: (c) 2012 by Alec Thomas
:license: BSD
"""

import itertools
import functools
import inspect
import logging
import sys
import types
import threading
from abc import ABCMeta, abstractmethod
from collections import namedtuple

try:
    NullHandler = logging.NullHandler
except AttributeError:
    class NullHandler(logging.Handler):
        def emit(self, record):
            pass

__author__ = 'Alec Thomas <alec@swapoff.org>'
__version__ = '0.7.8'
__version_tag__ = ''

log = logging.getLogger('injector')
log.addHandler(NullHandler())

if log.level == logging.NOTSET:
    log.setLevel(logging.WARN)


def private(something):
    something.__private__ = True
    return something


def synchronized(lock):
    def outside_wrapper(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            with lock:
                return function(*args, **kwargs)
        return wrapper
    return outside_wrapper

lock = threading.RLock()


def reraise(original, exception):
    prev_cls, prev, tb = sys.exc_info()
    frames = inspect.getinnerframes(tb)
    if len(frames) > 1:
        exception = original
    try:
        raise exception.with_traceback(tb)
    except AttributeError:
        # This syntax is not a valid Python 3 syntax so we have
        # to work around that
        exec('raise exception.__class__, exception, tb')


class Error(Exception):
    """Base exception."""


class UnsatisfiedRequirement(Error):
    """Requirement could not be satisfied."""

    def __str__(self):
        on = '%s has an ' % _describe(self.args[0]) if self.args[0] else ''
        return '%sunsatisfied requirement on %s%s' % (
            on,
            self.args[1].annotation + '='if self.args[1].annotation else '',
            _describe(self.args[1].interface),
            )


class CallError(Error):
    """Call to callable object fails."""

    def __str__(self):
        if len(self.args) == 1:
            return self.args[0]

        instance, method, args, kwargs, original_error, stack = self.args
        if hasattr(method, 'im_class'):
            instance = method.__self__
            method_name = method.__func__.__name__
        else:
            method_name = method.__name__

        cls = instance.__class__.__name__ if instance is not None else ''

        full_method = '.'.join((cls, method_name)).strip('.')

        parameters = ', '.join(itertools.chain(
            (repr(arg) for arg in args),
            ('%s=%r' % (key, value) for (key, value) in kwargs.items())
        ))
        return 'Call to %s(%s) failed: %s (injection stack: %r)' % (
            full_method, parameters, original_error, [level[0] for level in stack])


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


@private
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


@private
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


_BindingBase = namedtuple('_BindingBase', 'interface annotation provider scope')


@private
class Binding(_BindingBase):
    """A binding from an (interface, annotation) to a provider in a scope."""


class Binder(object):
    """Bind interfaces to implementations."""

    @private
    def __init__(self, injector, auto_bind=True, parent=None):
        """Create a new Binder.

        :param injector: Injector we are binding for.
        :param auto_bind: Whether to automatically bind missing types.
        :param parent: Parent binder.
        """
        self.injector = injector
        self._auto_bind = auto_bind
        self._bindings = {}
        self.parent = parent

    def bind(self, interface, to=None, annotation=None, scope=None):
        """Bind an interface to an implementation.

        :param interface: Interface or :func:`Key` to bind.
        :param to: Instance or class to bind to, or an explicit
             :class:`Provider` subclass.
        :param annotation: Optional global annotation of interface.
        :param scope: Optional :class:`Scope` in which to bind.
        """
        if type(interface) is type and issubclass(interface, (BaseMappingKey, BaseSequenceKey)):
            return self.multibind(interface, to, annotation=annotation, scope=scope)
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

        :param interface: :func:`MappingKey` or :func:`SequenceKey` to bind to.
        :param to: Instance, class to bind to, or an explicit :class:`Provider`
                subclass. Must provide a sequence.
        :param annotation: Optional global annotation of interface.
        :param scope: Optional Scope in which to bind.
        """
        key = BindingKey(interface, annotation)
        if key not in self._bindings:
            if isinstance(interface, dict) or isinstance(interface, type) and issubclass(interface, dict):
                provider = MapBindProvider()
            else:
                provider = MultiBindProvider()
            binding = self.create_binding(
                interface, provider, annotation, scope)
            self._bindings[key] = binding
        else:
            binding = self._bindings[key]
            provider = binding.provider
            assert isinstance(provider, ListOfProviders)
        provider.append(self.provider_for(key.interface, to))

    def install(self, module):
        """Install a module into this binder.

        :param module: A Module instance, Module subclass, or a function.
        """
        if type(module) is type and issubclass(module, Module):
            instance = self.injector.create_object(module)
            instance(self)
        else:
            self.injector.call_with_injection(
                callable=module,
                self_=None,
                args=(self,),
            )

    def create_binding(self, interface, to=None, annotation=None, scope=None):
        provider = self.provider_for(interface, to)
        scope = scope or getattr(to or interface, '__scope__', NoScope)
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
        elif isinstance(interface, ParameterizedBuilder):
            builder = AssistedBuilderImplementation(self.injector, interface.interface, None, None)
            return CallableProvider(lambda: builder.build(**interface.kwargs))
        elif isinstance(interface, AssistedBuilder):
            builder = AssistedBuilderImplementation(self.injector, *interface)
            return InstanceProvider(builder)
        elif isinstance(interface, (tuple, type)) and isinstance(to, interface):
            return InstanceProvider(to)
        elif issubclass(type(interface), type) or isinstance(interface, (tuple, list)):
            if issubclass(interface, (BaseKey, BaseMappingKey, BaseSequenceKey)):
                return InstanceProvider(to)
            return ClassProvider(interface, self.injector)
        elif hasattr(interface, '__call__'):
            function = to or interface
            if hasattr(function, '__bindings__'):
                function = self.injector.wrap_function(function)

            return InstanceProvider(function)

        else:
            raise UnknownProvider('couldn\'t determine provider for %r to %r' %
                                  (interface, to))

    def _get_binding(self, key):
        binding = self._bindings.get(key)
        if not binding and self.parent:
            binding = self.parent._get_binding(key)

        if not binding:
            raise KeyError

        return binding

    def get_binding(self, cls, key):
        try:
            return self._get_binding(key)
        except (KeyError, UnsatisfiedRequirement):
            if self._auto_bind:
                binding = self.create_binding(
                    key.interface,
                    annotation=key.annotation,
                    )
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
        binding = getattr(cls, '__binding__', None)
        if binding:
            new_binding = Binding(
                interface=binding.interface,
                annotation=binding.annotation,
                provider=binding.provider,
                scope=self.scope)
            setattr(cls, '__binding__', new_binding)
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
                binder.bind(
                    binding.interface,
                    to=types.MethodType(binding.provider, self),
                    annotation=binding.annotation,
                    scope=binding.scope,
                    )
        self.configure(binder)

    def configure(self, binder):
        """Override to configure bindings."""


class Injector(object):
    """Initialise and use an object dependency graph."""

    def __init__(self, modules=None, auto_bind=True, parent=None, use_annotations=False):
        """Construct a new Injector.

        :param modules: A callable, class, or list of callables/classes, used to configure the
                        Binder associated with this Injector. Typically these
                        callables will be subclasses of :class:`Module`.

                        In case of class, it's instance will be created using parameterless
                        constructor before the configuration process begins.

                        Signature is ``configure(binder)``.
        :param auto_bind: Whether to automatically bind missing types.
        :param parent: Parent injector.
        :param use_annotations: Attempt to infer injected arguments using Python3 argument annotations.
        """
        # Stack of keys currently being injected. Used to detect circular
        # dependencies.
        self._stack = ()

        self.parent = parent
        self.use_annotations = use_annotations

        # Binder
        self.binder = Binder(self, auto_bind=auto_bind, parent=parent and parent.binder)

        if not modules:
            modules = []
        elif not hasattr(modules, '__iter__'):
            modules = [modules]

        if not parent:
            # Bind scopes
            self.binder.bind_scope(NoScope)
            self.binder.bind_scope(SingletonScope)
            self.binder.bind_scope(ThreadLocalScope)

        # Bind some useful types
        self.binder.bind(Injector, to=self)
        self.binder.bind(Binder, to=self.binder)
        # Initialise modules
        for module in modules:
            self.binder.install(module)

    @property
    def _log_prefix(self):
        return '>' * (len(self._stack) + 1) + ' '

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

        log.debug('%sInjector.get(%r, annotation=%r, scope=%r) using %r', self._log_prefix, interface, annotation, scope, binding.provider)
        result = scope_instance.get(key, binding.provider).get()
        log.debug('%s -> %r', self._log_prefix, result)
        return result

    def create_child_injector(self, *args, **kwargs):
        return Injector(*args, parent=self, **kwargs)

    def create_object(self, cls, additional_kwargs=None):
        """Create a new instance, satisfying any dependencies on cls."""
        additional_kwargs = additional_kwargs or {}
        log.debug('%sCreating %r object with %r', self._log_prefix, cls, additional_kwargs)

        if self.use_annotations and hasattr(cls, '__init__') and not hasattr(cls.__init__, '__binding__'):
            bindings = self._infer_injected_bindings(cls.__init__)
            cls.__init__ = inject(**bindings)(cls.__init__)

        instance = cls.__new__(cls)
        try:
            self.install_into(instance)
        except AttributeError:
            if hasattr(instance, '__slots__'):
                raise Error('Can\'t create an instance of type %r due to presence of __slots__, '
                            'remove __slots__ to fix that' % (cls,))

            # Else do nothing - some builtin types can not be modified.
        try:
            instance.__init__(**additional_kwargs)
        except TypeError as e:
            # The reason why getattr() fallback is used here is that
            # __init__.__func__ apparently doesn't exist for Key-type objects
            reraise(e, CallError(
                instance,
                getattr(instance.__init__, '__func__', instance.__init__),
                (), additional_kwargs, e, self._stack,)
            )
        return instance

    def _infer_injected_bindings(self, callable):
        if not getfullargspec or not self.use_annotations:
            return None
        spec = getfullargspec(callable)
        return dict(spec.annotations.items())

    def install_into(self, instance):
        """
        Puts injector reference in given object.
        """
        instance.__injector__ = self

    @private
    def wrap_function(self, function):
        """Create function wrapper that will take care of it's dependencies.

        You only need to provide noninjectable arguments to the wrapped function.

        :return: Wrapped function.
        """

        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            return self.call_with_injection(
                callable=function,
                args=args,
                kwargs=kwargs
            )

        return wrapper

    @private
    def call_with_injection(self, callable, self_=None, args=(), kwargs={}):
        """Call a callable and provide it's dependencies if needed.

        :param self_: Instance of a class callable belongs to if it's a method,
            None otherwise.
        :param args: Arguments to pass to callable.
        :param kwargs: Keyword arguments to pass to callable.
        :type callable: callable
        :type args: tuple of objects
        :type kwargs: dict of string -> object
        :return: Value returned by callable.
        """
        bindings = getattr(callable, '__bindings__', None) or {}
        needed = dict((k, v) for (k, v) in bindings.items() if k not in kwargs)

        dependencies = self.args_to_inject(
            function=callable,
            bindings=needed,
            owner_key=self_.__class__ if self_ is not None else callable.__module__,
            )

        dependencies.update(kwargs)

        try:
            return callable(
                *((self_,) if self_ is not None else ()) + tuple(args),
                **dependencies)
        except TypeError as e:
            reraise(e, CallError(self_, callable, args, dependencies, e, self._stack))

    @private
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

        log.debug('%sProviding %r for %r', self._log_prefix, bindings, function)

        if key in self._stack:
            raise CircularDependency(
                'circular dependency detected: %s -> %s' %
                (' -> '.join(map(repr_key, self._stack)),
                repr_key(key)),
                )

        self._stack += (key,)
        try:
            for arg, key in bindings.items():
                try:
                    instance = self.get(
                        key.interface,
                        annotation=key.annotation,
                        )
                except UnsatisfiedRequirement as e:
                    if not e.args[0]:
                        e = UnsatisfiedRequirement(owner_key, e.args[1])
                    raise e
                dependencies[arg] = instance
        finally:
            self._stack = tuple(self._stack[:-1])

        return dependencies


def with_injector(*injector_args, **injector_kwargs):
    """Decorator for a method. Installs Injector object which the method
    belongs to before the decorated method is executed.

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
        scope_ = scope or getattr(provider, '__scope__', getattr(wrapper, '__scope__', None))
        provider.__binding__ = Binding(interface, annotation, provider, scope_)
        return provider

    return wrapper


def extends(interface, annotation=None, scope=None):
    raise DeprecationWarning('@extends({}|[]) is deprecated, use @provides and SequenceKey or MappingKey')


if hasattr(inspect, 'getfullargspec'):
    getfullargspec = getargspec = inspect.getfullargspec
else:
    getargspec = inspect.getargspec
    getfullargspec = None


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

    def method_wrapper(f):
        for key, value in bindings.items():
            bindings[key] = BindingKey(value, None)
        argspec = getargspec(f)
        if argspec.args and argspec.args[0] == 'self':
            @functools.wraps(f)
            def inject(self_, *args, **kwargs):
                injector = getattr(self_, '__injector__', None)
                if injector:
                    return injector.call_with_injection(
                        callable=f,
                        self_=self_,
                        args=args,
                        kwargs=kwargs
                    )
                else:
                    return f(self_, *args, **kwargs)

            # Propagate @provides bindings to wrapper function
            if hasattr(f, '__binding__'):
                inject.__binding__ = f.__binding__
        else:
            inject = f

        function_bindings = getattr(f, '__bindings__', None) or {}
        merged_bindings = dict(function_bindings, **bindings)

        f.__bindings__ = merged_bindings
        inject.__bindings__ = merged_bindings
        return inject

    def class_wrapper(cls):
        orig_init = cls.__init__

        original_keys = tuple(bindings.keys())

        for k in bindings:
            bindings[k.lstrip('_')] = bindings.pop(k)

        @inject(**bindings)
        def init(self, *args, **kwargs):
            try:
                for key in original_keys:
                    normalized_key = key.lstrip('_')
                    setattr(self, key, kwargs.pop(normalized_key))
            except KeyError as e:
                reraise(e, CallError(
                    'Keyword argument %s not found when calling %s' % (
                        normalized_key, '%s.%s' % (cls.__name__, '__init__'))))

            orig_init(self, *args, **kwargs)
        cls.__init__ = init
        return cls

    def multi_wrapper(something):
        if isinstance(something, type):
            return class_wrapper(something)
        else:
            return method_wrapper(something)

    return multi_wrapper


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


class BaseMappingKey(dict):
    """Base type for mapping binding keys."""
    def __init__(self):
        raise Exception('Instantiation of %s prohibited - it is derived from BaseMappingKey '
                        'so most likely you should bind it to something.' % (self.__class__,))


def MappingKey(name):
    """As for Key, but declares a multibind mapping."""
    try:
        if isinstance(name, unicode):
            name = name.encode('utf-8')
    except NameError:
        pass
    return type(name, (BaseMappingKey,), {})


class BaseSequenceKey(list):
    """Base type for mapping sequence keys."""
    def __init__(self):
        raise Exception('Instantiation of %s prohibited - it is derived from BaseSequenceKey '
                        'so most likely you should bind it to something.' % (self.__class__,))


def SequenceKey(name):
    """As for Key, but declares a multibind sequence."""
    try:
        if isinstance(name, unicode):
            name = name.encode('utf-8')
    except NameError:
        pass
    return type(name, (BaseSequenceKey,), {})


class ParameterizedBuilder(tuple):
    def __new__(cls, interface, **kwargs):
        kwargs = tuple(sorted(kwargs.items()))
        return super(ParameterizedBuilder, cls).__new__(cls, (interface, kwargs))

    @property
    def interface(self):
        return self[0]

    @property
    def kwargs(self):
        return dict(self[1])


class AssistedBuilder(namedtuple('_AssistedBuilder', 'interface cls callable')):
    def __new__(cls_, interface=None, cls=None, callable=None):
        if len([x for x in (interface, cls, callable) if x is not None]) != 1:
            raise Error('You need to specify exactly one of the following '
                        'arguments: interface, cls or callable')

        return super(AssistedBuilder, cls_).__new__(
            cls_, interface, cls, callable)


class AssistedBuilderImplementation(namedtuple(
        '_AssistedBuilderImplementation', 'injector interface cls callable')):

    def build(self, **kwargs):
        if self.interface is not None:
            return self.build_interface(**kwargs)
        elif self.cls is not None:
            return self.build_class(self.cls, **kwargs)
        else:
            return self.build_callable(**kwargs)

    def build_class(self, cls, **kwargs):
        return self.injector.create_object(cls, additional_kwargs=kwargs)

    def build_interface(self, **kwargs):
        key = BindingKey(self.interface, None)
        binder = self.injector.binder
        binding = binder.get_binding(None, key)
        provider = binding.provider
        if not isinstance(provider, ClassProvider):
            raise Error(
                'Assisted interface building works only with ClassProviders, '
                'got %r for %r' % (provider, self.interface))

        return self.build_class(provider._cls, **kwargs)

    def build_callable(self, **kwargs):
        return self.injector.call_with_injection(
            callable=self.callable,
            self_=None,
            kwargs=kwargs
        )


def _describe(c):
    if hasattr(c, '__name__'):
        return c.__name__
    if type(c) in (tuple, list):
        return '[%s]' % c[0].__name__
    return str(c)
