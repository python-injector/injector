# encoding: utf-8
#
# Copyright (C) 2010 Alec Thomas <alec@swapoff.org>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#
# Author: Alec Thomas <alec@swapoff.org>

"""Functional tests for the "Injector" dependency injection framework."""

from contextlib import contextmanager
from typing import Any, NewType
import abc
import sys
import threading
import traceback
import warnings

from typing import Dict, List, NewType

import pytest

from injector import (
    Binder,
    CallError,
    Injector,
    Scope,
    InstanceProvider,
    ClassProvider,
    get_bindings,
    inject,
    multiprovider,
    noninjectable,
    singleton,
    threadlocal,
    UnsatisfiedRequirement,
    CircularDependency,
    Module,
    SingletonScope,
    ScopeDecorator,
    AssistedBuilder,
    provider,
    ProviderOf,
    ClassAssistedBuilder,
    Error,
    UnknownArgument,
    HAVE_ANNOTATED,
)

if HAVE_ANNOTATED:
    from injector import Inject, NoInject


class EmptyClass:
    pass


class DependsOnEmptyClass:
    @inject
    def __init__(self, b: EmptyClass):
        """Construct a new DependsOnEmptyClass."""
        self.b = b


def prepare_nested_injectors():
    def configure(binder):
        binder.bind(str, to='asd')

    parent = Injector(configure)
    child = parent.create_child_injector()
    return parent, child


def check_exception_contains_stuff(exception, stuff):
    stringified = str(exception)

    for thing in stuff:
        assert thing in stringified, '%r should be present in the exception representation: %s' % (
            thing,
            stringified,
        )


def test_child_injector_inherits_parent_bindings():
    parent, child = prepare_nested_injectors()
    assert child.get(str) == parent.get(str)


def test_child_injector_overrides_parent_bindings():
    parent, child = prepare_nested_injectors()
    child.binder.bind(str, to='qwe')

    assert (parent.get(str), child.get(str)) == ('asd', 'qwe')


def test_child_injector_rebinds_arguments_for_parent_scope():
    class Cls:
        val = ""

    class A(Cls):
        @inject
        def __init__(self, val: str):
            self.val = val

    def configure_parent(binder):
        binder.bind(Cls, to=A)
        binder.bind(str, to="Parent")

    def configure_child(binder):
        binder.bind(str, to="Child")

    parent = Injector(configure_parent)
    assert parent.get(Cls).val == "Parent"
    child = parent.create_child_injector(configure_child)
    assert child.get(Cls).val == "Child"


def test_scopes_are_only_bound_to_root_injector():
    parent, child = prepare_nested_injectors()

    class A:
        pass

    parent.binder.bind(A, to=A, scope=singleton)
    assert parent.get(A) is child.get(A)


def test_get_default_injected_instances():
    def configure(binder):
        binder.bind(DependsOnEmptyClass)
        binder.bind(EmptyClass)

    injector = Injector(configure)
    assert injector.get(Injector) is injector
    assert injector.get(Binder) is injector.binder


def test_instantiate_injected_method():
    a = DependsOnEmptyClass('Bob')
    assert a.b == 'Bob'


def test_method_decorator_is_wrapped():
    assert DependsOnEmptyClass.__init__.__doc__ == 'Construct a new DependsOnEmptyClass.'
    assert DependsOnEmptyClass.__init__.__name__ == '__init__'


def test_decorator_works_for_function_with_no_args():
    @inject
    def wrapped(*args, **kwargs):
        pass


def test_providers_arent_called_for_dependencies_that_are_already_provided():
    def configure(binder):
        binder.bind(int, to=lambda: 1 / 0)

    class A:
        @inject
        def __init__(self, i: int):
            pass

    injector = Injector(configure)
    builder = injector.get(AssistedBuilder[A])

    with pytest.raises(ZeroDivisionError):
        builder.build()

    builder.build(i=3)


def test_inject_direct():
    def configure(binder):
        binder.bind(DependsOnEmptyClass)
        binder.bind(EmptyClass)

    injector = Injector(configure)
    a = injector.get(DependsOnEmptyClass)
    assert isinstance(a, DependsOnEmptyClass)
    assert isinstance(a.b, EmptyClass)


def test_configure_multiple_modules():
    def configure_a(binder):
        binder.bind(DependsOnEmptyClass)

    def configure_b(binder):
        binder.bind(EmptyClass)

    injector = Injector([configure_a, configure_b])
    a = injector.get(DependsOnEmptyClass)
    assert isinstance(a, DependsOnEmptyClass)
    assert isinstance(a.b, EmptyClass)


