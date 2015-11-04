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
import abc
import threading
import traceback
import warnings

import pytest

from injector import (
    Binder, CallError, Injector, Scope, InstanceProvider, ClassProvider,
    inject, singleton, threadlocal, UnsatisfiedRequirement,
    CircularDependency, Module, provides, Key, SingletonScope,
    ScopeDecorator, with_injector, AssistedBuilder, BindingKey,
    SequenceKey, MappingKey, ProviderOf,
    )


def prepare_basic_injection():
    class B(object):
        pass

    class A(object):
        @inject(b=B)
        def __init__(self, b):
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

    class A(object):
        @inject(val=I)
        def __init__(self, val):
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

    class A(object):
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
    @inject(s=str)
    def wrapped(*args, **kwargs):
        pass


def test_providers_arent_called_for_dependencies_that_are_already_provided():
    def configure(binder):
        binder.bind(int, to=lambda: 1 / 0)

    class A(object):
        @inject(i=int)
        def __init__(self, i):
            pass

    injector = Injector(configure)
    builder = injector.get(AssistedBuilder(A))

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
    class B(object):
        pass

    class A(object):
        @inject(b=B)
        def __init__(self, b):
            self.b = b

    def configure(binder):
        binder.bind(A)
        binder.bind(B)

    injector = Injector(configure)
    a = injector.get(A)
    assert (isinstance(a, A))
    assert (isinstance(a.b, B))


def prepare_transitive_injection():
    class C(object):
        pass

    class B(object):
        @inject(c=C)
        def __init__(self, c):
            self.c = c

    class A(object):
        @inject(b=B)
        def __init__(self, b):
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
    class B(object):
        pass

    class A(object):
        @inject(b=B)
        def __init__(self, b):
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
    class B(object):
        pass

    class A(object):
        @inject(b=B)
        def __init__(self, b):
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
    class A(object):
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
    class Interface(object):
        pass

    class Implementation(object):
        pass

    class A(object):
        @inject(i=Interface)
        def __init__(self, i):
            self.i = i

    def configure(binder):
        binder.bind(A)
        binder.bind(Interface, to=Implementation)

    injector = Injector(configure)
    a = injector.get(A)
    assert (isinstance(a.i, Implementation))


def test_cyclic_dependencies():
    class Interface(object):
        pass

    class A(object):
        @inject(i=Interface)
        def __init__(self, i):
            self.i = i

    class B(object):
        @inject(a=A)
        def __init__(self, a):
            self.a = a

    def configure(binder):
        binder.bind(Interface, to=B)
        binder.bind(A)

    injector = Injector(configure)
    with pytest.raises(CircularDependency):
        injector.get(A)


def test_avoid_circular_dependency_with_method_injection():
    class Interface(object):
        pass

    class A(object):
        @inject(i=Interface)
        def __init__(self, i):
            self.i = i

    # Even though A needs B (via Interface) and B.method() needs A, they are
    # resolved at different times, avoiding circular dependencies.
    class B(object):
        @inject(a=A)
        def method(self, a):
            self.a = a

    def configure(binder):
        binder.bind(Interface, to=B)
        binder.bind(A)
        binder.bind(B)

    injector = Injector(configure)
    a = injector.get(A)
    assert (isinstance(a.i, B))
    b = injector.get(B)
    b.method()
    assert (isinstance(b.a, A))


def test_that_injection_is_lazy():
    class Interface(object):
        constructed = False

        def __init__(self):
            Interface.constructed = True

    class A(object):
        @inject(i=Interface)
        def __init__(self, i):
            self.i = i

    def configure(binder):
        binder.bind(Interface)
        binder.bind(A)

    injector = Injector(configure)
    assert not (Interface.constructed)
    injector.get(A)
    assert (Interface.constructed)


def test_module_provides():
    class MyModule(Module):
        @provides(str)
        def provide_name(self):
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

    class Aaa(object):
        @with_injector(configure)
        @inject(username=str)
        def __init__(self, username):
            self.username = username

    aaa = Aaa()
    assert (aaa.username == name)


