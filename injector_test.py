# encoding: utf-8
#
# Copyright (C) 2010 Alec Thomas <alec@swapoff.org>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#
# Author: Alec Thomas <alec@swapoff.org>

"""Functional tests for the Pollute dependency injection framework."""

from contextlib import contextmanager
import abc
import threading

import pytest

from injector import (Binder, CallError, Injector, Scope, InstanceProvider, ClassProvider,
        inject, singleton, threadlocal, UnsatisfiedRequirement,
        CircularDependency, Module, provides, Key, extends, SingletonScope,
        ScopeDecorator, with_injector, AssistedFactoryProvider)


def prepare_basic_injection():
    class B(object):
        pass

    class A(object):
        @inject(b=B)
        def __init__(self, b):
            """Construct a new A."""
            self.b = b

    return A, B


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
        @provides(str, annotation='name')
        def provide_name(self):
            return 'Bob'

    module = MyModule()
    injector = Injector(module)
    assert (injector.get(str, annotation='name') == 'Bob')

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


def test_extends_decorator():
    Names = Key('names')

    class MyModule(Module):
        @extends(Names)
        def bob(self):
            return ['Bob']

        @extends(Names)
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
                provider = InstanceProvider(provider.get())
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


def test_map_binding_and_extends():

    def configure(binder):
        binder.multibind({str: int}, to={'one': 1})
        binder.multibind({str: int}, to={'two': 2})

    class MyModule(Module):
        @extends({str: int})
        def provide_numbers(self):
            return {'three': 3}

        @extends({str: int})
        def provide_more_numbers(self):
            return {'four': 4}

    injector = Injector([configure, MyModule()])
    assert (injector.get({str: int}) ==
                 {'one': 1, 'two': 2, 'three': 3, 'four': 4})


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
    binder = Injector().binder
    provider = binder.provider_for(int, to=InstanceProvider(1))
    assert (type(provider) is InstanceProvider)
    assert (provider.get() == 1)


def test_binder_provider_for_method_with_instance():
    binder = Injector().binder
    provider = binder.provider_for(int, to=1)
    assert (type(provider) is InstanceProvider)
    assert (provider.get() == 1)


def test_binder_provider_for_method_with_class():
    binder = Injector().binder
    provider = binder.provider_for(int)
    assert (type(provider) is ClassProvider)
    assert (provider.get() == 0)


def test_binder_provider_for_method_with_class_to_specific_subclass():
    class A(object):
        pass

    class B(A):
        pass

    binder = Injector().binder
    provider = binder.provider_for(A, B)
    assert (type(provider) is ClassProvider)
    assert (isinstance(provider.get(), B))


def test_binder_provider_for_type_with_metaclass():
    # use a metaclass cross python2/3 way
    # otherwise should be:
    # class A(object, metaclass=abc.ABCMeta):
    #    passa
    A = abc.ABCMeta('A', (object, ), {})

    binder = Injector().binder
    assert (isinstance(binder.provider_for(A, None).get(), A))

def test_injecting_undecorated_class_with_missing_dependencies_raises_the_right_error():
    class A(object):
        def __init__(self, parameter):
            pass

    class B(object):
        @inject(a = A)
        def __init__(self, a):
            pass

    injector = Injector()
    try:
        b = injector.get(B)
    except CallError as ce:
        function = A.__init__

        # Python 3 compatibility
        try:
            function = function.__func__
        except AttributeError:
            pass
        assert (ce.args[1] == function)

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

def test_assisted_factory_provider_works():
    class A(object):
        @inject(aaa=str)
        def __init__(self, aaa, bbb):
            self.aaa = aaa
            self.bbb = bbb

    AFactory = Key('AFactory')
    def conf(binder):
        binder.bind(AFactory, to=AssistedFactoryProvider(A))

    injector = Injector(conf)
    factory = injector.get(AFactory)
    a = factory.create(bbb=123)
    assert (a.aaa == str())
    assert (a.bbb == 123)