def test_inject_with_missing_dependency():
    def configure(binder):
        binder.bind(DependsOnEmptyClass)

    injector = Injector(configure, auto_bind=False)
    with pytest.raises(UnsatisfiedRequirement):
        injector.get(EmptyClass)


def test_inject_named_interface():
    class A:
        @inject
        def __init__(self, b: EmptyClass):
            self.b = b

    def configure(binder):
        binder.bind(A)
        binder.bind(EmptyClass)

    injector = Injector(configure)
    a = injector.get(A)
    assert isinstance(a, A)
    assert isinstance(a.b, EmptyClass)


class TransitiveC:
    pass


class TransitiveB:
    @inject
    def __init__(self, c: TransitiveC):
        self.c = c


class TransitiveA:
    @inject
    def __init__(self, b: TransitiveB):
        self.b = b


def test_transitive_injection():
    def configure(binder):
        binder.bind(TransitiveA)
        binder.bind(TransitiveB)
        binder.bind(TransitiveC)

    injector = Injector(configure)
    a = injector.get(TransitiveA)
    assert isinstance(a, TransitiveA)
    assert isinstance(a.b, TransitiveB)
    assert isinstance(a.b.c, TransitiveC)


def test_transitive_injection_with_missing_dependency():
    def configure(binder):
        binder.bind(TransitiveA)
        binder.bind(TransitiveB)

    injector = Injector(configure, auto_bind=False)
    with pytest.raises(UnsatisfiedRequirement):
        injector.get(TransitiveA)
    with pytest.raises(UnsatisfiedRequirement):
        injector.get(TransitiveB)


def test_inject_singleton():
    class A:
        @inject
        def __init__(self, b: EmptyClass):
            self.b = b

    def configure(binder):
        binder.bind(A)
        binder.bind(EmptyClass, scope=SingletonScope)

    injector1 = Injector(configure)
    a1 = injector1.get(A)
    a2 = injector1.get(A)
    assert a1.b is a2.b


@singleton
class SingletonB:
    pass


def test_inject_decorated_singleton_class():
    class A:
        @inject
        def __init__(self, b: SingletonB):
            self.b = b

    def configure(binder):
        binder.bind(A)
        binder.bind(SingletonB)

    injector1 = Injector(configure)
    a1 = injector1.get(A)
    a2 = injector1.get(A)
    assert a1.b is a2.b


def test_threadlocal():
    @threadlocal
    class A:
        def __init__(self):
            pass

    def configure(binder):
        binder.bind(A)

    injector = Injector(configure)
    a1 = injector.get(A)
    a2 = injector.get(A)

    assert a1 is a2

    a3 = [None]
    ready = threading.Event()

    def inject_a3():
        a3[0] = injector.get(A)
        ready.set()

    threading.Thread(target=inject_a3).start()
    ready.wait(1.0)

    assert a2 is not a3[0] and a3[0] is not None


class Interface2:
    pass


def test_injecting_interface_implementation():
    class Implementation:
        pass

    class A:
        @inject
        def __init__(self, i: Interface2):
            self.i = i

    def configure(binder):
        binder.bind(A)
        binder.bind(Interface2, to=Implementation)

    injector = Injector(configure)
    a = injector.get(A)
    assert isinstance(a.i, Implementation)


class CyclicInterface:
    pass


class CyclicA:
    @inject
    def __init__(self, i: CyclicInterface):
        self.i = i


class CyclicB:
    @inject
    def __init__(self, a: CyclicA):
        self.a = a


def test_cyclic_dependencies():
    def configure(binder):
        binder.bind(CyclicInterface, to=CyclicB)
        binder.bind(CyclicA)

    injector = Injector(configure)
    with pytest.raises(CircularDependency):
        injector.get(CyclicA)


class CyclicInterface2:
    pass


class CyclicA2:
    @inject
    def __init__(self, i: CyclicInterface2):
        self.i = i


class CyclicB2:
    @inject
    def __init__(self, a_builder: AssistedBuilder[CyclicA2]):
        self.a = a_builder.build(i=self)


def test_dependency_cycle_can_be_worked_broken_by_assisted_building():
    def configure(binder):
        binder.bind(CyclicInterface2, to=CyclicB2)
        binder.bind(CyclicA2)

    injector = Injector(configure)

    # Previously it'd detect a circular dependency here:
    # 1. Constructing CyclicA2 requires CyclicInterface2 (bound to CyclicB2)
    # 2. Constructing CyclicB2 requires assisted build of CyclicA2
    # 3. Constructing CyclicA2 triggers circular dependency check
    assert isinstance(injector.get(CyclicA2), CyclicA2)


class Interface5:
    constructed = False

    def __init__(self):
        Interface5.constructed = True


