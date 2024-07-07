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
from abc import ABCMeta, abstractmethod
from collections import namedtuple
from typing import (
    Any,
    Callable,
    cast,
    Dict,
    Generic,
    Iterable,
    List,
    Optional,
    overload,
    Set,
    Tuple,
    Type,
    TypeVar,
    TYPE_CHECKING,
    Union,
)

try:
    from typing import NoReturn
except ImportError:
    from typing_extensions import NoReturn

# This is a messy, type-wise, because we not only have two potentially conflicting imports here
# The easiest way to make mypy happy here is to tell it the versions from typing_extensions are
# canonical. Since this typing_extensions import is only for mypy it'll work even without
# typing_extensions actually installed so all's good.
if TYPE_CHECKING:
    from typing_extensions import _AnnotatedAlias, Annotated, get_type_hints
else:
    # Ignoring errors here as typing_extensions stub doesn't know about those things yet
    try:
        from typing import _AnnotatedAlias, Annotated, get_type_hints
    except ImportError:
        from typing_extensions import _AnnotatedAlias, Annotated, get_type_hints


__author__ = 'Alec Thomas <alec@swapoff.org>'
__version__ = '0.22.0'
__version_tag__ = ''

log = logging.getLogger('injector')
log.addHandler(logging.NullHandler())

if log.level == logging.NOTSET:
    log.setLevel(logging.WARN)

T = TypeVar('T')
K = TypeVar('K')
V = TypeVar('V')


def private(something: T) -> T:
    something.__private__ = True  # type: ignore
    return something


CallableT = TypeVar('CallableT', bound=Callable)


def synchronized(lock: threading.RLock) -> Callable[[CallableT], CallableT]:
    def outside_wrapper(function: CallableT) -> CallableT:
        @functools.wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with lock:
                return function(*args, **kwargs)

        return cast(CallableT, wrapper)

    return outside_wrapper


lock = threading.RLock()


_inject_marker = object()
_noinject_marker = object()

InjectT = TypeVar('InjectT')
Inject = Annotated[InjectT, _inject_marker]
"""An experimental way to declare injectable dependencies utilizing a `PEP 593`_ implementation
in Python 3.9 and backported to Python 3.7+ in `typing_extensions`.

Those two declarations are equivalent::

    @inject
    def fun(t: SomeType) -> None:
        pass

    def fun(t: Inject[SomeType]) -> None:
        pass

The advantage over using :func:`inject` is that if you have some noninjectable parameters
it may be easier to spot what are they. Those two are equivalent::

    @inject
    @noninjectable('s')
    def fun(t: SomeType, s: SomeOtherType) -> None:
        pass

    def fun(t: Inject[SomeType], s: SomeOtherType) -> None:
        pass

.. seealso::

    Function :func:`get_bindings`
        A way to inspect how various injection declarations interact with each other.

.. versionadded:: 0.18.0
.. note:: Requires Python 3.7+.
.. note::

    If you're using mypy you need the version 0.750 or newer to fully type-check code using this
    construct.

.. _PEP 593: https://www.python.org/dev/peps/pep-0593/
.. _typing_extensions: https://pypi.org/project/typing-extensions/
"""

NoInject = Annotated[InjectT, _noinject_marker]
"""An experimental way to declare noninjectable dependencies utilizing a `PEP 593`_ implementation
in Python 3.9 and backported to Python 3.7+ in `typing_extensions`.

Since :func:`inject` declares all function's parameters to be injectable there needs to be a way
to opt out of it. This has been provided by :func:`noninjectable` but `noninjectable` suffers from
two issues:

* You need to repeat the parameter name
* The declaration may be relatively distance in space from the actual parameter declaration, thus
  hindering readability

`NoInject` solves both of those concerns, for example (those two declarations are equivalent)::

    @inject
    @noninjectable('b')
    def fun(a: TypeA, b: TypeB) -> None:
        pass

    @inject
    def fun(a: TypeA, b: NoInject[TypeB]) -> None:
        pass

.. seealso::

    Function :func:`get_bindings`
        A way to inspect how various injection declarations interact with each other.

.. versionadded:: 0.18.0
.. note:: Requires Python 3.7+.
.. note::

    If you're using mypy you need the version 0.750 or newer to fully type-check code using this
    construct.

.. _PEP 593: https://www.python.org/dev/peps/pep-0593/
.. _typing_extensions: https://pypi.org/project/typing-extensions/
"""


def reraise(original: Exception, exception: Exception, maximum_frames: int = 1) -> NoReturn:
    prev_cls, prev, tb = sys.exc_info()
    frames = inspect.getinnerframes(cast(types.TracebackType, tb))
    if len(frames) > maximum_frames:
        exception = original
    raise exception.with_traceback(tb)


class Error(Exception):
    """Base exception."""


class UnsatisfiedRequirement(Error):
    """Requirement could not be satisfied."""

    def __init__(self, owner: Optional[object], interface: type) -> None:
        super().__init__(owner, interface)
        self.owner = owner
        self.interface = interface

    def __str__(self) -> str:
        on = '%s has an ' % _describe(self.owner) if self.owner else ''
        return '%sunsatisfied requirement on %s' % (on, _describe(self.interface))


class CallError(Error):
    """Call to callable object fails."""

    def __str__(self) -> str:
        if len(self.args) == 1:
            return self.args[0]

        instance, method, args, kwargs, original_error, stack = self.args
        cls = instance.__class__.__name__ if instance is not None else ''

        full_method = '.'.join((cls, method.__name__)).strip('.')

        parameters = ', '.join(
            itertools.chain(
                (repr(arg) for arg in args), ('%s=%r' % (key, value) for (key, value) in kwargs.items())
            )
        )
        return 'Call to %s(%s) failed: %s (injection stack: %r)' % (
            full_method,
            parameters,
            original_error,
            [level[0] for level in stack],
        )


