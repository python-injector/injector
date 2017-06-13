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

:copyright: (c) 2012 by Alec Thomas
:license: BSD
"""

import functools
import inspect
import itertools
import logging
import sys
import threading
import types
import warnings
from abc import ABCMeta, abstractmethod
from collections import namedtuple
from typing import Any, Generic, get_type_hints, TypeVar, Union

TYPING353 = hasattr(Union[str, int], '__origin__')


__author__ = 'Alec Thomas <alec@swapoff.org>'
__version__ = '0.13.0'
__version_tag__ = ''

log = logging.getLogger('injector')
log.addHandler(logging.NullHandler())

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


def reraise(original, exception, maximum_frames=1):
    prev_cls, prev, tb = sys.exc_info()
    frames = inspect.getinnerframes(tb)
    if len(frames) > maximum_frames:
        exception = original
    raise exception.with_traceback(tb)


class Error(Exception):
    """Base exception."""


class UnsatisfiedRequirement(Error):
    """Requirement could not be satisfied."""

    def __str__(self):
        on = '%s has an ' % _describe(self.args[0]) if self.args[0] else ''
        return '%sunsatisfied requirement on %s' % (
            on, _describe(self.args[1].interface),)


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


class Provider:
    """Provides class instances."""

    __metaclass__ = ABCMeta

    @abstractmethod
    def get(self, injector):
        raise NotImplementedError


class ClassProvider(Provider):
    """Provides instances from a given class, created using an Injector."""

    def __init__(self, cls):
        self._cls = cls

    def get(self, injector):
        return injector.create_object(self._cls)


class CallableProvider(Provider):
    """Provides something using a callable.

    The callable is called every time new value is requested from the provider.

    ::

        >>> key = Key('key')
        >>> def factory():
        ...     print('providing')
        ...     return []
        ...
        >>> def configure(binder):
        ...     binder.bind(key, to=CallableProvider(factory))
        ...
        >>> injector = Injector(configure)
        >>> injector.get(key) is injector.get(key)
        providing
        providing
        False
        """

    def __init__(self, callable):
        self._callable = callable

    def get(self, injector):
        return injector.call_with_injection(self._callable)

    def __repr__(self):
        return '%s(%r)' % (type(self).__name__, self._callable)


class InstanceProvider(Provider):
    """Provide a specific instance.

    ::

        >>> my_list = Key('my_list')
        >>> def configure(binder):
        ...     binder.bind(my_list, to=InstanceProvider([]))
        ...
        >>> injector = Injector(configure)
        >>> injector.get(my_list) is injector.get(my_list)
        True
        >>> injector.get(my_list).append('x')
        >>> injector.get(my_list)
        ['x']
    """

    def __init__(self, instance):
        self._instance = instance

    def get(self, injector):
        return self._instance

    def __repr__(self):
        return '%s(%r)' % (type(self).__name__, self._instance)



@private
class ListOfProviders(Provider):
    """Provide a list of instances via other Providers."""

    def __init__(self):
        self._providers = []

    def append(self, provider):
        self._providers.append(provider)

    def get(self, injector):
        return [provider.get(injector) for provider in self._providers]

    def __repr__(self):
        return '%s(%r)' % (type(self).__name__, self._providers)


class MultiBindProvider(ListOfProviders):
    """Used by :meth:`Binder.multibind` to flatten results of providers that
    return sequences."""

    def get(self, injector):
        return [i for provider in self._providers for i in provider.get(injector)]


class MapBindProvider(ListOfProviders):
    """A provider for map bindings."""

    def get(self, injector):
        map = {}
        for provider in self._providers:
            map.update(provider.get(injector))
        return map


@private
class BindingKey(tuple):
    """A key mapping to a Binding."""

    def __new__(cls, what):
        if isinstance(what, list):
            if len(what) != 1:
                raise Error('list bindings must have a single interface '
                            'element')
            what = (list, BindingKey(what[0]))
        elif isinstance(what, dict):
            if len(what) != 1:
                raise Error('dictionary bindings must have a single interface '
                            'key and value')
            what = (dict, BindingKey(list(what.items())[0]))
        return tuple.__new__(cls, (what,))

    @property
    def interface(self):
        return self[0]


_BindingBase = namedtuple('_BindingBase', 'interface provider scope')


@private
class Binding(_BindingBase):
    """A binding from an (interface,) to a provider in a scope."""


class Binder:
    """Bind interfaces to implementations.

    .. note:: This class is instantiated internally for you and there's no need
        to instantiate it on your own.
    """

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

    def bind(self, interface, to=None, scope=None):
        """Bind an interface to an implementation.

        :param interface: Interface or :func:`Key` to bind.
        :param to: Instance or class to bind to, or an explicit
             :class:`Provider` subclass.
        :param scope: Optional :class:`Scope` in which to bind.
        """
        if type(interface) is type and issubclass(interface, (BaseMappingKey, BaseSequenceKey)):
            return self.multibind(interface, to, scope=scope)
        key = BindingKey(interface)
        self._bindings[key] = \
            self.create_binding(interface, to, scope)

    def bind_scope(self, scope):
        """Bind a Scope.

        :param scope: Scope class.
        """
        self.bind(scope, to=scope(self.injector))

    def multibind(self, interface, to, scope=None):
        """Creates or extends a multi-binding.

        A multi-binding maps from a key to a sequence, where each element in
        the sequence is provided separately.

        :param interface: :func:`MappingKey` or :func:`SequenceKey` to bind to.
        :param to: Instance, class to bind to, or an explicit :class:`Provider`
                subclass. Must provide a sequence.
        :param scope: Optional Scope in which to bind.
        """
        key = BindingKey(interface)
        if key not in self._bindings:
            if (
                    isinstance(interface, dict) or
                    isinstance(interface, type) and issubclass(interface, dict)):
                provider = MapBindProvider()
            else:
                provider = MultiBindProvider()
            binding = self.create_binding(interface, provider, scope)
            self._bindings[key] = binding
        else:
            binding = self._bindings[key]
            provider = binding.provider
            assert isinstance(provider, ListOfProviders)
        provider.append(self.provider_for(key.interface, to))

    def install(self, module):
        """Install a module into this binder.

        In this context the module is one of the following:

        * function taking the :class:`Binder` as it's only parameter

          ::

            def configure(binder):
                bind(str, to='s')

            binder.install(configure)

        * instance of :class:`Module` (instance of it's subclass counts)

          ::

            class MyModule(Module):
                def configure(self, binder):
                    binder.bind(str, to='s')

            binder.install(MyModule())

        * subclass of :class:`Module` - the subclass needs to be instantiable so if it
          expects any parameters they need to be injected

          ::

            binder.install(MyModule)
        """
        if (
            hasattr(module, '__bindings__') or
            hasattr(getattr(module, 'configure', None), '__bindings__') or
            hasattr(getattr(module, '__init__', None), '__bindings__')
        ):
            warnings.warn(
                'Injector Modules (ie. %s) constructors and their configure methods should '
                'not have injectable parameters. This can result in non-deterministic '
                'initialization. If you need injectable objects in order to provide something '
                ' you can use @provider-decorated methods. \n'
                ' This feature will be removed in next Injector release.' %
                module.__name__ if hasattr(module, '__name__') else module.__class__.__name__,
                RuntimeWarning,
                stacklevel=3,
            )
        if type(module) is type and issubclass(module, Module):
            instance = self.injector.create_object(module)
            instance(self)
        else:
            self.injector.call_with_injection(
                callable=module,
                self_=None,
                args=(self,),
            )

    def create_binding(self, interface, to=None, scope=None):
        provider = self.provider_for(interface, to)
        scope = scope or getattr(to or interface, '__scope__', NoScope)
        if isinstance(scope, ScopeDecorator):
            scope = scope.scope
        return Binding(interface, provider, scope)

    def provider_for(self, interface, to=None):
        if interface is Any:
            raise TypeError('Injecting Any is not supported')
        elif _is_specialization(interface, ProviderOf):
            (target,) = interface.__args__
            if to is not None:
                raise Exception('ProviderOf cannot be bound to anything')
            return InstanceProvider(ProviderOf(self.injector, target))
        elif isinstance(to, Provider):
            return to
        elif isinstance(interface, Provider):
            return interface
        elif isinstance(to, (types.FunctionType, types.LambdaType,
                             types.MethodType, types.BuiltinFunctionType,
                             types.BuiltinMethodType)):
            return CallableProvider(to)
        elif issubclass(type(to), type):
            return ClassProvider(to)
        elif isinstance(interface, BoundKey):
            def proxy(**kwargs):
                return interface.interface(**kwargs)

            proxy.__annotations__ = interface.kwargs.copy()
            return CallableProvider(inject(proxy))
        elif _is_specialization(interface, AssistedBuilder):
            (target,) = interface.__args__
            builder = interface(self.injector, target)
            return InstanceProvider(builder)
        elif (
            isinstance(interface, (tuple, type)) and
            interface is not Any and
            isinstance(to, interface)
        ):
            return InstanceProvider(to)
        elif issubclass(type(interface), type) or isinstance(interface, (tuple, list)):
            if to is not None:
                return InstanceProvider(to)
            return ClassProvider(interface)

        elif hasattr(interface, '__call__'):
            raise TypeError('Injecting partially applied functions is no longer supported.')
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
            # The special interface is added here so that requesting a special
            # interface with auto_bind disabled works
            if self._auto_bind or self._is_special_interface(key.interface):
                binding = self.create_binding(key.interface)
                self._bindings[key] = binding
                return binding
            raise UnsatisfiedRequirement(cls, key)

    def _is_special_interface(self, interface):
        # "Special" interfaces are ones that you cannot bind yourself but
        # you can request them (for example you cannot bind ProviderOf(SomeClass)
        # to anything but you can inject ProviderOf(SomeClass) just fine
        return any(
            _is_specialization(interface, cls)
            for cls in [AssistedBuilder, ProviderOf]
        )


if TYPING353:
    def _is_specialization(cls, generic_class):
        # Starting with typing 3.5.3/Python 3.6 it is no longer necessarily true that
        # issubclass(SomeGeneric[X], SomeGeneric) so we need some other way to
        # determine whether a particular object is a generic class with type parameters
        # provided. Fortunately there seems to be __origin__ attribute that's useful here.
        if not hasattr(cls, '__origin__'):
            return False
        origin = cls.__origin__
        if not inspect.isclass(generic_class):
            generic_class = type(generic_class)
        if not inspect.isclass(origin):
            origin = type(origin)
        # __origin__ is generic_class is a special case to handle Union as
        # Union cannot be used in issubclass() check (it raises an exception
        # by design).
        return origin is generic_class or issubclass(origin, generic_class)

else:
    # To maintain compatibility we fall back to an issubclass check.
    def _is_specialization(cls, generic_class):
        return isinstance(cls, type) and cls is not Any and issubclass(cls, generic_class)


class Scope:
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


class ScopeDecorator:
    def __init__(self, scope):
        self.scope = scope

    def __call__(self, cls):
        cls.__scope__ = self.scope
        binding = getattr(cls, '__binding__', None)
        if binding:
            new_binding = Binding(interface=binding.interface,
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

    >>> class A: pass
    >>> injector = Injector()
    >>> provider = ClassProvider(A)
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
            provider = InstanceProvider(provider.get(self.injector))
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
            provider = InstanceProvider(provider.get(self.injector))
            setattr(self._locals, repr(key), provider)
            return provider


threadlocal = ScopeDecorator(ThreadLocalScope)


class Module:
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
                    scope=binding.scope,
                )
        self.configure(binder)

    def configure(self, binder):
        """Override to configure bindings."""


class Injector:
    """
    :param modules: Optional - a configuration module or iterable of configuration modules.
        Each module will be installed in current :class:`Binder` using :meth:`Binder.install`.

        Consult :meth:`Binder.install` documentation for the details.

    :param auto_bind: Whether to automatically bind missing types.
    :param parent: Parent injector.

    If you use Python 3 you can make Injector use constructor parameter annotations to
    determine class dependencies. The following code::

        class B:
            @inject
            def __init__(self, a: A):
                self.a = a

    can now be written as::

        class B:
            def __init__(self, a:A):
                self.a = a

    .. versionadded:: 0.7.5
        ``use_annotations`` parameter

    .. versionchanged:: 0.13.0
        ``use_annotations`` parameter is removed
    """

    def __init__(self, modules=None, auto_bind=True, parent=None):
        # Stack of keys currently being injected. Used to detect circular
        # dependencies.
        self._stack = ()

        self.parent = parent

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

    def get(self, interface, scope=None):
        """Get an instance of the given interface.

        .. note::

            Although this method is part of :class:`Injector`'s public interface
            it's meant to be used in limited set of circumstances.

            For example, to create some kind of root object (application object)
            of your application (note that only one `get` call is needed,
            inside the `Application` class and any of its dependencies
            :func:`inject` can and should be used):

            .. code-block:: python

                class Application:

                    @inject
                    def __init__(self, dep1: Dep1, dep2: Dep2):
                        self.dep1 = dep1
                        self.dep2 = dep2

                    def run(self):
                        self.dep1.something()

                injector = Injector(configuration)
                application = injector.get(Application)
                application.run()

        :param interface: Interface whose implementation we want.
        :param scope: Class of the Scope in which to resolve.
        :returns: An implementation of interface.
        """
        key = BindingKey(interface)
        binding = self.binder.get_binding(None, key)
        scope = scope or binding.scope
        if isinstance(scope, ScopeDecorator):
            scope = scope.scope
        # Fetch the corresponding Scope instance from the Binder.
        scope_key = BindingKey(scope)
        try:
            scope_binding = self.binder.get_binding(None, scope_key)
            scope_instance = scope_binding.provider.get(self)
        except UnsatisfiedRequirement as e:
            raise Error('%s; scopes must be explicitly bound '
                        'with Binder.bind_scope(scope_cls)' % e)

        log.debug('%sInjector.get(%r, scope=%r) using %r',
                  self._log_prefix, interface, scope, binding.provider)
        result = scope_instance.get(key, binding.provider).get(self)
        log.debug('%s -> %r', self._log_prefix, result)
        return result

    def create_child_injector(self, *args, **kwargs):
        return Injector(*args, parent=self, **kwargs)

    def create_object(self, cls, additional_kwargs=None):
        """Create a new instance, satisfying any dependencies on cls."""
        additional_kwargs = additional_kwargs or {}
        log.debug('%sCreating %r object with %r', self._log_prefix, cls, additional_kwargs)

        try:
            instance = cls.__new__(cls)
        except TypeError as e:
            reraise(e, CallError(
                cls,
                getattr(cls.__new__, '__func__', cls.__new__),
                (), {}, e, self._stack,),
                maximum_frames=2)
        try:
            self.install_into(instance)
            installed = True
        except AttributeError:
            installed = False
            if hasattr(instance, '__slots__'):
                raise Error('Can\'t create an instance of type %r due to presence of __slots__, '
                            'remove __slots__ to fix that' % (cls,))

            # Else do nothing - some builtin types can not be modified.
        try:
            try:
                init = cls.__init__
                init(instance, **additional_kwargs)
            except TypeError as e:
                # The reason why getattr() fallback is used here is that
                # __init__.__func__ apparently doesn't exist for Key-type objects
                reraise(e, CallError(
                    instance,
                    getattr(instance.__init__, '__func__', instance.__init__),
                    (), additional_kwargs, e, self._stack,)
                )
            return instance
        finally:
            if installed:
                self._uninstall_from(instance)

    def install_into(self, instance):
        """Put injector reference in given object.

        This method has, in general, two applications:

        * Injector internal use (not documented here)
        * Making it possible to inject into methods of an object that wasn't created
            using Injector. Usually it's because you either don't control the instantiation
            process, it'd generate unnecessary boilerplate or it's just easier this way.

            For example, in application main script::

                from injector import Injector

                class Main:
                    def __init__(self):
                        def configure(binder):
                            binder.bind(str, to='Hello!')

                        injector = Injector(configure)
                        injector.install_into(self)

                    @inject
                    def run(self, s: str):
                        print(s)

                if __name__ == '__main__':
                    main = Main()
                    main.run()


        .. note:: You don't need to use this method if the object is created using `Injector`.

        .. warning:: Using `install_into` to install :class:`Injector` reference into an object
            created by different :class:`Injector` instance may very likely result in unexpected
            behaviour of that object immediately or in the future.

        """
        instance.__injector__ = self

    def _uninstall_from(self, instance):
        del instance.__injector__

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
        def _get_callable_bindings(callable):
            if not hasattr(callable, '__bindings__'):
                return {}

            if callable.__bindings__ == 'deferred':
                callable.__read_and_store_bindings__(_infer_injected_bindings(callable))
                del callable.__read_and_store_bindings__
            return callable.__bindings__

        bindings = _get_callable_bindings(callable)
        noninjectables = getattr(callable, '__noninjectables__', set())
        needed = dict(
            (k, v) for (k, v) in bindings.items()
            if k not in kwargs and k not in noninjectables
        )

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

        key = (owner_key, function, tuple(sorted(bindings.items())))

        def repr_key(k):
            owner_key, function, bindings = k
            return '%s.%s(injecting %s)' % (tuple(map(_describe, k[:2])) + (dict(k[2]),))

        log.debug('%sProviding %r for %r', self._log_prefix, bindings, function)

        if key in self._stack:
            raise CircularDependency(
                'circular dependency detected: %s -> %s' %
                (' -> '.join(map(repr_key, self._stack)), repr_key(key))
            )

        self._stack += (key,)
        try:
            for arg, key in bindings.items():
                try:
                    instance = self.get(key.interface)
                except UnsatisfiedRequirement as e:
                    if not e.args[0]:
                        e = UnsatisfiedRequirement(owner_key, e.args[1])
                    raise e
                dependencies[arg] = instance
        finally:
            self._stack = tuple(self._stack[:-1])

        return dependencies


class _BindingNotYetAvailable(Exception):
    pass


def _infer_injected_bindings(callable):
    spec = inspect.getfullargspec(callable)
    try:
        bindings = get_type_hints(callable)
    except NameError as e:
        raise _BindingNotYetAvailable(e)

    # We don't care about the return value annotation as it doesn't matter
    # injection-wise.
    bindings.pop('return', None)

    # variadic arguments aren't supported at the moment (this may change
    # in the future if someone has a good idea how to utilize them)
    bindings.pop(spec.varargs, None)
    bindings.pop(spec.varkw, None)

    for k, v in list(bindings.items()):
        if _is_specialization(v, Union):
            # We don't treat Optional parameters in any special way at the moment.
            if TYPING353:
                union_members = v.__args__
            else:
                union_members = v.__union_params__
            new_members = tuple(set(union_members) - {type(None)})
            new_union = Union[new_members]
            bindings[k] = new_union

    return bindings


def with_injector(*injector_args, **injector_kwargs):
    """Decorator for a method. Installs Injector object which the method
    belongs to before the decorated method is executed.

    Parameters are the same as for :class:`Injector` constructor.
    """
    def wrapper(f):
        @functools.wraps(f)
        def setup(self_, *args, **kwargs):
            injector = Injector(*injector_args, **injector_kwargs)
            injector.install_into(self_)
            return f(self_, *args, **kwargs)

        return setup

    return wrapper


def provider(function):
    """Decorator for :class:`Module` methods, registering a provider of a type.

    >>> class MyModule(Module):
    ...   @provider
    ...   def provide_name(self) -> str:
    ...       return 'Bob'

    @provider-decoration implies @inject so you can omit it and things will
    work just the same:

    >>> class MyModule2(Module):
    ...     def configure(self, binder):
    ...         binder.bind(int, to=654)
    ...
    ...     @provider
    ...     def provide_str(self, i: int) -> str:
    ...         return str(i)
    ...
    >>> injector = Injector(MyModule2)
    >>> injector.get(str)
    '654'

    .. note:: This function works only on Python 3
    """
    scope_ = getattr(function, '__scope__', None)
    annotations = inspect.getfullargspec(function).annotations
    return_type = annotations['return']
    function.__binding__ = Binding(return_type, inject(function), scope_)
    return function


def inject(function=None, **bindings):
    """Decorator declaring parameters to be injected.

    eg.

    >>> Sizes = Key('sizes')
    >>> Names = Key('names')
    >>>
    >>> class A:
    ...     @inject
    ...     def __init__(self, number: int, name: str, sizes: Sizes):
    ...         print([number, name, sizes])
    ...
    >>> def configure(binder):
    ...     binder.bind(A)
    ...     binder.bind(int, to=123)
    ...     binder.bind(str, to='Bob')
    ...     binder.bind(Sizes, to=[1, 2, 3])

    Use the Injector to get a new instance of A:

    >>> a = Injector(configure).get(A)
    [123, 'Bob', [1, 2, 3]]
    """
    if bindings or not function:
        raise AssertionError('Wrong use of the inject decorator, please consult the documentation')

    try:
        bindings = _infer_injected_bindings(function)
    except _BindingNotYetAvailable:
        bindings = 'deferred'
    return method_wrapper(function, bindings)


def noninjectable(*args):
    """Mark some parameters as not injectable.

    This serves as documentation for people reading the code and will prevent
    Injector from ever attempting to provide the parameters.

    For example:

    >>> class Service:
    ...    pass
    ...
    >>> class SomeClass:
    ...     @inject
    ...     @noninjectable('user_id')
    ...     def __init__(self, service: Service, user_id: int):
    ...         # ...
    ...         pass

    :func:`noninjectable` decorations can be stacked on top of
    each other and the order in which a function is decorated with
    :func:`inject` and :func:`noninjectable`
    doesn't matter.
    """
    def decorator(function):
        existing = getattr(function, '__noninjectables__', set())
        merged = existing | set(args)
        function.__noninjectables__ = merged
        return function
    return decorator


def method_wrapper(f, bindings):
    argspec = inspect.getfullargspec(f)
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

        # Propagate @provider bindings to wrapper function
        if hasattr(f, '__binding__'):
            inject.__binding__ = f.__binding__
    else:
        inject = f

    def read_and_store_bindings(bindings):
        for key, value in bindings.items():
            bindings[key] = BindingKey(value)
        function_bindings = getattr(f, '__bindings__', None) or {}
        if function_bindings == 'deferred':
            function_bindings = {}
        merged_bindings = dict(function_bindings, **bindings)

        f.__bindings__ = merged_bindings
        inject.__bindings__ = merged_bindings

    if isinstance(bindings, dict):
        read_and_store_bindings(bindings)
    else:
        f.__bindings__ = 'deferred'
        f.__read_and_store_bindings__ = read_and_store_bindings
    return inject


@private
class BaseKey:
    """Base type for binding keys."""

    def __init__(self):
        raise Exception('Instantiation of %s prohibited - it is derived from BaseKey '
                        'so most likely you should bind it to something.' % (self.__class__,))


def Key(name):
    """Create a new type key.

    >>> Age = Key('Age')
    >>> def configure(binder):
    ...   binder.bind(Age, to=90)
    >>> Injector(configure).get(Age)
    90
    """
    return type(name, (BaseKey,), {})


@private
class BaseMappingKey(dict):
    """Base type for mapping binding keys."""
    def __init__(self):
        raise Exception('Instantiation of %s prohibited - it is derived from BaseMappingKey '
                        'so most likely you should bind it to something.' % (self.__class__,))


def MappingKey(name):
    """As for Key, but declares a multibind mapping."""
    return type(name, (BaseMappingKey,), {})


@private
class BaseSequenceKey(list):
    """Base type for mapping sequence keys."""
    def __init__(self):
        raise Exception('Instantiation of %s prohibited - it is derived from BaseSequenceKey '
                        'so most likely you should bind it to something.' % (self.__class__,))


def SequenceKey(name):
    """As for Key, but declares a multibind sequence."""
    return type(name, (BaseSequenceKey,), {})


class BoundKey(tuple):
    """A BoundKey provides a key to a type with pre-injected arguments.

    >>> class A:
    ...   def __init__(self, a, b):
    ...     self.a = a
    ...     self.b = b
    >>> InjectedA = BoundKey(A, a=InstanceProvider(1), b=InstanceProvider(2))
    >>> injector = Injector()
    >>> a = injector.get(InjectedA)
    >>> a.a, a.b
    (1, 2)
    """

    def __new__(cls, interface, **kwargs):
        kwargs = tuple(sorted(kwargs.items()))
        return super(BoundKey, cls).__new__(cls, (interface, kwargs))

    @property
    def interface(self):
        return self[0]

    @property
    def kwargs(self):
        return dict(self[1])


T = TypeVar('T')


class AssistedBuilder(Generic[T]):

    def __init__(self, injector, target):
        self._injector = injector
        self._target = target

    def build(self, **kwargs):
        key = BindingKey(self._target)
        binder = self._injector.binder
        binding = binder.get_binding(None, key)
        provider = binding.provider
        if not isinstance(provider, ClassProvider):
            raise Error(
                'Assisted interface building works only with ClassProviders, '
                'got %r for %r' % (provider, self.interface))

        return self._build_class(provider._cls, **kwargs)

    def _build_class(self, cls, **kwargs):
        return self._injector.create_object(cls, additional_kwargs=kwargs)


class ClassAssistedBuilder(AssistedBuilder[T]):
    def build(self, **kwargs):
        return self._build_class(self._target, **kwargs)


def _describe(c):
    if hasattr(c, '__name__'):
        return c.__name__
    if type(c) in (tuple, list):
        return '[%s]' % c[0].__name__
    return str(c)


class ProviderOf(Generic[T]):
    """Can be used to get a provider of an interface, for example:

        >>> def provide_int():
        ...     print('providing')
        ...     return 123
        >>>
        >>> def configure(binder):
        ...     binder.bind(int, to=provide_int)
        >>>
        >>> injector = Injector(configure)
        >>> provider = injector.get(ProviderOf[int])
        >>> value = provider.get()
        providing
        >>> value
        123
    """

    def __init__(self, injector, interface):
        self._injector = injector
        self._interface = interface

    def __repr__(self):
        return '%s(%r, %r)' % (
            type(self).__name__, self._injector, self._interface)

    def get(self):
        """Get an implementation for the specified interface."""
        return self._injector.get(self._interface)


def is_decorated_with_inject(function):
    """See if given callable is declared to want some dependencies injected.

    Example use:

    >>> def fun(i: int) -> str:
    ...     return str(i)

    >>> is_decorated_with_inject(fun)
    False
    >>>
    >>> @inject
    ... def fun2(i: int) -> str:
    ...     return str(i)

    >>> is_decorated_with_inject(fun2)
    True
    """
    return hasattr(function, '__bindings__')
