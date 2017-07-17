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
from typing import Any
import abc
import threading
import traceback
import warnings

import pytest

from injector import (
    Binder, CallError, Injector, Scope, InstanceProvider, ClassProvider,
    inject, noninjectable, singleton, threadlocal, UnsatisfiedRequirement,
    CircularDependency, Module, Key, SingletonScope,
    ScopeDecorator, with_injector, AssistedBuilder, BindingKey,
    SequenceKey, MappingKey, provider, ProviderOf, ClassAssistedBuilder,
    NoScope)


def prepare_basic_injection():
    class B:
        pass

    class A:
        @inject
        def __init__(self, b: B):
            """Construct a new A."""
            self.b = b

    return A, B


def prepare_nested_injectors():
    def configure(binder):
        binder.bind(str, to='asd')

    parent = Injector(configure)
    child = parent.create_child_injector()
    return parent, child


def check_exception_contains_stuff(exception, stuff):
    stringified = str(exception)

    for thing in stuff:
        assert thing in stringified, (
            '%r should be present in the exception representation: %s' % (
                thing, stringified))


def test_child_injector_inherits_parent_bindings():
    parent, child = prepare_nested_injectors()
    assert (child.get(str) == parent.get(str))


def test_child_injector_overrides_parent_bindings():
    parent, child = prepare_nested_injectors()
    child.binder.bind(str, to='qwe')

    assert ((parent.get(str), child.get(str)) == ('asd', 'qwe'))

def test_child_injector_rebinds_arguments_for_parent_scope():
    I = Key("interface")
    Cls = Key("test_class")

    class A:
        @inject
        def __init__(self, val: I):
            self.val = val

    def configure_parent(binder):
        binder.bind(Cls, to=A)
        binder.bind(I, to="Parent")

    def configure_child(binder):
        binder.bind(I, to="Child")

    parent = Injector(configure_parent)
    assert (parent.get(Cls).val == "Parent")
    child = parent.create_child_injector(configure_child)
    assert (child.get(Cls).val == "Child")

def test_scopes_are_only_bound_to_root_injector():
    parent, child = prepare_nested_injectors()

    class A:
        pass

    parent.binder.bind(A, to=A, scope=singleton)
    assert (parent.get(A) is child.get(A))


def test_key_cannot_be_instantiated():
    Interface = Key('Interface')

    with pytest.raises(Exception):
        Interface()

    with pytest.raises(Exception):
        Injector().get(Interface)


def test_get_default_injected_instances():
    A, B = prepare_basic_injection()

    def configure(binder):
        binder.bind(A)
        binder.bind(B)

    injector = Injector(configure)
    assert (injector.get(Injector) is injector)
    assert (injector.get(Binder) is injector.binder)


def test_instantiate_injected_method():
    A, _ = prepare_basic_injection()
    a = A('Bob')
    assert (a.b == 'Bob')


def test_method_decorator_is_wrapped():
    A, _ = prepare_basic_injection()
    assert (A.__init__.__doc__ == 'Construct a new A.')
    assert (A.__init__.__name__ == '__init__')


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
    A, B = prepare_basic_injection()

    def configure(binder):
        binder.bind(A)
        binder.bind(B)

    injector = Injector(configure)
    a = injector.get(A)
    assert (isinstance(a, A))
    assert (isinstance(a.b, B))


def test_configure_multiple_modules():
    A, B = prepare_basic_injection()

    def configure_a(binder):
        binder.bind(A)

    def configure_b(binder):
        binder.bind(B)

    injector = Injector([configure_a, configure_b])
    a = injector.get(A)
    assert (isinstance(a, A))
    assert (isinstance(a.b, B))


def test_inject_with_missing_dependency():
    A, _ = prepare_basic_injection()

    def configure(binder):
        binder.bind(A)

    injector = Injector(configure, auto_bind=False)
    with pytest.raises(UnsatisfiedRequirement):
        injector.get(A)


def test_inject_named_interface():
    class B:
        pass

    class A:
        @inject
        def __init__(self, b: B):
            self.b = b

    def configure(binder):
        binder.bind(A)
        binder.bind(B)

    injector = Injector(configure)
    a = injector.get(A)
    assert (isinstance(a, A))
    assert (isinstance(a.b, B))


def prepare_transitive_injection():
    class C:
        pass

    class B:
        @inject
        def __init__(self, c: C):
            self.c = c

    class A:
        @inject
        def __init__(self, b: B):
            self.b = b

    return A, B, C


