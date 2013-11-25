import pytest

from injector import Injector, CallError


def test_implicit_injection_for_python3():
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


def test_implicit_injection_fails_when_annotations_are_missing():
    class A(object):
        def __init__(self, n):
            self.n = n

    injector = Injector(use_annotations=True)
    with pytest.raises(CallError):
        injector.get(A)