def test_that_injection_is_lazy():
    class A:
        @inject
        def __init__(self, i: Interface5):
            self.i = i

    def configure(binder):
        binder.bind(Interface5)
        binder.bind(A)

    injector = Injector(configure)
    assert not (Interface5.constructed)
    injector.get(A)
    assert Interface5.constructed


def test_module_provider():
    class MyModule(Module):
        @provider
        def provide_name(self) -> str:
            return 'Bob'

    module = MyModule()
    injector = Injector(module)
    assert injector.get(str) == 'Bob'


def test_module_class_gets_instantiated():
    name = 'Meg'

    class MyModule(Module):
        def configure(self, binder):
            binder.bind(str, to=name)

    injector = Injector(MyModule)
    assert injector.get(str) == name


def test_inject_and_provide_coexist_happily():
    class MyModule(Module):
        @provider
        def provide_weight(self) -> float:
            return 50.0

        @provider
        def provide_age(self) -> int:
            return 25

        # TODO(alec) Make provider/inject order independent.
        @provider
        @inject
        def provide_description(self, age: int, weight: float) -> str:
            return 'Bob is %d and weighs %0.1fkg' % (age, weight)

    assert Injector(MyModule()).get(str) == 'Bob is 25 and weighs 50.0kg'


Names = NewType('Names', List[str])
Passwords = NewType('Ages', Dict[str, str])


def test_multibind():
    # First let's have some explicit multibindings
    def configure(binder):
        binder.multibind(List[str], to=['not a name'])
        binder.multibind(Dict[str, str], to={'asd': 'qwe'})
        # To make sure Lists and Dicts of different subtypes are treated distinctly
        binder.multibind(List[int], to=[1, 2, 3])
        binder.multibind(Dict[str, int], to={'weight': 12})
        # To see that NewTypes are treated distinctly
        binder.multibind(Names, to=['Bob'])
        binder.multibind(Passwords, to={'Bob': 'password1'})

    # Then @multiprovider-decorated Module methods
    class CustomModule(Module):
        @multiprovider
        def provide_some_ints(self) -> List[int]:
            return [4, 5, 6]

        @multiprovider
        def provide_some_strs(self) -> List[str]:
            return ['not a name either']

        @multiprovider
        def provide_str_to_str_mapping(self) -> Dict[str, str]:
            return {'xxx': 'yyy'}

        @multiprovider
        def provide_str_to_int_mapping(self) -> Dict[str, int]:
            return {'height': 33}

        @multiprovider
        def provide_names(self) -> Names:
            return ['Alice', 'Clarice']

        @multiprovider
        def provide_passwords(self) -> Passwords:
            return {'Alice': 'aojrioeg3', 'Clarice': 'clarice30'}

    injector = Injector([configure, CustomModule])
    assert injector.get(List[str]) == ['not a name', 'not a name either']
    assert injector.get(List[int]) == [1, 2, 3, 4, 5, 6]
    assert injector.get(Dict[str, str]) == {'asd': 'qwe', 'xxx': 'yyy'}
    assert injector.get(Dict[str, int]) == {'weight': 12, 'height': 33}
    assert injector.get(Names) == ['Bob', 'Alice', 'Clarice']
    assert injector.get(Passwords) == {'Bob': 'password1', 'Alice': 'aojrioeg3', 'Clarice': 'clarice30'}


def test_regular_bind_and_provider_dont_work_with_multibind():
    # We only want multibind and multiprovider to work to avoid confusion

    Names = NewType('Names', List[str])
    Passwords = NewType('Passwords', Dict[str, str])

    class MyModule(Module):
        with pytest.raises(Error):

            @provider
            def provide_strs(self) -> List[str]:
                return []

        with pytest.raises(Error):

            @provider
            def provide_names(self) -> Names:
                return []

        with pytest.raises(Error):

            @provider
            def provide_strs_in_dict(self) -> Dict[str, str]:
                return {}

        with pytest.raises(Error):

            @provider
            def provide_passwords(self) -> Passwords:
                return {}

    injector = Injector()
    binder = injector.binder

    with pytest.raises(Error):
        binder.bind(List[str], to=[])

    with pytest.raises(Error):
        binder.bind(Names, to=[])

    with pytest.raises(Error):
        binder.bind(Dict[str, str], to={})

    with pytest.raises(Error):
        binder.bind(Passwords, to={})


def test_auto_bind():
    class A:
        pass

    injector = Injector()
    assert isinstance(injector.get(A), A)


def test_auto_bind_with_newtype():
    # Reported in https://github.com/alecthomas/injector/issues/117
    class A:
        pass

    AliasOfA = NewType('AliasOfA', A)
    injector = Injector()
    assert isinstance(injector.get(AliasOfA), A)