def test_transitive_injection():
    A, B, C = prepare_transitive_injection()

    def configure(binder):
        binder.bind(A)
        binder.bind(B)
        binder.bind(C)

    injector = Injector(configure)
    a = injector.get(A)
    assert (isinstance(a, A))
    assert (isinstance(a.b, B))
    assert (isinstance(a.b.c, C))


def test_transitive_injection_with_missing_dependency():
    A, B, _ = prepare_transitive_injection()

    def configure(binder):
        binder.bind(A)
        binder.bind(B)

    injector = Injector(configure, auto_bind=False)
    with pytest.raises(UnsatisfiedRequirement):
        injector.get(A)
    with pytest.raises(UnsatisfiedRequirement):
        injector.get(B)


def test_inject_singleton():
    class B:
        pass

    class A:
        @inject
        def __init__(self, b: B):
            self.b = b

    def configure(binder):
        binder.bind(A)
        binder.bind(B, scope=SingletonScope)

    injector1 = Injector(configure)
    a1 = injector1.get(A)
    a2 = injector1.get(A)
    assert (a1.b is a2.b)


def test_inject_decorated_singleton_class():
    @singleton
    class B:
        pass

    class A:
        @inject
        def __init__(self, b: B):
            self.b = b

    def configure(binder):
        binder.bind(A)
        binder.bind(B)

    injector1 = Injector(configure)
    a1 = injector1.get(A)
    a2 = injector1.get(A)
    assert (a1.b is a2.b)


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

    assert (a1 is a2)

    a3 = [None]
    ready = threading.Event()

    def inject_a3():
        a3[0] = injector.get(A)
        ready.set()

    threading.Thread(target=inject_a3).start()
    ready.wait(1.0)

    assert (a2 is not a3[0] and a3[0] is not None)


def test_injecting_interface_implementation():
    class Interface:
        pass

    class Implementation:
        pass

    class A:
        @inject
        def __init__(self, i: Interface):
            self.i = i

    def configure(binder):
        binder.bind(A)
        binder.bind(Interface, to=Implementation)

    injector = Injector(configure)
    a = injector.get(A)
    assert (isinstance(a.i, Implementation))


def test_cyclic_dependencies():
    class Interface:
        pass

    class A:
        @inject
        def __init__(self, i: Interface):
            self.i = i

    class B:
        @inject
        def __init__(self, a: A):
            self.a = a

    def configure(binder):
        binder.bind(Interface, to=B)
        binder.bind(A)

    injector = Injector(configure)
    with pytest.raises(CircularDependency):
        injector.get(A)


def test_dependency_cycle_can_be_worked_broken_by_assisted_building():
    class Interface:
        pass

    class A:
        @inject
        def __init__(self, i: Interface):
            self.i = i

    class B:
        @inject
        def __init__(self, a_builder: AssistedBuilder[A]):
            self.a = a_builder.build(i=self)

    def configure(binder):
        binder.bind(Interface, to=B)
        binder.bind(A)

    injector = Injector(configure)

    # Previously it'd detect a circular dependency here:
    # 1. Constructing A requires Interface (bound to B)
    # 2. Constructing B requires assisted build of A
    # 3. Constructing A triggers circular dependency check
    assert isinstance(injector.get(A), A)


def test_that_injection_is_lazy():
    class Interface:
        constructed = False

        def __init__(self):
            Interface.constructed = True

    class A:
        @inject
        def __init__(self, i: Interface):
            self.i = i

    def configure(binder):
        binder.bind(Interface)
        binder.bind(A)

    injector = Injector(configure)
    assert not (Interface.constructed)
    injector.get(A)
    assert (Interface.constructed)


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
    assert (injector.get(str) == name)


def test_with_injector_works():
    name = 'Victoria'

    def configure(binder):
        binder.bind(str, to=name)

    class Aaa:
        @with_injector(configure)
        @inject
        def __init__(self, username: str):
            self.username = username

    aaa = Aaa()
    assert (aaa.username == name)


def test_bind_using_key():
    Name = Key('name')
    Age = Key('age')

    class MyModule(Module):
        @provider
        def provider_name(self) -> Name:
            return 'Bob'

        def configure(self, binder):
            binder.bind(Age, to=25)

    injector = Injector(MyModule())
    assert (injector.get(Age) == 25)
    assert (injector.get(Name) == 'Bob')


def test_inject_using_key():
    Name = Key('name')
    Description = Key('description')

    class MyModule(Module):
        @provider
        def provide_name(self) -> Name:
            return 'Bob'

        @provider
        @inject
        def provide_description(self, name: Name) -> Description:
            return '%s is cool!' % name

    assert (Injector(MyModule()).get(Description) == 'Bob is cool!')


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

    assert (Injector(MyModule()).get(str) == 'Bob is 25 and weighs 50.0kg')


