Testing with Injector
=====================

When you use unit test framework such as `unittest2` or `nose` you can also profit from `injector`. However, manually creating injectors and test classes can be quite annoying. There is, however, `with_injector` method decorator which has parameters just as `Injector` construtor and installes configured injector into class instance on the time of method call::

    import unittest
    from injector import Module, with_injector, inject

    class UsernameModule(Module):
        def configure(self, binder):
            binder.bind(str, 'Maria')

    class TestSomethingClass(unittest.TestCase):
        @with_injector(UsernameModule())
        def setUp(self):
            pass

        @inject
        def test_username(self, username: str):
            self.assertEqual(username, 'Maria')

**Each** method call re-initializes :class:`~injector.Injector` - if you want to you can also put :func:`~injector.with_injector` decorator on class constructor.

After such call all :func:`~injector.inject`-decorated methods will work just as you'd expect them to work.