class CircularDependency(Error):
    """Circular dependency detected."""


class UnknownProvider(Error):
    """Tried to bind to a type whose provider couldn't be determined."""


class UnknownArgument(Error):
    """Tried to mark an unknown argument as noninjectable."""


class Provider(Generic[T]):
    """Provides class instances."""

    __metaclass__ = ABCMeta

    @abstractmethod
    def get(self, injector: 'Injector') -> T:
        raise NotImplementedError  # pragma: no cover


class ClassProvider(Provider, Generic[T]):
    """Provides instances from a given class, created using an Injector."""

    def __init__(self, cls: Type[T]) -> None:
        self._cls = cls

    def get(self, injector: 'Injector') -> T:
        return injector.create_object(self._cls)


class CallableProvider(Provider, Generic[T]):
    """Provides something using a callable.

    The callable is called every time new value is requested from the provider.

    There's no need to explicitly use :func:`inject` or :data:`Inject` with the callable as it's
    assumed that, if the callable has annotated parameters, they're meant to be provided
    automatically. It wouldn't make sense any other way, as there's no mechanism to provide
    parameters to the callable at a later time, so either they'll be injected or there'll be
    a `CallError`.

    ::

        >>> class MyClass:
        ...     def __init__(self, value: int) -> None:
        ...         self.value = value
        ...
        >>> def factory():
        ...     print('providing')
        ...     return MyClass(42)
        ...
        >>> def configure(binder):
        ...     binder.bind(MyClass, to=CallableProvider(factory))
        ...
        >>> injector = Injector(configure)
        >>> injector.get(MyClass) is injector.get(MyClass)
        providing
        providing
        False
    """

    def __init__(self, callable: Callable[..., T]):
        self._callable = callable

    def get(self, injector: 'Injector') -> T:
        return injector.call_with_injection(self._callable)

    def __repr__(self) -> str:
        return '%s(%r)' % (type(self).__name__, self._callable)


class InstanceProvider(Provider, Generic[T]):
    """Provide a specific instance.

    ::

        >>> class MyType:
        ...     def __init__(self):
        ...         self.contents = []
        >>> def configure(binder):
        ...     binder.bind(MyType, to=InstanceProvider(MyType()))
        ...
        >>> injector = Injector(configure)
        >>> injector.get(MyType) is injector.get(MyType)
        True
        >>> injector.get(MyType).contents.append('x')
        >>> injector.get(MyType).contents
        ['x']
    """

    def __init__(self, instance: T) -> None:
        self._instance = instance

    def get(self, injector: 'Injector') -> T:
        return self._instance

    def __repr__(self) -> str:
        return '%s(%r)' % (type(self).__name__, self._instance)


@private
class ListOfProviders(Provider, Generic[T]):
    """Provide a list of instances via other Providers."""

    _providers: List[Provider[T]]

    def __init__(self) -> None:
        self._providers = []

    def append(self, provider: Provider[T]) -> None:
        self._providers.append(provider)

    def __repr__(self) -> str:
        return '%s(%r)' % (type(self).__name__, self._providers)


class MultiBindProvider(ListOfProviders[List[T]]):
    """Used by :meth:`Binder.multibind` to flatten results of providers that
    return sequences."""

    def get(self, injector: 'Injector') -> List[T]:
        return [i for provider in self._providers for i in provider.get(injector)]


class MapBindProvider(ListOfProviders[Dict[str, T]]):
    """A provider for map bindings."""

    def get(self, injector: 'Injector') -> Dict[str, T]:
        map: Dict[str, T] = {}
        for provider in self._providers:
            map.update(provider.get(injector))
        return map


_BindingBase = namedtuple('_BindingBase', 'interface provider scope')


@private
class Binding(_BindingBase):
    """A binding from an (interface,) to a provider in a scope."""

    def is_multibinding(self) -> bool:
        return _get_origin(_punch_through_alias(self.interface)) in {dict, list}


@private
class ImplicitBinding(Binding):
    """A binding that was created implicitly by auto-binding."""

    pass


_InstallableModuleType = Union[Callable[['Binder'], None], 'Module', Type['Module']]