class Request:
    pass


class RequestScope(Scope):
    def configure(self):
        self.context = None

    @contextmanager
    def __call__(self, request):
        assert self.context is None
        self.context = {}
        binder = self.injector.get(Binder)
        binder.bind(Request, to=request, scope=RequestScope)
        yield
        self.context = None

    def get(self, key, provider):
        if self.context is None:
            raise UnsatisfiedRequirement(None, key)
        try:
            return self.context[key]
        except KeyError:
            provider = InstanceProvider(provider.get(self.injector))
            self.context[key] = provider
            return provider


request = ScopeDecorator(RequestScope)


@request
class Handler:
    def __init__(self, request):
        self.request = request


class RequestModule(Module):
    @provider
    @inject
    def handler(self, request: Request) -> Handler:
        return Handler(request)


def test_custom_scope():

    injector = Injector([RequestModule()], auto_bind=False)

    with pytest.raises(UnsatisfiedRequirement):
        injector.get(Handler)

    scope = injector.get(RequestScope)
    request = Request()

    with scope(request):
        handler = injector.get(Handler)
        assert handler.request is request

    with pytest.raises(UnsatisfiedRequirement):
        injector.get(Handler)


def test_binder_install():
    class ModuleA(Module):
        def configure(self, binder):
            binder.bind(str, to='hello world')

    class ModuleB(Module):
        def configure(self, binder):
            binder.install(ModuleA())

    injector = Injector([ModuleB()])
    assert injector.get(str) == 'hello world'


def test_binder_provider_for_method_with_explicit_provider():
    injector = Injector()
    binder = injector.binder
    provider = binder.provider_for(int, to=InstanceProvider(1))
    assert type(provider) is InstanceProvider
    assert provider.get(injector) == 1


def test_binder_provider_for_method_with_instance():
    injector = Injector()
    binder = injector.binder
    provider = binder.provider_for(int, to=1)
    assert type(provider) is InstanceProvider
    assert provider.get(injector) == 1


def test_binder_provider_for_method_with_class():
    injector = Injector()
    binder = injector.binder
    provider = binder.provider_for(int)
    assert type(provider) is ClassProvider
    assert provider.get(injector) == 0


def test_binder_provider_for_method_with_class_to_specific_subclass():
    class A:
        pass

    class B(A):
        pass

    injector = Injector()
    binder = injector.binder
    provider = binder.provider_for(A, B)
    assert type(provider) is ClassProvider
    assert isinstance(provider.get(injector), B)


def test_binder_provider_for_type_with_metaclass():
    # use a metaclass cross python2/3 way
    # otherwise should be:
    # class A(object, metaclass=abc.ABCMeta):
    #    passa
    A = abc.ABCMeta('A', (object,), {})

    injector = Injector()
    binder = injector.binder
    assert isinstance(binder.provider_for(A, None).get(injector), A)


class ClassA:
    def __init__(self, parameter):
        pass


class ClassB:
    @inject
    def __init__(self, a: ClassA):
        pass


def test_injecting_undecorated_class_with_missing_dependencies_raises_the_right_error():
    injector = Injector()
    try:
        injector.get(ClassB)
    except CallError as ce:
        check_exception_contains_stuff(ce, ('ClassA.__init__', 'ClassB'))


def test_call_to_method_with_legitimate_call_error_raises_type_error():
    class A:
        def __init__(self):
            max()

    injector = Injector()
    with pytest.raises(TypeError):
        injector.get(A)


def test_call_error_str_representation_handles_single_arg():
    ce = CallError('zxc')
    assert str(ce) == 'zxc'


class NeedsAssistance:
    @inject
    def __init__(self, a: str, b):
        self.a = a
        self.b = b


def test_assisted_builder_works_when_got_directly_from_injector():
    injector = Injector()
    builder = injector.get(AssistedBuilder[NeedsAssistance])
    obj = builder.build(b=123)
    assert (obj.a, obj.b) == (str(), 123)


def test_assisted_builder_works_when_injected():
    class X:
        @inject
        def __init__(self, builder: AssistedBuilder[NeedsAssistance]):
            self.obj = builder.build(b=234)

    injector = Injector()
    x = injector.get(X)
    assert (x.obj.a, x.obj.b) == (str(), 234)


class Interface:
    b = 0


def test_assisted_builder_uses_bindings():
    def configure(binder):
        binder.bind(Interface, to=NeedsAssistance)

    injector = Injector(configure)
    builder = injector.get(AssistedBuilder[Interface])
    x = builder.build(b=333)
    assert (type(x), x.b) == (NeedsAssistance, 333)


