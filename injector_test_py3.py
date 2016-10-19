from typing import Any

import pytest

from injector import (
    AssistedBuilder, inject, Injector, CallError,
    Module, noninjectable, provider, provides, singleton,
)


def test_implicit_injection_for_python3_old_style():
    class A(object):
        pass

    class B(object):
        def __init__(self, a:A):
            self.a = a

    class C(object):
        def __init__(self, b:B):
            self.b = b

    injector = Injector(use_annotations=True)
    c = injector.get(C)
    assert isinstance(c, C)
    assert isinstance(c.b, B)
    assert isinstance(c.b.a, A)


def test_implicit_injection_for_python3_old_style():
    class A(object):
        pass

    class B(object):
        @inject
        def __init__(self, a:A):
            self.a = a

    class C(object):
        @inject
        def __init__(self, b:B):
            self.b = b

    injector = Injector()
    c = injector.get(C)
    assert isinstance(c, C)
    assert isinstance(c.b, B)
    assert isinstance(c.b.a, A)


def test_annotation_based_injection_works_in_provider_methods_old_style():
    class MyModule(Module):
        def configure(self, binder):
            binder.bind(int, to=42)

        @provides(str)
        @inject
        def provide_str(self, i: int):
            return str(i)

    injector = Injector(MyModule)
    assert injector.get(str) == '42'


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


def test_implicit_injection_fails_when_annotations_are_missing_old_style():
    class A(object):
        def __init__(self, n):
            self.n = n

    injector = Injector(use_annotations=True)
    with pytest.raises(CallError):
        injector.get(A)


def test_implicit_injection_fails_when_annotations_are_missing():
    class A(object):
        def __init__(self, n):
            self.n = n

    injector = Injector()
    with pytest.raises(CallError):
        injector.get(A)


def test_injection_works_in_presence_of_return_value_annotation_old_style():
    # Code with PEP 484-compatible type hints will have __init__ methods
    # annotated as returning None[1] and this didn't work well with Injector.
    #
    # [1] https://www.python.org/dev/peps/pep-0484/#the-meaning-of-annotations

    class A:
        def __init__(self, s: str) -> None:
            self.s = s

    def configure(binder):
        binder.bind(str, to='this is string')

    injector = Injector([configure], use_annotations=True)

    # Used to fail with:
    # injector.UnknownProvider: couldn't determine provider for None to None
    a = injector.get(A)

    # Just a sanity check, if the code above worked we're almost certain
    # we're good but just in case the return value annotation handling changed
    # something:
    assert a.s == 'this is string'


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
        binder.bind(str, to='hello')

    @inject
    def fun(s: 'str') -> None:
        return s

    injector = Injector(configure)
    injector.call_with_injection(fun) == 'hello'


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
    with pytest.raises(CallError):
        injector.call_with_injection(fun)