class Binder:
    """Bind interfaces to implementations.

    .. note:: This class is instantiated internally for you and there's no need
        to instantiate it on your own.
    """

    _bindings: Dict[type, Binding]

    @private
    def __init__(
        self, injector: 'Injector', auto_bind: bool = True, parent: Optional['Binder'] = None
    ) -> None:
        """Create a new Binder.

        :param injector: Injector we are binding for.
        :param auto_bind: Whether to automatically bind missing types.
        :param parent: Parent binder.
        """
        self.injector = injector
        self._auto_bind = auto_bind
        self._bindings = {}
        self.parent = parent

    def bind(
        self,
        interface: Type[T],
        to: Union[None, T, Callable[..., T], Provider[T]] = None,
        scope: Union[None, Type['Scope'], 'ScopeDecorator'] = None,
    ) -> None:
        """Bind an interface to an implementation.

        Binding `T` to an instance of `T` like

        ::

            binder.bind(A, to=A('some', 'thing'))

        is, for convenience, a shortcut for

        ::

            binder.bind(A, to=InstanceProvider(A('some', 'thing'))).

        Likewise, binding to a callable like

        ::

            binder.bind(A, to=some_callable)

        is a shortcut for

        ::

            binder.bind(A, to=CallableProvider(some_callable))

        and, as such, if `some_callable` there has any annotated parameters they'll be provided
        automatically without having to use :func:`inject` or :data:`Inject` with the callable.

        `typing.List` and `typing.Dict` instances are reserved for multibindings and trying to bind them
        here will result in an error (use :meth:`multibind` instead)::

            binder.bind(List[str], to=['hello', 'there'])  # Error

        :param interface: Type to bind.
        :param to: Instance or class to bind to, or an instance of
             :class:`Provider` subclass.
        :param scope: Optional :class:`Scope` in which to bind.
        """
        if _get_origin(_punch_through_alias(interface)) in {dict, list}:
            raise Error(
                'Type %s is reserved for multibindings. Use multibind instead of bind.' % (interface,)
            )
        self._bindings[interface] = self.create_binding(interface, to, scope)

    @overload
    def multibind(
        self,
        interface: Type[List[T]],
        to: Union[List[T], Callable[..., List[T]], Provider[List[T]]],
        scope: Union[Type['Scope'], 'ScopeDecorator', None] = None,
    ) -> None:  # pragma: no cover
        pass

    @overload
    def multibind(
        self,
        interface: Type[Dict[K, V]],
        to: Union[Dict[K, V], Callable[..., Dict[K, V]], Provider[Dict[K, V]]],
        scope: Union[Type['Scope'], 'ScopeDecorator', None] = None,
    ) -> None:  # pragma: no cover
        pass

    def multibind(
        self, interface: type, to: Any, scope: Union['ScopeDecorator', Type['Scope'], None] = None
    ) -> None:
        """Creates or extends a multi-binding.

        A multi-binding contributes values to a list or to a dictionary. For example::

            binder.multibind(List[str], to=['some', 'strings'])
            binder.multibind(List[str], to=['other', 'strings'])
            injector.get(List[str])  # ['some', 'strings', 'other', 'strings']

            binder.multibind(Dict[str, int], to={'key': 11})
            binder.multibind(Dict[str, int], to={'other_key': 33})
            injector.get(Dict[str, int])  # {'key': 11, 'other_key': 33}

        .. versionchanged:: 0.17.0
            Added support for using `typing.Dict` and `typing.List` instances as interfaces.
            Deprecated support for `MappingKey`, `SequenceKey` and single-item lists and
            dictionaries as interfaces.

        :param interface: typing.Dict or typing.List instance to bind to.
        :param to: Instance, class to bind to, or an explicit :class:`Provider`
                subclass. Must provide a list or a dictionary, depending on the interface.
        :param scope: Optional Scope in which to bind.
        """
        if interface not in self._bindings:
            provider: ListOfProviders
            if (
                isinstance(interface, dict)
                or isinstance(interface, type)
                and issubclass(interface, dict)
                or _get_origin(_punch_through_alias(interface)) is dict
            ):
                provider = MapBindProvider()
            else:
                provider = MultiBindProvider()
            binding = self.create_binding(interface, provider, scope)
            self._bindings[interface] = binding
        else:
            binding = self._bindings[interface]
            provider = binding.provider
            assert isinstance(provider, ListOfProviders)
        provider.append(self.provider_for(interface, to))

    def install(self, module: _InstallableModuleType) -> None:
        """Install a module into this binder.

        In this context the module is one of the following:

        * function taking the :class:`Binder` as its only parameter

          ::

            def configure(binder):
                bind(str, to='s')

            binder.install(configure)

        * instance of :class:`Module` (instance of its subclass counts)

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
        if type(module) is type and issubclass(cast(type, module), Module):
            instance = cast(type, module)()
        else:
            instance = module
        instance(self)

    def create_binding(
        self, interface: type, to: Any = None, scope: Union['ScopeDecorator', Type['Scope'], None] = None
    ) -> Binding:
        provider = self.provider_for(interface, to)
        scope = scope or getattr(to or interface, '__scope__', NoScope)
        if isinstance(scope, ScopeDecorator):
            scope = scope.scope
        return Binding(interface, provider, scope)

    def provider_for(self, interface: Any, to: Any = None) -> Provider:
        base_type = _punch_through_alias(interface)
        origin = _get_origin(base_type)

        if interface is Any:
            raise TypeError('Injecting Any is not supported')
        elif _is_specialization(interface, ProviderOf):
            (target,) = interface.__args__
            if to is not None:
                raise Exception('ProviderOf cannot be bound to anything')
            return InstanceProvider(ProviderOf(self.injector, target))
        elif isinstance(to, Provider):
            return to
        elif isinstance(
            to,
            (
                types.FunctionType,
                types.LambdaType,
                types.MethodType,
                types.BuiltinFunctionType,
                types.BuiltinMethodType,
            ),
        ):
            return CallableProvider(to)
        elif issubclass(type(to), type):
            return ClassProvider(cast(type, to))
        elif isinstance(interface, BoundKey):

            def proxy(injector: Injector) -> Any:
                binder = injector.binder
                kwarg_providers = {
                    name: binder.provider_for(None, provider) for (name, provider) in interface.kwargs.items()
                }
                kwargs = {name: provider.get(injector) for (name, provider) in kwarg_providers.items()}
                return interface.interface(**kwargs)

            return CallableProvider(inject(proxy))
        elif _is_specialization(interface, AssistedBuilder):
            (target,) = interface.__args__
            builder = interface(self.injector, target)
            return InstanceProvider(builder)
        elif (
            origin is None
            and isinstance(base_type, (tuple, type))
            and interface is not Any
            and isinstance(to, base_type)
            or origin in {dict, list}
            and isinstance(to, origin)
        ):
            return InstanceProvider(to)
        elif issubclass(type(base_type), type) or isinstance(base_type, (tuple, list)):
            if to is not None:
                return InstanceProvider(to)
            return ClassProvider(base_type)

        else:
            raise UnknownProvider('couldn\'t determine provider for %r to %r' % (interface, to))

    def _get_binding(self, key: type, *, only_this_binder: bool = False) -> Tuple[Binding, 'Binder']:
        binding = self._bindings.get(key)
        if binding:
            return binding, self
        if self.parent and not only_this_binder:
            return self.parent._get_binding(key)

        raise KeyError

    def get_binding(self, interface: type) -> Tuple[Binding, 'Binder']:
        is_scope = isinstance(interface, type) and issubclass(interface, Scope)
        is_assisted_builder = _is_specialization(interface, AssistedBuilder)
        try:
            return self._get_binding(interface, only_this_binder=is_scope or is_assisted_builder)
        except (KeyError, UnsatisfiedRequirement):
            if is_scope:
                scope = interface
                self.bind(scope, to=scope(self.injector))
                return self._get_binding(interface)
            # The special interface is added here so that requesting a special
            # interface with auto_bind disabled works
            if self._auto_bind or self._is_special_interface(interface):
                binding = ImplicitBinding(*self.create_binding(interface))
                self._bindings[interface] = binding
                return binding, self

        raise UnsatisfiedRequirement(None, interface)

    def has_binding_for(self, interface: type) -> bool:
        return interface in self._bindings

    def has_explicit_binding_for(self, interface: type) -> bool:
        return self.has_binding_for(interface) and not isinstance(self._bindings[interface], ImplicitBinding)

    def _is_special_interface(self, interface: type) -> bool:
        # "Special" interfaces are ones that you cannot bind yourself but
        # you can request them (for example you cannot bind ProviderOf(SomeClass)
        # to anything but you can inject ProviderOf(SomeClass) just fine
        return any(_is_specialization(interface, cls) for cls in [AssistedBuilder, ProviderOf])


def _is_specialization(cls: type, generic_class: Any) -> bool:
    # Starting with typing 3.5.3/Python 3.6 it is no longer necessarily true that
    # issubclass(SomeGeneric[X], SomeGeneric) so we need some other way to
    # determine whether a particular object is a generic class with type parameters
    # provided. Fortunately there seems to be __origin__ attribute that's useful here.

    # We need to special-case Annotated as its __origin__ behaves differently than
    # other typing generic classes. See https://github.com/python/typing/pull/635
    # for some details.
    if generic_class is Annotated and isinstance(cls, _AnnotatedAlias):
        return True

    if not hasattr(cls, '__origin__'):
        return False
    origin = cast(Any, cls).__origin__
    if not inspect.isclass(generic_class):
        generic_class = type(generic_class)
    if not inspect.isclass(origin):
        origin = type(origin)
    # __origin__ is generic_class is a special case to handle Union as
    # Union cannot be used in issubclass() check (it raises an exception
    # by design).
    return origin is generic_class or issubclass(origin, generic_class)


def _punch_through_alias(type_: Any) -> type:
    if (
        sys.version_info < (3, 10)
        and getattr(type_, '__qualname__', '') == 'NewType.<locals>.new_type'
        or sys.version_info >= (3, 10)
        and type(type_).__module__ == 'typing'
        and type(type_).__name__ == 'NewType'
    ):
        return type_.__supertype__
    elif isinstance(type_, _AnnotatedAlias) and getattr(type_, '__metadata__', None) is not None:
        return type_.__origin__
    else:
        return type_


def _get_origin(type_: type) -> Optional[type]:
    origin = getattr(type_, '__origin__', None)
    # Older typing behaves differently there and stores Dict and List as origin, we need to be flexible.
    if origin is List:
        return list
    elif origin is Dict:
        return dict
    return origin


class Scope:
    """A Scope looks up the Provider for a binding.

    By default (ie. :class:`NoScope` ) this simply returns the default
    :class:`Provider` .
    """

    __metaclass__ = ABCMeta

    def __init__(self, injector: 'Injector') -> None:
        self.injector = injector
        self.configure()

    def configure(self) -> None:
        """Configure the scope."""

    @abstractmethod
    def get(self, key: Type[T], provider: Provider[T]) -> Provider[T]:
        """Get a :class:`Provider` for a key.

        :param key: The key to return a provider for.
        :param provider: The default Provider associated with the key.
        :returns: A Provider instance that can provide an instance of key.
        """
        raise NotImplementedError  # pragma: no cover


class ScopeDecorator:
    def __init__(self, scope: Type[Scope]) -> None:
        self.scope = scope

    def __call__(self, cls: T) -> T:
        cast(Any, cls).__scope__ = self.scope
        binding = getattr(cls, '__binding__', None)
        if binding:
            new_binding = Binding(interface=binding.interface, provider=binding.provider, scope=self.scope)
            setattr(cls, '__binding__', new_binding)
        return cls

    def __repr__(self) -> str:
        return 'ScopeDecorator(%s)' % self.scope.__name__


class NoScope(Scope):
    """An unscoped provider."""

    def get(self, unused_key: Type[T], provider: Provider[T]) -> Provider[T]:
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

    _context: Dict[type, Provider]

    def configure(self) -> None:
        self._context = {}

    @synchronized(lock)
    def get(self, key: Type[T], provider: Provider[T]) -> Provider[T]:
        try:
            return self._context[key]
        except KeyError:
            instance = self._get_instance(key, provider, self.injector)
            provider = InstanceProvider(instance)
            self._context[key] = provider
            return provider

    def _get_instance(self, key: Type[T], provider: Provider[T], injector: 'Injector') -> T:
        if injector.parent and not injector.binder.has_explicit_binding_for(key):
            try:
                return self._get_instance_from_parent(key, provider, injector.parent)
            except (CallError, UnsatisfiedRequirement):
                pass
        return provider.get(injector)

    def _get_instance_from_parent(self, key: Type[T], provider: Provider[T], parent: 'Injector') -> T:
        singleton_scope_binding, _ = parent.binder.get_binding(type(self))
        singleton_scope = singleton_scope_binding.provider.get(parent)
        provider = singleton_scope.get(key, provider)
        return provider.get(parent)


singleton = ScopeDecorator(SingletonScope)


class ThreadLocalScope(Scope):
    """A :class:`Scope` that returns a per-thread instance for a key."""

    def configure(self) -> None:
        self._locals = threading.local()

    def get(self, key: Type[T], provider: Provider[T]) -> Provider[T]:
        try:
            return getattr(self._locals, repr(key))
        except AttributeError:
            provider = InstanceProvider(provider.get(self.injector))
            setattr(self._locals, repr(key), provider)
            return provider


threadlocal = ScopeDecorator(ThreadLocalScope)


class Module:
    """Configures injector and providers."""

    def __call__(self, binder: Binder) -> None:
        """Configure the binder."""
        self.__injector__ = binder.injector
        for unused_name, function in inspect.getmembers(self, inspect.ismethod):
            binding = None
            if hasattr(function, '__binding__'):
                binding = function.__binding__
                if binding.interface == '__deferred__':
                    # We could not evaluate a forward reference at @provider-decoration time, we need to
                    # try again now.
                    try:
                        annotations = get_type_hints(function)
                    except NameError as e:
                        raise NameError(
                            'Cannot avaluate forward reference annotation(s) in method %r belonging to %r: %s'
                            % (function.__name__, type(self), e)
                        ) from e
                    return_type = annotations['return']
                    binding = cast(Any, function.__func__).__binding__ = Binding(
                        interface=return_type, provider=binding.provider, scope=binding.scope
                    )
                bind_method = binder.multibind if binding.is_multibinding() else binder.bind
                bind_method(  # type: ignore
                    binding.interface, to=types.MethodType(binding.provider, self), scope=binding.scope
                )
        self.configure(binder)

    def configure(self, binder: Binder) -> None:
        """Override to configure bindings."""


class Injector:
    """
    :param modules: Optional - a configuration module or iterable of configuration modules.
        Each module will be installed in current :class:`Binder` using :meth:`Binder.install`.

        Consult :meth:`Binder.install` documentation for the details.

    :param auto_bind: Whether to automatically bind missing types.
    :param parent: Parent injector.

    .. versionadded:: 0.7.5
        ``use_annotations`` parameter

    .. versionchanged:: 0.13.0
        ``use_annotations`` parameter is removed
    """

    _stack: Tuple[Tuple[object, Callable, Tuple[Tuple[str, type], ...]], ...]
    binder: Binder

    def __init__(
        self,
        modules: Union[_InstallableModuleType, Iterable[_InstallableModuleType], None] = None,
        auto_bind: bool = True,
        parent: Optional['Injector'] = None,
    ) -> None:
        # Stack of keys currently being injected. Used to detect circular
        # dependencies.
        self._stack = ()

        self.parent = parent

        # Binder
        self.binder = Binder(self, auto_bind=auto_bind, parent=parent.binder if parent is not None else None)

        if not modules:
            modules = []
        elif not hasattr(modules, '__iter__'):
            modules = [cast(_InstallableModuleType, modules)]
        # This line is needed to pelase mypy. We know we have Iteable of modules here.
        modules = cast(Iterable[_InstallableModuleType], modules)

        # Bind some useful types
        self.binder.bind(Injector, to=self)
        self.binder.bind(Binder, to=self.binder)

        # Initialise modules
        for module in modules:
            self.binder.install(module)

    @property
    def _log_prefix(self) -> str:
        return '>' * (len(self._stack) + 1) + ' '

    @synchronized(lock)
    def get(self, interface: Type[T], scope: Union[ScopeDecorator, Type[Scope], None] = None) -> T:
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
        binding, binder = self.binder.get_binding(interface)
        scope = scope or binding.scope
        if isinstance(scope, ScopeDecorator):
            scope = scope.scope
        # Fetch the corresponding Scope instance from the Binder.
        scope_binding, _ = binder.get_binding(scope)
        scope_instance = scope_binding.provider.get(self)

        log.debug(
            '%sInjector.get(%r, scope=%r) using %r', self._log_prefix, interface, scope, binding.provider
        )
        provider_instance = scope_instance.get(interface, binding.provider)
        result = provider_instance.get(self)
        log.debug('%s -> %r', self._log_prefix, result)
        return result

    def create_child_injector(self, *args: Any, **kwargs: Any) -> 'Injector':
        kwargs['parent'] = self
        return Injector(*args, **kwargs)

    def create_object(self, cls: Type[T], additional_kwargs: Any = None) -> T:
        """Create a new instance, satisfying any dependencies on cls."""
        additional_kwargs = additional_kwargs or {}
        log.debug('%sCreating %r object with %r', self._log_prefix, cls, additional_kwargs)

        try:
            instance = cls.__new__(cls)
        except TypeError as e:
            reraise(
                e,
                CallError(cls, getattr(cls.__new__, '__func__', cls.__new__), (), {}, e, self._stack),
                maximum_frames=2,
            )
        init = cls.__init__
        try:
            self.call_with_injection(init, self_=instance, kwargs=additional_kwargs)
        except TypeError as e:
            # Mypy says "Cannot access "__init__" directly"
            init_function = instance.__init__.__func__  # type: ignore
            reraise(e, CallError(instance, init_function, (), additional_kwargs, e, self._stack))
        return instance

    def call_with_injection(
        self, callable: Callable[..., T], self_: Any = None, args: Any = (), kwargs: Any = {}
    ) -> T:
        """Call a callable and provide its dependencies if needed.

        Dependencies are provided when the callable is decorated with :func:`@inject <inject>`
        or some individual parameters are wrapped in :data:`Inject` – otherwise
        ``call_with_injection()`` is equivalent to just calling the callable directly.

        If there is an overlap between arguments provided in ``args`` and ``kwargs``
        and injectable dependencies the provided values take precedence and no dependency
        injection process will take place for the corresponding parameters.

        :param self_: Instance of a class callable belongs to if it's a method,
            None otherwise.
        :param args: Arguments to pass to callable.
        :param kwargs: Keyword arguments to pass to callable.
        :type callable: callable
        :type args: tuple of objects
        :type kwargs: dict of string -> object
        :return: Value returned by callable.
        """

        bindings = get_bindings(callable)
        signature = inspect.signature(callable)
        full_args = args
        if self_ is not None:
            full_args = (self_,) + full_args
        bound_arguments = signature.bind_partial(*full_args)

        needed = dict(
            (k, v) for (k, v) in bindings.items() if k not in kwargs and k not in bound_arguments.arguments
        )

        dependencies = self.args_to_inject(
            function=callable,
            bindings=needed,
            owner_key=self_.__class__ if self_ is not None else callable.__module__,
        )

        dependencies.update(kwargs)

        try:
            return callable(*full_args, **dependencies)
        except TypeError as e:
            reraise(e, CallError(self_, callable, args, dependencies, e, self._stack))
            # Needed because of a mypy-related issue (https://github.com/python/mypy/issues/8129).
            assert False, "unreachable"  # pragma: no cover

    @private
    @synchronized(lock)
    def args_to_inject(
        self, function: Callable, bindings: Dict[str, type], owner_key: object
    ) -> Dict[str, Any]:
        """Inject arguments into a function.

        :param function: The function.
        :param bindings: Map of argument name to binding key to inject.
        :param owner_key: A key uniquely identifying the *scope* of this function.
            For a method this will be the owning class.
        :returns: Dictionary of resolved arguments.
        """
        dependencies = {}

        key = (owner_key, function, tuple(sorted(bindings.items())))

        def repr_key(k: Tuple[object, Callable, Tuple[Tuple[str, type], ...]]) -> str:
            owner_key, function, bindings = k
            return '%s.%s(injecting %s)' % (tuple(map(_describe, k[:2])) + (dict(k[2]),))

        log.debug('%sProviding %r for %r', self._log_prefix, bindings, function)

        if key in self._stack:
            raise CircularDependency(
                'circular dependency detected: %s -> %s'
                % (' -> '.join(map(repr_key, self._stack)), repr_key(key))
            )

        self._stack += (key,)
        try:
            for arg, interface in bindings.items():
                try:
                    instance: Any = self.get(interface)
                except UnsatisfiedRequirement as e:
                    if not e.owner:
                        e = UnsatisfiedRequirement(owner_key, e.interface)
                    raise e
                dependencies[arg] = instance
        finally:
            self._stack = tuple(self._stack[:-1])

        return dependencies


def get_bindings(callable: Callable) -> Dict[str, type]:
    """Get bindings of injectable parameters from a callable.

    If the callable is not decorated with :func:`inject` and does not have any of its
    parameters declared as injectable using :data:`Inject` an empty dictionary will
    be returned.  Otherwise the returned dictionary will contain a mapping
    between parameter names and their types with the exception of parameters
    excluded from dependency injection (either with :func:`noninjectable`, :data:`NoInject`
    or only explicit injection with :data:`Inject` being used). For example::

        >>> def function1(a: int) -> None:
        ...     pass
        ...
        >>> get_bindings(function1)
        {}

        >>> @inject
        ... def function2(a: int) -> None:
        ...     pass
        ...
        >>> get_bindings(function2)
        {'a': <class 'int'>}

        >>> @inject
        ... @noninjectable('b')
        ... def function3(a: int, b: str) -> None:
        ...     pass
        ...
        >>> get_bindings(function3)
        {'a': <class 'int'>}

        >>> # The simple case of no @inject but injection requested with Inject[...]
        >>> def function4(a: Inject[int], b: str) -> None:
        ...     pass
        ...
        >>> get_bindings(function4)
        {'a': <class 'int'>}

        >>> # Using @inject with Inject is redundant but it should not break anything
        >>> @inject
        ... def function5(a: Inject[int], b: str) -> None:
        ...     pass
        ...
        >>> get_bindings(function5)
        {'a': <class 'int'>, 'b': <class 'str'>}

        >>> # We need to be able to exclude a parameter from injection with NoInject
        >>> @inject
        ... def function6(a: int, b: NoInject[str]) -> None:
        ...     pass
        ...
        >>> get_bindings(function6)
        {'a': <class 'int'>}

        >>> # The presence of NoInject should not trigger anything on its own
        >>> def function7(a: int, b: NoInject[str]) -> None:
        ...     pass
        ...
        >>> get_bindings(function7)
        {}

    This function is used internally so by calling it you can learn what exactly
    Injector is going to try to provide to a callable.
    """
    look_for_explicit_bindings = False
    if not hasattr(callable, '__bindings__'):
        type_hints = get_type_hints(callable, include_extras=True)
        has_injectable_parameters = any(
            _is_specialization(v, Annotated) and _inject_marker in v.__metadata__ for v in type_hints.values()
        )

        if not has_injectable_parameters:
            return {}
        else:
            look_for_explicit_bindings = True

    if look_for_explicit_bindings or cast(Any, callable).__bindings__ == 'deferred':
        read_and_store_bindings(
            callable, _infer_injected_bindings(callable, only_explicit_bindings=look_for_explicit_bindings)
        )
    noninjectables: Set[str] = getattr(callable, '__noninjectables__', set())
    return {k: v for k, v in cast(Any, callable).__bindings__.items() if k not in noninjectables}


class _BindingNotYetAvailable(Exception):
    pass


# See a comment in _infer_injected_bindings() for why this is useful.
class _NoReturnAnnotationProxy:
    def __init__(self, callable: Callable) -> None:
        self.callable = callable

    def __getattribute__(self, name: str) -> Any:
        # get_type_hints() uses quite complex logic to determine the namespaces using which
        # any forward references should be resolved. Instead of mirroring this logic here
        # let's just take the easy way out and forward all attribute access to the original
        # callable except for the annotations – we want to filter them.
        callable = object.__getattribute__(self, 'callable')
        if name == '__annotations__':
            annotations = callable.__annotations__
            return {name: value for (name, value) in annotations.items() if name != 'return'}
        return getattr(callable, name)


def _infer_injected_bindings(callable: Callable, only_explicit_bindings: bool) -> Dict[str, type]:
    def _is_new_union_type(instance: Any) -> bool:
        new_union_type = getattr(types, 'UnionType', None)
        return new_union_type is not None and isinstance(instance, new_union_type)

    spec = inspect.getfullargspec(callable)

    try:
        # Return types don't matter for the purpose of dependency injection so instead of
        # obtaining type hints of the callable directly let's wrap it in _NoReturnAnnotationProxy.
        # The proxy removes the return type annotation (if present) from the annotations so that
        # get_type_hints() works even if the return type is a forward reference that can't be
        # resolved.
        bindings = get_type_hints(cast(Callable, _NoReturnAnnotationProxy(callable)), include_extras=True)
    except NameError as e:
        raise _BindingNotYetAvailable(e)

    # We don't care about the return value annotation as it doesn't matter
    # injection-wise.
    bindings.pop('return', None)

    # If we're dealing with a bound method get_type_hints will still return `self` annotation even though
    # it's already provided and we're not really interested in its type. So – drop it.
    if isinstance(callable, types.MethodType):
        self_name = spec.args[0]
        bindings.pop(self_name, None)

    # variadic arguments aren't supported at the moment (this may change
    # in the future if someone has a good idea how to utilize them)
    if spec.varargs:
        bindings.pop(spec.varargs, None)
    if spec.varkw:
        bindings.pop(spec.varkw, None)

    for k, v in list(bindings.items()):
        if _is_specialization(v, Annotated):
            v, metadata = v.__origin__, v.__metadata__
            bindings[k] = v
        else:
            metadata = tuple()

        if only_explicit_bindings and _inject_marker not in metadata or _noinject_marker in metadata:
            del bindings[k]
        elif _is_specialization(v, Union) or _is_new_union_type(v):
            # We don't treat Optional parameters in any special way at the moment.
            union_members = v.__args__
            new_members = tuple(set(union_members) - {type(None)})
            # mypy stared complaining about this line for some reason:
            #     error: Variable "new_members" is not valid as a type
            new_union = Union[new_members]  # type: ignore
            # mypy complains about this construct:
            #     error: The type alias is invalid in runtime context
            # See: https://github.com/python/mypy/issues/5354
            union_metadata = {
                metadata
                for member in new_members
                for metadata in getattr(member, '__metadata__', tuple())
                if _is_specialization(member, Annotated)
            }
            if (
                only_explicit_bindings
                and _inject_marker not in union_metadata
                or _noinject_marker in union_metadata
            ):
                del bindings[k]
            else:
                bindings[k] = new_union  # type: ignore

    return bindings


def provider(function: CallableT) -> CallableT:
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
    """
    _mark_provider_function(function, allow_multi=False)
    return function