def test_assisted_builder_uses_concrete_class_when_specified():
    class X:
        pass

    def configure(binder):
        # meant only to show that provider isn't called
        binder.bind(X, to=lambda: 1 / 0)

    injector = Injector(configure)
    builder = injector.get(ClassAssistedBuilder[X])
    builder.build()


def test_assisted_builder_injection_is_safe_to_use_with_multiple_injectors():
    class X:
        @inject
        def __init__(self, builder: AssistedBuilder[NeedsAssistance]):
            self.builder = builder

    i1, i2 = Injector(), Injector()
    b1 = i1.get(X).builder
    b2 = i2.get(X).builder
    assert (b1._injector, b2._injector) == (i1, i2)


class TestThreadSafety:
    def setup(self):
        self.event = threading.Event()

        def configure(binder):
            binder.bind(str, to=lambda: self.event.wait() and 'this is str')

        class XXX:
            @inject
            def __init__(self, s: str):
                pass

        self.injector = Injector(configure)
        self.cls = XXX

    def gather_results(self, count):
        objects = []
        lock = threading.Lock()

        def target():
            o = self.injector.get(self.cls)
            with lock:
                objects.append(o)

        threads = [threading.Thread(target=target) for i in range(count)]

        for t in threads:
            t.start()

        self.event.set()

        for t in threads:
            t.join()

        return objects

    def test_injection_is_thread_safe(self):
        objects = self.gather_results(2)
        assert len(objects) == 2

    def test_singleton_scope_is_thread_safe(self):
        self.injector.binder.bind(self.cls, scope=singleton)
        a, b = self.gather_results(2)
        assert a is b


def test_provider_and_scope_decorator_collaboration():
    @provider
    @singleton
    def provider_singleton() -> int:
        return 10

    @singleton
    @provider
    def singleton_provider() -> int:
        return 10

    assert provider_singleton.__binding__.scope == SingletonScope
    assert singleton_provider.__binding__.scope == SingletonScope


def test_injecting_into_method_of_object_that_is_falseish_works():
    # regression test

    class X(dict):
        @inject
        def __init__(self, s: str):
            pass

    injector = Injector()
    injector.get(X)


Name = NewType("Name", str)
Message = NewType("Message", str)


def test_callable_provider_injection():
    @inject
    def create_message(name: Name):
        return "Hello, " + name

    def configure(binder):
        binder.bind(Name, to="John")
        binder.bind(Message, to=create_message)

    injector = Injector([configure])
    msg = injector.get(Message)
    assert msg == "Hello, John"


def test_providerof():
    counter = [0]

    def provide_str():
        counter[0] += 1
        return 'content'

    def configure(binder):
        binder.bind(str, to=provide_str)

    injector = Injector(configure)

    assert counter[0] == 0

    provider = injector.get(ProviderOf[str])
    assert counter[0] == 0

    assert provider.get() == 'content'
    assert counter[0] == 1

    assert provider.get() == injector.get(str)
    assert counter[0] == 3


def test_providerof_cannot_be_bound():
    def configure(binder):
        binder.bind(ProviderOf[int], to=InstanceProvider(None))

    with pytest.raises(Exception):
        Injector(configure)


def test_providerof_is_safe_to_use_with_multiple_injectors():
    def configure1(binder):
        binder.bind(int, to=1)

    def configure2(binder):
        binder.bind(int, to=2)

    injector1 = Injector(configure1)
    injector2 = Injector(configure2)

    provider_of = ProviderOf[int]

    provider1 = injector1.get(provider_of)
    provider2 = injector2.get(provider_of)

    assert provider1.get() == 1
    assert provider2.get() == 2


def test_special_interfaces_work_with_auto_bind_disabled():
    class InjectMe:
        pass

    def configure(binder):
        binder.bind(InjectMe, to=InstanceProvider(InjectMe()))

    injector = Injector(configure, auto_bind=False)

    # This line used to fail with:
    # Traceback (most recent call last):
    #   File "/projects/injector/injector_test.py", line 1171,
    #   in test_auto_bind_disabled_regressions
    #     injector.get(ProviderOf(InjectMe))
    #   File "/projects/injector/injector.py", line 687, in get
    #     binding = self.binder.get_binding(None, key)
    #   File "/projects/injector/injector.py", line 459, in get_binding
    #     raise UnsatisfiedRequirement(cls, key)
    # UnsatisfiedRequirement: unsatisfied requirement on
    # <injector.ProviderOf object at 0x10ff01550>
    injector.get(ProviderOf[InjectMe])

    # This used to fail with an error similar to the ProviderOf one
    injector.get(ClassAssistedBuilder[InjectMe])