def test_bind_using_key():
    Name = Key('name')
    Age = Key('age')

    class MyModule(Module):
        @provides(Name)
        def provides_name(self):
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
        @provides(Name)
        def provide_name(self):
            return 'Bob'

        @provides(Description)
        @inject(name=Name)
        def provide_description(self, name):
            return '%s is cool!' % name

    assert (Injector(MyModule()).get(Description) == 'Bob is cool!')


def test_inject_and_provide_coexist_happily():
    class MyModule(Module):
        @provides(float)
        def provide_weight(self):
            return 50.0

        @provides(int)
        def provide_age(self):
            return 25

        # TODO(alec) Make provides/inject order independent.
        @provides(str)
        @inject(age=int, weight=float)
        def provide_description(self, age, weight):
            return 'Bob is %d and weighs %0.1fkg' % (age, weight)

    assert (Injector(MyModule()).get(str) == 'Bob is 25 and weighs 50.0kg')


def test_multibind():
    Names = Key('names')

    def configure_one(binder):
        binder.multibind(Names, to=['Bob'])

    def configure_two(binder):
        binder.multibind(Names, to=['Tom'])

    assert (Injector([configure_one, configure_two]).get(Names) == ['Bob', 'Tom'])


def test_provides_sequence_decorator():
    Names = SequenceKey('names')

    class MyModule(Module):
        @provides(Names)
        def bob(self):
            return ['Bob']

        @provides(Names)
        def tom(self):
            return ['Tom']

    assert (Injector(MyModule()).get(Names) == ['Bob', 'Tom'])


def test_auto_bind():

    class A(object):
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

    class Request(object):
        pass

    @request
    class Handler(object):
        def __init__(self, request):
            self.request = request

    class RequestModule(Module):
        def configure(self, binder):
            binder.bind_scope(RequestScope)

        @provides(Handler)
        @inject(request=Request)
        def handler(self, request):
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


def test_provides_mapping():

    StrInt = MappingKey('StrInt')

    def configure(binder):
        binder.multibind(StrInt, to={'one': 1})
        binder.multibind(StrInt, to={'two': 2})

    class MyModule(Module):
        @provides(StrInt)
        def provide_numbers(self):
            return {'three': 3}

        @provides(StrInt)
        def provide_more_numbers(self):
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
    class A(object):
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
    class ClassA(object):
        def __init__(self, parameter):
            pass

    class ClassB(object):
        @inject(a=ClassA)
        def __init__(self, a):
            pass

    injector = Injector()
    try:
        injector.get(ClassB)
    except CallError as ce:
        check_exception_contains_stuff(ce, ('ClassA.__init__', 'ClassB'))


def test_call_to_method_with_legitimate_call_error_raises_type_error():
    class A(object):
        def __init__(self):
            max()

    injector = Injector()
    with pytest.raises(TypeError):
        injector.get(A)


def test_call_to_method_containing_noninjectable_and_unsatisfied_dependencies_raises_the_right_error():
    class A(object):
        @inject(something=str)
        def fun(self, something, something_different):
            pass

    injector = Injector()
    a = injector.get(A)
    try:
        a.fun()
    except CallError as ce:
        assert (ce.args[0] == a)

        # We cannot really check for function identity here... Error is raised after calling
        # original function but from outside we have access to function already decorated
        function = A.fun

        # Python 3 compatibility
        try:
            function = function.__func__
        except AttributeError:
            pass
        assert (ce.args[1].__name__ == function.__name__)

        assert (ce.args[2] == ())
        assert (ce.args[3] == {'something': str()})


def test_call_error_is_raised_with_correct_traceback():
    class A(object):
        @inject(x=str)
        def fun_a(self, x='irrelevant'):
            raise TypeError('Something happened')

    class B(object):
        @inject(a=A)
        def fun_b(self, a):
            a.fun_a()

    injector = Injector()
    b = injector.get(B)
    try:
        b.fun_b()
    except:
        tb = traceback.format_exc()
        assert 'in fun_a' in tb


def test_call_error_str_representation_handles_single_arg():
    ce = CallError('zxc')
    assert str(ce) == 'zxc'


