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

from nose.tools import assert_true, assert_raises, assert_equal

from injector import Binder, Injector, Scope, InstanceProvider, inject, \
        singleton, UnsatisfiedRequirement, CircularDependency, Module, provides


class TestBasicInjection(object):
    def prepare(self):
        class B(object):
            pass

        class A(object):
            @inject(B)
            def __init__(self, b):
                """Construct a new A."""
                self.b = b

        return A, B

    def test_get_default_injected_instances(self):
        A, B = self.prepare()

        def configure(binder):
            binder.bind(A)
            binder.bind(B)

        injector = Injector(configure)
        assert_true(injector.get_instance(Injector) is injector)
        assert_true(injector.get_instance(Binder) is injector._binder)

    def test_instantiate_injected_method(self):
        A, _ = self.prepare()
        a = A('Bob')
        assert_equal(a.b, 'Bob')

    def test_method_decorator_is_wrapped(self):
        A, _ = self.prepare()
        assert_equal(A.__init__.__doc__, 'Construct a new A.')
        assert_equal(A.__init__.__name__, '__init__')

    def test_inject_direct(self):
        A, B = self.prepare()

        def configure(binder):
            binder.bind(A)
            binder.bind(B)

        injector = Injector(configure)
        a = injector.get_instance(A)
        assert_true(isinstance(a, A))
        assert_true(isinstance(a.b, B))

    def test_configure_multiple_modules(self):
        A, B = self.prepare()

        def configure_a(binder):
            binder.bind(A)

        def configure_b(binder):
            binder.bind(B)

        injector = Injector([configure_a, configure_b])
        a = injector.get_instance(A)
        assert_true(isinstance(a, A))
        assert_true(isinstance(a.b, B))

    def test_inject_with_missing_dependency(self):
        A, _ = self.prepare()

        def configure(binder):
            binder.bind(A)

        injector = Injector(configure)
        assert_raises(UnsatisfiedRequirement, injector.get_instance, A)


def test_inject_named_interface():
    class B(object):
        pass

    class A(object):
        @inject(b=B)
        def __init__(self, b):
            self.b = b

    def configure(binder):
        binder.bind(A)
        binder.bind(B, named='b')

    injector = Injector(configure)
    a = injector.get_instance(A)
    assert_true(isinstance(a, A))
    assert_true(isinstance(a.b, B))


class TestTransitiveInjection(object):
    def prepare(self):
        class C(object):
            pass

        class B(object):
            @inject(C)
            def __init__(self, c):
                self.c = c

        class A(object):
            @inject(B)
            def __init__(self, b):
                self.b = b

        return A, B, C

    def test_transitive_injection(self):
        A, B, C = self.prepare()

        def configure(binder):
            binder.bind(A)
            binder.bind(B)
            binder.bind(C)

        injector = Injector(configure)
        a = injector.get_instance(A)
        assert_true(isinstance(a, A))
        assert_true(isinstance(a.b, B))
        assert_true(isinstance(a.b.c, C))

    def test_transitive_injection_with_missing_dependency(self):
        A, B, _ = self.prepare()

        def configure(binder):
            binder.bind(A)
            binder.bind(B)

        injector = Injector(configure)
        assert_raises(UnsatisfiedRequirement, injector.get_instance, A)
        assert_raises(UnsatisfiedRequirement, injector.get_instance, B)


def test_inject_singleton():
    class B(object):
        pass

    class A(object):
        @inject(B)
        def __init__(self, b):
            self.b = b

    def configure(binder):
        binder.bind(A)
        binder.bind(B, scope=singleton)

    injector1 = Injector(configure)
    a1 = injector1.get_instance(A)
    a2 = injector1.get_instance(A)
    assert_true(a1.b is a2.b)
    injector2 = Injector(configure)
    a3 = injector2.get_instance(A)
    a4 = injector2.get_instance(A)
    assert_true(a2.b is a3.b)
    assert_true(a3.b is a4.b)


def test_inject_decorated_singleton_class():
    @singleton
    class B(object):
        pass

    class A(object):
        @inject(B)
        def __init__(self, b):
            self.b = b

    def configure(binder):
        binder.bind(A)
        binder.bind(B)

    injector1 = Injector(configure)
    a1 = injector1.get_instance(A)
    a2 = injector1.get_instance(A)
    assert_true(a1.b is a2.b)


class TestCustomScope(object):
    class ModuleScope(Scope):
        def __init__(self):
            self._cache = {}

        def get(self, key, provider):
            try:
                return self._cache[key]
            except KeyError:
                self._cache[key] = InstanceProvider(provider.get())
                return self._cache[key]

    def test_module_scope_does_not_leak(self):
        class B(object):
            pass

        class A(object):
            @inject(B)
            def __init__(self, b):
                self.b = b

        self.run(A, B)

    def test_scope_class_decorator(self):
        @singleton
        class B(object):
            pass

        class A(object):
            @inject(B)
            def __init__(self, b):
                self.b = b

        self.run(A, B)

    def run(self, A, B):
        def configure(binder):
            module_scope = self.ModuleScope()
            binder.bind(A, scope=module_scope)
            binder.bind(B)

        injector1 = Injector(configure)
        a1 = injector1.get_instance(A)
        a2 = injector1.get_instance(A)
        assert_true(a1 is a2)

        injector1 = Injector(configure)
        a3 = injector1.get_instance(A)
        a4 = injector1.get_instance(A)
        assert_true(a2 is not a3)
        assert_true(a3 is a4)


def test_injecting_interface_implementation():
    class Interface(object):
        pass

    class Implementation(object):
        pass

    class A(object):
        @inject(Interface)
        def __init__(self, i):
            self.i = i

    def configure(binder):
        binder.bind(A)
        binder.bind(Interface, to=Implementation)

    injector = Injector(configure)
    a = injector.get_instance(A)
    assert_true(isinstance(a.i, Implementation))


def test_cyclic_dependencies():
    class Interface(object):
        pass

    class A(object):
        @inject(Interface)
        def __init__(self, i):
            self.i = i

    class B(object):
        @inject(A)
        def __init__(self, a):
            self.a = a

    def configure(binder):
        binder.bind(Interface, to=B)
        binder.bind(A)

    injector = Injector(configure)
    assert_raises(CircularDependency, injector.get_instance, A)


def test_avoid_circular_dependency_with_method_injection():
    class Interface(object):
        pass

    class A(object):
        @inject(Interface)
        def __init__(self, i):
            self.i = i

    # Even though A needs B (via Interface) and B.method() needs A, they are
    # resolved at different times, avoiding circular dependencies.
    class B(object):
        @inject(A)
        def method(self, a):
            self.a = a

    def configure(binder):
        binder.bind(Interface, to=B)
        binder.bind(A)
        binder.bind(B)

    injector = Injector(configure)
    a = injector.get_instance(A)
    assert_true(isinstance(a.i, B))
    b = injector.get_instance(B)
    b.method()
    assert_true(isinstance(b.a, A))


def test_module_provides():
    class MyModule(Module):
        @provides(str, named='name')
        def provide_name(self):
            return 'Bob'

    module = MyModule()
    injector = Injector(module)
    assert_equal(injector.get_instance(str, named='name'), 'Bob')