def test_multibind():
    Names = Key('names')

    def configure_one(binder):
        binder.multibind(Names, to=['Bob'])

    def configure_two(binder):
        binder.multibind(Names, to=['Tom'])

    assert (Injector([configure_one, configure_two]).get(Names) == ['Bob', 'Tom'])


def test_provider_sequence_decorator():
    Names = SequenceKey('names')

    class MyModule(Module):
        @provider
        def bob(self) -> Names:
            return ['Bob']

        @provider
        def tom(self) -> Names:
            return ['Tom']

    assert (Injector(MyModule()).get(Names) == ['Bob', 'Tom'])


def test_auto_bind():

    class A:
        pass

    injector = Injector()
    assert (isinstance(injector.get(A), A))


def test_custom_scope():
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

    class Request:
        pass

    @request
    class Handler:
        def __init__(self, request):
            self.request = request

    class RequestModule(Module):
        def configure(self, binder):
            binder.bind_scope(RequestScope)

        @provider
        @inject
        def handler(self, request: Request) -> Handler:
            return Handler(request)

    injector = Injector([RequestModule()], auto_bind=False)

    with pytest.raises(UnsatisfiedRequirement):
        injector.get(Handler)

    scope = injector.get(RequestScope)
    request = Request()

    with scope(request):
        handler = injector.get(Handler)
        assert (handler.request is request)

    with pytest.raises(UnsatisfiedRequirement):
        injector.get(Handler)


def test_bind_interface_of_list_of_types():

    def configure(binder):
        binder.multibind([int], to=[1, 2, 3])
        binder.multibind([int], to=[4, 5, 6])

    injector = Injector(configure)
    assert (injector.get([int]) == [1, 2, 3, 4, 5, 6])


def test_provider_mapping():

    StrInt = MappingKey('StrInt')

    def configure(binder):
        binder.multibind(StrInt, to={'one': 1})
        binder.multibind(StrInt, to={'two': 2})

    class MyModule(Module):
        @provider
        def provide_numbers(self) -> StrInt:
            return {'three': 3}

        @provider
        def provide_more_numbers(self) -> StrInt:
            return {'four': 4}

    injector = Injector([configure, MyModule()])
    assert (injector.get(StrInt) == {'one': 1, 'two': 2, 'three': 3, 'four': 4})


def test_binder_install():
    class ModuleA(Module):
        def configure(self, binder):
            binder.bind(str, to='hello world')

    class ModuleB(Module):
        def configure(self, binder):
            binder.install(ModuleA())

    injector = Injector([ModuleB()])
    assert (injector.get(str) == 'hello world')


def test_binder_provider_for_method_with_explicit_provider():
    injector = Injector()
    binder = injector.binder
    provider = binder.provider_for(int, to=InstanceProvider(1))
    assert (type(provider) is InstanceProvider)
    assert (provider.get(injector) == 1)


def test_binder_provider_for_method_with_instance():
    injector = Injector()
    binder = injector.binder
    provider = binder.provider_for(int, to=1)
    assert (type(provider) is InstanceProvider)
    assert (provider.get(injector) == 1)


def test_binder_provider_for_method_with_class():
    injector = Injector()
    binder = injector.binder
    provider = binder.provider_for(int)
    assert (type(provider) is ClassProvider)
    assert (provider.get(injector) == 0)


def test_binder_provider_for_method_with_class_to_specific_subclass():
    class A:
        pass

    class B(A):
        pass

    injector = Injector()
    binder = injector.binder
    provider = binder.provider_for(A, B)
    assert (type(provider) is ClassProvider)
    assert (isinstance(provider.get(injector), B))


def test_binder_provider_for_type_with_metaclass():
    # use a metaclass cross python2/3 way
    # otherwise should be:
    # class A(object, metaclass=abc.ABCMeta):
    #    passa
    A = abc.ABCMeta('A', (object, ), {})

    injector = Injector()
    binder = injector.binder
    assert (isinstance(binder.provider_for(A, None).get(injector), A))


def test_injecting_undecorated_class_with_missing_dependencies_raises_the_right_error():
    class ClassA:
        def __init__(self, parameter):
            pass

    class ClassB:
        @inject
        def __init__(self, a: ClassA):
            pass

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
    assert ((obj.a, obj.b) == (str(), 123))