def test_binding_an_instance_regression():
    text = b'hello'.decode()

    def configure(binder):
        # Yes, this binding doesn't make sense strictly speaking but
        # it's just a sample case.
        binder.bind(bytes, to=text)

    injector = Injector(configure)
    # This used to return empty bytes instead of the expected string
    assert injector.get(bytes) == text


class PartialB:
    @inject
    def __init__(self, a: EmptyClass, b: str):
        self.a = a
        self.b = b


def test_class_assisted_builder_of_partially_injected_class_old():
    class C:
        @inject
        def __init__(self, a: EmptyClass, builder: ClassAssistedBuilder[PartialB]):
            self.a = a
            self.b = builder.build(b='C')

    c = Injector().get(C)
    assert isinstance(c, C)
    assert isinstance(c.b, PartialB)
    assert isinstance(c.b.a, EmptyClass)


class ImplicitA:
    pass


class ImplicitB:
    @inject
    def __init__(self, a: ImplicitA):
        self.a = a


class ImplicitC:
    @inject
    def __init__(self, b: ImplicitB):
        self.b = b


def test_implicit_injection_for_python3():
    injector = Injector()
    c = injector.get(ImplicitC)
    assert isinstance(c, ImplicitC)
    assert isinstance(c.b, ImplicitB)
    assert isinstance(c.b.a, ImplicitA)


def test_annotation_based_injection_works_in_provider_methods():
    class MyModule(Module):
        def configure(self, binder):
            binder.bind(int, to=42)

        @provider
        def provide_str(self, i: int) -> str:
            return str(i)

        @singleton
        @provider
        def provide_object(self) -> object:
            return object()

    injector = Injector(MyModule)
    assert injector.get(str) == '42'
    assert injector.get(object) is injector.get(object)


class Fetcher:
    def fetch(self, user_id):
        assert user_id == 333
        return {'name': 'John'}


class Processor:
    @noninjectable('provider_id')
    @inject
    @noninjectable('user_id')
    def __init__(self, fetcher: Fetcher, user_id: int, provider_id: str):
        assert provider_id == 'not injected'
        data = fetcher.fetch(user_id)
        self.name = data['name']


def test_assisted_building_is_supported():
    def configure(binder):
        binder.bind(int, to=897)
        binder.bind(str, to='injected')

    injector = Injector(configure)
    processor_builder = injector.get(AssistedBuilder[Processor])

    with pytest.raises(CallError):
        processor_builder.build()

    processor = processor_builder.build(user_id=333, provider_id='not injected')
    assert processor.name == 'John'


def test_raises_when_noninjectable_arguments_defined_with_invalid_arguments():
    with pytest.raises(UnknownArgument):

        class A:
            @inject
            @noninjectable('c')
            def __init__(self, b: str):
                self.b = b


def test_can_create_instance_with_untyped_noninjectable_argument():
    class Parent:
        @inject
        @noninjectable('child1', 'child2')
        def __init__(self, child1, *, child2):
            self.child1 = child1
            self.child2 = child2

    injector = Injector()
    parent_builder = injector.get(AssistedBuilder[Parent])
    parent = parent_builder.build(child1='injected1', child2='injected2')

    assert parent.child1 == 'injected1'
    assert parent.child2 == 'injected2'


def test_implicit_injection_fails_when_annotations_are_missing():
    class A:
        def __init__(self, n):
            self.n = n

    injector = Injector()
    with pytest.raises(CallError):
        injector.get(A)


def test_injection_works_in_presence_of_return_value_annotation():
    # Code with PEP 484-compatible type hints will have __init__ methods
    # annotated as returning None[1] and this didn't work well with Injector.
    #
    # [1] https://www.python.org/dev/peps/pep-0484/#the-meaning-of-annotations

    class A:
        @inject
        def __init__(self, s: str) -> None:
            self.s = s

    def configure(binder):
        binder.bind(str, to='this is string')

    injector = Injector([configure])

    # Used to fail with:
    # injector.UnknownProvider: couldn't determine provider for None to None
    a = injector.get(A)

    # Just a sanity check, if the code above worked we're almost certain
    # we're good but just in case the return value annotation handling changed
    # something:
    assert a.s == 'this is string'