class NeedsAssistance(object):
    @inject(a=str)
    def __init__(self, a, b):
        self.a = a
        self.b = b


def test_assisted_builder_works_when_got_directly_from_injector():
    injector = Injector()
    builder = injector.get(AssistedBuilder(NeedsAssistance))
    obj = builder.build(b=123)
    assert ((obj.a, obj.b) == (str(), 123))


def test_assisted_builder_works_when_injected():
    class X(object):
        @inject(builder=AssistedBuilder(NeedsAssistance))
        def __init__(self, builder):
            self.obj = builder.build(b=234)

    injector = Injector()
    x = injector.get(X)
    assert ((x.obj.a, x.obj.b) == (str(), 234))


def test_assisted_builder_uses_bindings():
    Interface = Key('Interface')

    def configure(binder):
        binder.bind(Interface, to=NeedsAssistance)

    injector = Injector(configure)
    builder = injector.get(AssistedBuilder(Interface))
    x = builder.build(b=333)
    assert ((type(x), x.b) == (NeedsAssistance, 333))


def test_assisted_builder_uses_concrete_class_when_specified():
    class X(object):
        pass

    def configure(binder):
        # meant only to show that provider isn't called
        binder.bind(X, to=lambda: 1 / 0)

    injector = Injector(configure)
    builder = injector.get(AssistedBuilder(cls=X))
    builder.build()


def test_assisted_builder_accepts_callables():
    injector = Injector()
    builder = injector.get(AssistedBuilder(callable=lambda x: x * 2))
    assert builder.build(x=3) == 6


def test_assisted_builder_injection_is_safe_to_use_with_multiple_injectors():
    class X(object):
        @inject(builder=AssistedBuilder(NeedsAssistance))
        def y(self, builder):
            return builder

    i1, i2 = Injector(), Injector()
    b1 = i1.get(X).y()
    b2 = i2.get(X).y()
    assert ((b1.injector, b2.injector) == (i1, i2))


def test_assisted_builder_injection_uses_the_same_binding_key_every_time():
    # if we have different BindingKey for every AssistedBuilder(...) we will get memory leak
    gen_key = lambda: BindingKey(AssistedBuilder(NeedsAssistance))
    assert gen_key() == gen_key()


class TestThreadSafety(object):
    def setup(self):
        self.event = threading.Event()

        def configure(binder):
            binder.bind(str, to=lambda: self.event.wait() and 'this is str')

        class XXX(object):
            @inject(s=str)
            def __init__(self, s):
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


class TestClassInjection(object):
    def setup(self):
        class A(object):
            counter = 0

            def __init__(self):
                A.counter += 1

        @inject(a=A)
        class B(object):
            pass

        @inject(injectable=A)
        class C(object):
            def __init__(self, noninjectable):
                self.noninjectable = noninjectable

        self.injector = Injector()
        self.A = A
        self.B = B
        self.C = C

    def test_inject_decorator_works_when_metaclass_used(self):
        WithABCMeta = abc.ABCMeta(str('WithABCMeta'), (object,), {})

        @inject(y=int)
        class X(WithABCMeta):
            pass

        self.injector.get(X)

    def test_instantiation_still_requires_parameters(self):
        for cls in (self.B, self.C):
            with pytest.raises(Exception):
                cls()

        try:
            self.C(noninjectable=1)
            assert False, 'Should have raised an exception'
        except Exception as e:
            check_exception_contains_stuff(e, ('C.__init__', 'injectable'))

        with pytest.raises(Exception):
            self.C(injectable=self.A())

    def test_injection_works(self):
        b = self.injector.get(self.B)
        a = b.a
        assert (type(a) == self.A)

    def test_assisted_injection_works(self):
        builder = self.injector.get(AssistedBuilder(self.C))
        c = builder.build(noninjectable=5)

        assert((type(c.injectable), c.noninjectable) == (self.A, 5))

    def test_members_are_injected_only_once(self):
        b = self.injector.get(self.B)
        _1 = b.a
        _2 = b.a
        assert (self.A.counter == 1 and _1 is _2)

    def test_each_instance_gets_new_injection(self):
        count = 3
        objs = [self.injector.get(self.B).a for i in range(count)]

        assert (self.A.counter == count)
        assert (len(set(objs)) == count)

    def test_members_can_be_overwritten(self):
        b = self.injector.get(self.B)
        b.a = 123

        assert (b.a == 123)

    def test_injected_members_starting_with_underscore_generate_sane_constructor(self):
        @inject(_b=self.B)
        class X(object):
            pass

        x = self.injector.get(X)
        assert (type(x._b) == self.B)

        x = X(b=314)
        assert (x._b == 314)

    def test_correct_exception_is_raised_when_argument_is_missing(self):
        @inject(s=str)
        class X(object):
            pass

        with pytest.raises(CallError):
            self.B()

        with pytest.raises(CallError):
            self.B('something')

    def test_mutating_dict_while_iterating_it_bug(self):
        bindings = dict(('_' + str(i), str) for i in range(1000))

        @inject(**bindings)
        class X(object):
            pass

        injector = Injector()
        injector.get(X)