def test_assisted_builder_works_when_injected():
    class X:
        @inject
        def __init__(self, builder: AssistedBuilder[NeedsAssistance]):
            self.obj = builder.build(b=234)

    injector = Injector()
    x = injector.get(X)
    assert ((x.obj.a, x.obj.b) == (str(), 234))


def test_assisted_builder_uses_bindings():
    Interface = Key('Interface')

    def configure(binder):
        binder.bind(Interface, to=NeedsAssistance)

    injector = Injector(configure)
    builder = injector.get(AssistedBuilder[Interface])
    x = builder.build(b=333)
    assert ((type(x), x.b) == (NeedsAssistance, 333))


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
    assert ((b1._injector, b2._injector) == (i1, i2))


def test_assisted_builder_injection_uses_the_same_binding_key_every_time():
    # if we have different BindingKey for every AssistedBuilder(...) we will get memory leak
    gen_key = lambda: BindingKey(AssistedBuilder[NeedsAssistance])
    assert gen_key() == gen_key()


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
        assert (len(objects) == 2)

    def test_singleton_scope_is_thread_safe(self):
        self.injector.binder.bind(self.cls, scope=singleton)
        a, b = self.gather_results(2)
        assert (a is b)


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


def test_injection_fails_when_injector_cant_install_itself_into_an_object_with_slots():
    try:
        class ClassName:
            __slots__ = ()

        injector = Injector()
        injector.get(ClassName)
    except Exception as e:
        check_exception_contains_stuff(e, ('ClassName', '__slots__'))
    else:
        assert False, 'Should have raised an exception and it didn\'t'


def test_deprecated_module_configure_injection():
    class Test(Module):
        @inject
        def configure(self, binder, name: int):
            pass

    class Test2(Module):
        @inject
        def __init__(self, name: int):
            pass

    @inject
    def configure(binder, name: int):
        pass

    for module in [Test, Test2, configure, Test()]:
        with warnings.catch_warnings(record=True) as w:
            print(module)
            Injector(module)
        assert len(w) == 1, w


def test_callable_provider_injection():
    Name = Key("Name")
    Message = Key("Message")

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


def test_class_assisted_builder_of_partially_injected_class_old():
    class A:
        pass

    class B:
        @inject
        def __init__(self, a: A, b: str):
            self.a = a
            self.b = b

    class C:
        @inject
        def __init__(self, a: A, builder: ClassAssistedBuilder[B]):
            self.a = a
            self.b = builder.build(b='C')

    c = Injector().get(C)
    assert isinstance(c, C)
    assert isinstance(c.b, B)
    assert isinstance(c.b.a, A)


def test_implicit_injection_for_python3():
    class A:
        pass

    class B:
        @inject
        def __init__(self, a:A):
            self.a = a

    class C:
        @inject
        def __init__(self, b:B):
            self.b = b

    injector = Injector()
    c = injector.get(C)
    assert isinstance(c, C)
    assert isinstance(c.b, B)
    assert isinstance(c.b.a, A)


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


def test_assisted_building_is_supported():
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

    def configure(binder):
        binder.bind(int, to=897)
        binder.bind(str, to='injected')

    injector = Injector(configure)
    processor_builder = injector.get(AssistedBuilder[Processor])

    with pytest.raises(CallError):
        processor_builder.build()

    processor = processor_builder.build(user_id=333, provider_id='not injected')
    assert processor.name == 'John'


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
    def configure(binder):
        binder.bind(X, to=X('hello'))

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
        injector = Injector(configure)
        injector.call_with_injection(fun).message == 'hello'
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


def test_class_assisted_builder_of_partially_injected_class():
    class A:
        pass

    class B:
        @inject
        def __init__(self, a: A, b: str):
            self.a = a
            self.b = b

    class C:
        @inject
        def __init__(self, a: A, builder: ClassAssistedBuilder[B]):
            self.a = a
            self.b = builder.build(b='C')

    c = Injector().get(C)
    assert isinstance(c, C)
    assert isinstance(c.b, B)
    assert isinstance(c.b.a, A)


def test_default_scope_settings():
    class A:
        pass

    i1 = Injector()
    assert i1.get(A) is not i1.get(A)

    i2 = Injector(scope=SingletonScope)
    assert i2.get(A) is i2.get(A)


def test_default_scope_parents():
    class A:
        pass

    parent = Injector(scope=SingletonScope)
    child1 = Injector(parent=parent)
    child2 = Injector(parent=parent, scope=NoScope)

    assert child1.scope == SingletonScope
    assert child2.scope == NoScope