def multiprovider(function: CallableT) -> CallableT:
    """Like :func:`provider`, but for multibindings. Example usage::

        class MyModule(Module):
            @multiprovider
            def provide_strs(self) -> List[str]:
                return ['str1']

        class OtherModule(Module):
            @multiprovider
            def provide_strs_also(self) -> List[str]:
                return ['str2']

        Injector([MyModule, OtherModule]).get(List[str])  # ['str1', 'str2']

    See also: :meth:`Binder.multibind`."""
    _mark_provider_function(function, allow_multi=True)
    return function


def _mark_provider_function(function: Callable, *, allow_multi: bool) -> None:
    scope_ = getattr(function, '__scope__', None)
    try:
        annotations = get_type_hints(function)
    except NameError:
        return_type = '__deferred__'
    else:
        return_type = annotations['return']
        _validate_provider_return_type(function, cast(type, return_type), allow_multi)
    function.__binding__ = Binding(return_type, inject(function), scope_)  # type: ignore


def _validate_provider_return_type(function: Callable, return_type: type, allow_multi: bool) -> None:
    origin = _get_origin(_punch_through_alias(return_type))
    if origin in {dict, list} and not allow_multi:
        raise Error(
            'Function %s needs to be decorated with multiprovider instead of provider if it is to '
            'provide values to a multibinding of type %s' % (function.__name__, return_type)
        )