def test_provides_and_scope_decorator_collaboration():
    @provides(int)
    @singleton
    def provides_singleton():
        return 10

    @singleton
    @provides(int)
    def singleton_provides():
        return 10

    assert provides_singleton.__binding__.scope == SingletonScope
    assert singleton_provides.__binding__.scope == SingletonScope


def test_injecting_into_method_of_object_that_is_falseish_works():
    # regression test

    class X(dict):
        @inject(s=str)
        def __init__(self, s):
            pass

    injector = Injector()
    injector.get(X)


def test_injection_fails_when_injector_cant_install_itself_into_an_object_with_slots():
    try:
        class ClassName(object):
            __slots__ = ()

        injector = Injector()
        injector.get(ClassName)
    except Exception as e:
        check_exception_contains_stuff(e, ('ClassName', '__slots__'))
    else:
        assert False, 'Should have raised an exception and it didn\'t'


def test_injecting_function_will_work():
    @inject(s=str)
    def function(s):
        return 'Got %s' % s

    def configure(binder):
        binder.bind(str, to='123')

    injector = Injector(configure)
    wrapped = injector.get(function)
    assert wrapped.__name__ == function.__name__
    result = wrapped()
    assert result == 'Got 123'


def test_deprecated_module_configure_injection():
    class Test(Module):
        @inject(name=int)
        def configure(self, binder, name):
            pass

    class Test2(Module):
        @inject(name=int)
        def __init__(self, name):
            pass

    @inject(name=int)
    class Test3(Module):
        pass

    @inject(name=int)
    def configure(binder, name):
        pass

    for module in [Test, Test2, Test3, configure, Test()]:
        with warnings.catch_warnings(record=True) as w:
            print(module)
            Injector(module)
        assert len(w) == 1, w


def test_callable_provider_injection():
    Name = Key("Name")
    Message = Key("Message")

    @inject(name=Name)
    def create_message(name):
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

    provider = injector.get(ProviderOf(str))
    assert counter[0] == 0

    assert provider.get() == 'content'
    assert counter[0] == 1

    assert provider.get() == injector.get(str)
    assert counter[0] == 3


def test_providerof_cannot_be_bound():
    def configure(binder):
        binder.bind(ProviderOf(int), to=InstanceProvider(None))

    with pytest.raises(Exception):
        Injector(configure)


def test_providerof_is_safe_to_use_with_multiple_injectors():
    def configure1(binder):
        binder.bind(int, to=1)

    def configure2(binder):
        binder.bind(int, to=2)

    injector1 = Injector(configure1)
    injector2 = Injector(configure2)

    provider_of = ProviderOf(int)

    provider1 = injector1.get(provider_of)
    provider2 = injector2.get(provider_of)

    assert provider1.get() == 1
    assert provider2.get() == 2


def test_special_interfaces_work_with_auto_bind_disabled():
    class InjectMe(object):
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
    injector.get(ProviderOf(InjectMe))

    # This used to fail with an error similar to the ProviderOf one
    injector.get(AssistedBuilder(cls=InjectMe))
