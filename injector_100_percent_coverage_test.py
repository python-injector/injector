"""Targeted tests that exercise the remaining uncovered lines in ``injector``.

These cases don't fit naturally into the functional test suite in
``injector_test.py`` – they poke at internal string-formatting helpers and
rarely-hit edge-case/error branches purely to drive coverage to 100%.
"""

from typing import Dict, List

import injector
from injector import UnsatisfiedRequirement


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