ConstructorOrClassT = TypeVar('ConstructorOrClassT', bound=Union[Callable, Type])


@overload
def inject(constructor_or_class: CallableT) -> CallableT:  # pragma: no cover
    pass


@overload
def inject(constructor_or_class: Type[T]) -> Type[T]:  # pragma: no cover
    pass


def inject(constructor_or_class: ConstructorOrClassT) -> ConstructorOrClassT:
    """Decorator declaring parameters to be injected.

    eg.

    >>> class A:
    ...     @inject
    ...     def __init__(self, number: int, name: str):
    ...         print([number, name])
    ...
    >>> def configure(binder):
    ...     binder.bind(A)
    ...     binder.bind(int, to=123)
    ...     binder.bind(str, to='Bob')

    Use the Injector to get a new instance of A:

    >>> a = Injector(configure).get(A)
    [123, 'Bob']

    As a convenience one can decorate a class itself::

        @inject
        class B:
            def __init__(self, dependency: Dependency):
                self.dependency = dependency

    This is equivalent to decorating its constructor. In particular this provides integration with
    `dataclasses <https://docs.python.org/3/library/dataclasses.html>`_ (the order of decorator
    application is important here)::

        @inject
        @dataclass
        class C:
            dependency: Dependency

    .. note::

        This decorator is to be used on class constructors (or, as a convenience, on classes).
        Using it on non-constructor methods worked in the past but it was an implementation
        detail rather than a design decision.

        Third party libraries may, however, provide support for injecting dependencies
        into non-constructor methods or free functions in one form or another.

    .. seealso::

        Generic type :data:`Inject`
            A more explicit way to declare parameters as injectable.

        Function :func:`get_bindings`
            A way to inspect how various injection declarations interact with each other.

    .. versionchanged:: 0.16.2

        (Re)added support for decorating classes with @inject.
    """
    if isinstance(constructor_or_class, type) and hasattr(constructor_or_class, '__init__'):
        inject(cast(Any, constructor_or_class).__init__)
    else:
        function = constructor_or_class
        try:
            bindings = _infer_injected_bindings(function, only_explicit_bindings=False)
            read_and_store_bindings(function, bindings)
        except _BindingNotYetAvailable:
            cast(Any, function).__bindings__ = 'deferred'
    return constructor_or_class