def test_things_dont_break_in_presence_of_args_or_kwargs():
    class A:
        @inject
        def __init__(self, s: str, *args: int, **kwargs: str):
            assert not args
            assert not kwargs

    injector = Injector()

    # The following line used to fail with something like this:
    # Traceback (most recent call last):
    #   File "/ve/injector/injector_test_py3.py", line 192,
    #     in test_things_dont_break_in_presence_of_args_or_kwargs
    #     injector.get(A)
    #   File "/ve/injector/injector.py", line 707, in get
    #     result = scope_instance.get(key, binding.provider).get(self)
    #   File "/ve/injector/injector.py", line 142, in get
    #     return injector.create_object(self._cls)
    #   File "/ve/injector/injector.py", line 744, in create_object
    #     init(instance, **additional_kwargs)
    #   File "/ve/injector/injector.py", line 1082, in inject
    #     kwargs=kwargs
    #   File "/ve/injector/injector.py", line 851, in call_with_injection
    #     **dependencies)
    #   File "/ve/injector/injector_test_py3.py", line 189, in __init__
    #     assert not kwargs
    #   AssertionError: assert not {'args': 0, 'kwargs': ''}
    injector.get(A)


def test_forward_references_in_annotations_are_handled():
    # See https://www.python.org/dev/peps/pep-0484/#forward-references for details

    class CustomModule(Module):
        @provider
        def provide_x(self) -> 'X':
            return X('hello')

    @inject
    def fun(s: 'X') -> 'X':
        return s

    # The class needs to be module-global in order for the string -> object
    # resolution mechanism to work. I could make it work with locals but it
    # doesn't seem worth it.
    global X

    class X:
        def __init__(self, message: str) -> None:
            self.message = message

    try:
        injector = Injector(CustomModule)
        assert injector.call_with_injection(fun).message == 'hello'
    finally:
        del X


def test_more_useful_exception_is_raised_when_parameters_type_is_any():
    @inject
    def fun(a: Any) -> None:
        pass

    injector = Injector()

    # This was the exception before:
    #
    # TypeError: Cannot instantiate <class 'typing.AnyMeta'>
    #
    # Now:
    #
    # injector.CallError: Call to AnyMeta.__new__() failed: Cannot instantiate
    #   <class 'typing.AnyMeta'> (injection stack: ['injector_test_py3'])
    #
    # In this case the injection stack doesn't provide too much information but
    # it quickly gets helpful when the stack gets deeper.
    with pytest.raises((CallError, TypeError)):
        injector.call_with_injection(fun)


def test_optionals_are_ignored_for_now():
    @inject
    def fun(s: str = None):
        return s

    assert Injector().call_with_injection(fun) == ''


def test_explicitly_passed_parameters_override_injectable_values():
    # The class needs to be defined globally for the 'X' forward reference to be able to be resolved.
    global X

    # We test a method on top of regular function to exercise the code path that's
    # responsible for handling methods.
    class X:
        @inject
        def method(self, s: str) -> str:
            return s

        @inject
        def method_typed_self(self: 'X', s: str) -> str:
            return s

    @inject
    def function(s: str) -> str:
        return s

    injection_counter = 0

    def provide_str() -> str:
        nonlocal injection_counter
        injection_counter += 1
        return 'injected string'

    def configure(binder: Binder) -> None:
        binder.bind(str, to=provide_str)

    injector = Injector([configure])
    x = X()

    try:
        assert injection_counter == 0

        assert injector.call_with_injection(x.method) == 'injected string'
        assert injection_counter == 1
        assert injector.call_with_injection(x.method_typed_self) == 'injected string'
        assert injection_counter == 2
        assert injector.call_with_injection(function) == 'injected string'
        assert injection_counter == 3

        assert injector.call_with_injection(x.method, args=('passed string',)) == 'passed string'
        assert injection_counter == 3
        assert injector.call_with_injection(x.method_typed_self, args=('passed string',)) == 'passed string'
        assert injection_counter == 3
        assert injector.call_with_injection(function, args=('passed string',)) == 'passed string'
        assert injection_counter == 3

        assert injector.call_with_injection(x.method, kwargs={'s': 'passed string'}) == 'passed string'
        assert injection_counter == 3
        assert (
            injector.call_with_injection(x.method_typed_self, kwargs={'s': 'passed string'})
            == 'passed string'
        )
        assert injection_counter == 3
        assert injector.call_with_injection(function, kwargs={'s': 'passed string'}) == 'passed string'
        assert injection_counter == 3
    finally:
        del X


class AssistedB:
    @inject
    def __init__(self, a: EmptyClass, b: str):
        self.a = a
        self.b = b


def test_class_assisted_builder_of_partially_injected_class():
    class C:
        @inject
        def __init__(self, a: EmptyClass, builder: ClassAssistedBuilder[AssistedB]):
            self.a = a
            self.b = builder.build(b='C')

    c = Injector().get(C)
    assert isinstance(c, C)
    assert isinstance(c.b, AssistedB)
    assert isinstance(c.b.a, EmptyClass)


