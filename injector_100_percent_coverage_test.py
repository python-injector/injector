"""Targeted tests that exercise the remaining uncovered lines in ``injector``.

These cases don't fit naturally into the functional test suite in
``injector_test.py`` – they poke at internal string-formatting helpers and
rarely-hit edge-case/error branches purely to drive coverage to 100%.
"""

from typing import Dict, List, Union

import pytest

import injector
from injector import (
    CallError,
    Injector,
    Module,
    NoInject,
    UnknownProvider,
    UnsatisfiedRequirement,
    provider,
    singleton,
)

# --- String / representation formatting --------------------------------------


def test_unsatisfied_requirement_str_without_owner():
    # The ``self.owner`` falsy branch of ``UnsatisfiedRequirement.__str__``.
    error = UnsatisfiedRequirement(None, int)
    assert str(error) == 'unsatisfied requirement on int'


def test_unsatisfied_requirement_str_with_owner():
    # The ``self.owner`` truthy branch, which prepends a description of the owner.
    class Owner:
        pass

    owner = Owner()
    error = UnsatisfiedRequirement(owner, int)
    message = str(error)
    assert message.endswith('has an unsatisfied requirement on int')
    assert message != 'unsatisfied requirement on int'


def test_describe_named_object():
    # Objects exposing ``__name__`` are described by that name.
    assert injector._describe(int) == 'int'


def test_describe_tuple_uses_first_element():
    # Tuples/lists are described via their first element's ``__name__``.
    assert injector._describe((int,)) == '[int]'
    assert injector._describe([str]) == '[str]'


def test_describe_falls_back_to_str():
    # Anything without ``__name__`` that isn't a tuple/list falls back to ``str``.
    assert injector._describe(123) == '123'


def test_get_origin_normalizes_typing_aliases():
    # Some (older) typings store ``typing.List``/``typing.Dict`` as ``__origin__``;
    # ``_get_origin`` normalizes those back to the builtin containers.
    class FakeListAlias:
        __origin__ = List

    class FakeDictAlias:
        __origin__ = Dict

    assert injector._get_origin(FakeListAlias) is list
    assert injector._get_origin(FakeDictAlias) is dict


# --- Edge-case exception / branch paths --------------------------------------


def test_provider_for_unknown_target_raises():
    # Neither a class, callable, provider nor a recognized bindable instance –
    # provider_for can't figure out what to do and raises UnknownProvider.
    binder = Injector().binder
    with pytest.raises(UnknownProvider):
        binder.provider_for(123, to=123)


def test_unresolvable_forward_reference_in_provider_raises_name_error():
    # The return annotation is a forward reference to a name that never exists,
    # so it stays "__deferred__" and re-evaluation at configure time fails.
    class BrokenModule(Module):
        @provider
        def provide(self) -> 'ThisNameNeverExists':  # noqa: F821
            return object()

    with pytest.raises(NameError, match='forward reference'):
        Injector([BrokenModule])


def test_create_object_wraps_new_type_error_in_call_error():
    # ``cls.__new__(cls)`` raises TypeError (extra required arg), which gets
    # re-raised as a CallError.
    class NeedsArg:
        def __new__(cls, required):
            return super().__new__(cls)

    with pytest.raises(CallError):
        Injector().create_object(NeedsArg)


def test_union_member_marked_noinject_is_dropped():
    # A Union whose members carry the NoInject marker is removed from the
    # inferred bindings.
    def target(x: Union[NoInject[int], str]):
        pass

    bindings = injector._infer_injected_bindings(target, only_explicit_bindings=False)
    assert 'x' not in bindings


def test_get_with_scope_decorator_unwraps_to_scope():
    # Passing a ScopeDecorator (e.g. ``singleton``) to Injector.get unwraps it
    # to the underlying scope before resolving.
    class Service:
        pass

    inj = Injector()
    first = inj.get(Service, scope=singleton)
    second = inj.get(Service, scope=singleton)
    assert isinstance(first, Service)
    assert first is second