def noninjectable(*args: str) -> Callable[[CallableT], CallableT]:
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

    .. seealso::

        Generic type :data:`NoInject`
            A nicer way to declare parameters as noninjectable.

        Function :func:`get_bindings`
            A way to inspect how various injection declarations interact with each other.

    """

    def decorator(function: CallableT) -> CallableT:
        argspec = inspect.getfullargspec(inspect.unwrap(function))
        for arg in args:
            if arg not in argspec.args and arg not in argspec.kwonlyargs:
                raise UnknownArgument('Unable to mark unknown argument %s ' 'as non-injectable.' % arg)

        existing: Set[str] = getattr(function, '__noninjectables__', set())
        merged = existing | set(args)
        cast(Any, function).__noninjectables__ = merged
        return function

    return decorator


@private
def read_and_store_bindings(f: Callable, bindings: Dict[str, type]) -> None:
    function_bindings = getattr(f, '__bindings__', None) or {}
    if function_bindings == 'deferred':
        function_bindings = {}
    merged_bindings = dict(function_bindings, **bindings)

    if hasattr(f, '__func__'):
        f = cast(Any, f).__func__
    cast(Any, f).__bindings__ = merged_bindings


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

    def __new__(cls, interface: Type[T], **kwargs: Any) -> 'BoundKey':
        kwargs_tuple = tuple(sorted(kwargs.items()))
        return super(BoundKey, cls).__new__(cls, (interface, kwargs_tuple))  # type: ignore

    @property
    def interface(self) -> Type[T]:
        return self[0]

    @property
    def kwargs(self) -> Dict[str, Any]:
        return dict(self[1])


class AssistedBuilder(Generic[T]):
    def __init__(self, injector: Injector, target: Type[T]) -> None:
        self._injector = injector
        self._target = target

    def build(self, **kwargs: Any) -> T:
        binder = self._injector.binder
        binding, _ = binder.get_binding(self._target)
        provider = binding.provider
        if not isinstance(provider, ClassProvider):
            raise Error(
                'Assisted interface building works only with ClassProviders, '
                'got %r for %r' % (provider, binding.interface)
            )

        return self._build_class(cast(Type[T], provider._cls), **kwargs)

    def _build_class(self, cls: Type[T], **kwargs: Any) -> T:
        return self._injector.create_object(cls, additional_kwargs=kwargs)


class ClassAssistedBuilder(AssistedBuilder[T]):
    def build(self, **kwargs: Any) -> T:
        return self._build_class(self._target, **kwargs)


def _describe(c: Any) -> str:
    if hasattr(c, '__name__'):
        return cast(str, c.__name__)
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

    def __init__(self, injector: Injector, interface: Type[T]):
        self._injector = injector
        self._interface = interface

    def __repr__(self) -> str:
        return '%s(%r, %r)' % (type(self).__name__, self._injector, self._interface)

    def get(self) -> T:
        """Get an implementation for the specified interface."""
        return self._injector.get(self._interface)


def is_decorated_with_inject(function: Callable[..., Any]) -> bool:
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