# The test taken from Alec Thomas' pull request: https://github.com/alecthomas/injector/pull/73
def test_child_scope():
    TestKey = NewType('TestKey', str)
    TestKey2 = NewType('TestKey2', str)

    def parent_module(binder):
        binder.bind(TestKey, to='in parent', scope=singleton)

    def first_child_module(binder):
        binder.bind(TestKey2, to='in first child', scope=singleton)

    def second_child_module(binder):
        binder.bind(TestKey2, to='in second child', scope=singleton)

    injector = Injector(modules=[parent_module])
    first_child_injector = injector.create_child_injector(modules=[first_child_module])
    second_child_injector = injector.create_child_injector(modules=[second_child_module])

    assert first_child_injector.get(TestKey) is first_child_injector.get(TestKey)
    assert first_child_injector.get(TestKey) is second_child_injector.get(TestKey)
    assert first_child_injector.get(TestKey2) is not second_child_injector.get(TestKey2)


def test_custom_scopes_work_as_expected_with_child_injectors():
    class CustomSingletonScope(SingletonScope):
        pass

    custom_singleton = ScopeDecorator(CustomSingletonScope)

    def parent_module(binder):
        binder.bind(str, to='parent value', scope=custom_singleton)

    def child_module(binder):
        binder.bind(str, to='child value', scope=custom_singleton)

    parent = Injector(modules=[parent_module])
    child = parent.create_child_injector(modules=[child_module])
    print('parent, child: %s, %s' % (parent, child))
    assert parent.get(str) == 'parent value'
    assert child.get(str) == 'child value'


# Test for https://github.com/alecthomas/injector/issues/75
def test_inject_decorator_does_not_break_manual_construction_of_pyqt_objects():
    class PyQtFake:
        @inject
        def __init__(self):
            pass

        def __getattribute__(self, item):
            if item == '__injector__':
                raise RuntimeError(
                    'A PyQt class would raise this exception if getting '
                    'self.__injector__ before __init__ is called and '
                    'self.__injector__ has not been set by Injector.'
                )
            return object.__getattribute__(self, item)

    instance = PyQtFake()  # This used to raise the exception

    assert isinstance(instance, PyQtFake)


def test_using_an_assisted_builder_with_a_provider_raises_an_injector_error():
    class MyModule(Module):
        @provider
        def provide_a(self, builder: AssistedBuilder[EmptyClass]) -> EmptyClass:
            return builder.build()

    injector = Injector(MyModule)

    with pytest.raises(Error):
        injector.get(EmptyClass)


def test_newtype_integration_works():
    UserID = NewType('UserID', int)

    def configure(binder):
        binder.bind(UserID, to=123)

    injector = Injector([configure])
    assert injector.get(UserID) == 123


@pytest.mark.skipif(sys.version_info < (3, 6), reason="Requires Python 3.6+")
def test_dataclass_integration_works():
    import dataclasses

    # Python 3.6+-only syntax below
    exec(
        """
@inject
@dataclasses.dataclass
class Data:
    name: str
    """,
        locals(),
        globals(),
    )

    def configure(binder):
        binder.bind(str, to='data')

    injector = Injector([configure])
    assert injector.get(Data).name == 'data'


def test_get_bindings():
    def function1(a: int) -> None:
        pass

    assert get_bindings(function1) == {}

    @inject
    def function2(a: int) -> None:
        pass

    assert get_bindings(function2) == {'a': int}

    @inject
    @noninjectable('b')
    def function3(a: int, b: str) -> None:
        pass

    assert get_bindings(function3) == {'a': int}

    # Let's verify that the inject/noninjectable ordering doesn't matter
    @noninjectable('b')
    @inject
    def function3b(a: int, b: str) -> None:
        pass

    assert get_bindings(function3b) == {'a': int}

    if HAVE_ANNOTATED:
        # The simple case of no @inject but injection requested with Inject[...]
        def function4(a: Inject[int], b: str) -> None:
            pass

        assert get_bindings(function4) == {'a': int}

        # Using @inject with Inject is redundant but it should not break anything
        @inject
        def function5(a: Inject[int], b: str) -> None:
            pass

        assert get_bindings(function5) == {'a': int, 'b': str}

        # We need to be able to exclude a parameter from injection with NoInject
        @inject
        def function6(a: int, b: NoInject[str]) -> None:
            pass

        assert get_bindings(function6) == {'a': int}

        # The presence of NoInject should not trigger anything on its own
        def function7(a: int, b: NoInject[str]) -> None:
            pass

        assert get_bindings(function7) == {}

        # There was a bug where in case of multiple NoInject-decorated parameters only the first one was
        # actually made noninjectable and we tried to inject something we couldn't possibly provide
        # into the second one.
        @inject
        def function8(a: NoInject[int], b: NoInject[int]) -> None:
            pass

        assert get_bindings(function8) == {}
