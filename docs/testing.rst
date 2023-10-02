Testing with Injector
=====================

When you use unit test framework such as `unittest2` or `nose` you can also profit from `injector`. ::

    import unittest
    from injector import Injector, Module


    class UsernameModule(Module):
        def configure(self, binder):
            binder.bind(str, 'Maria')


    class TestSomethingClass(unittest.TestCase):

        def setUp(self):
            self.__injector = Injector(UsernameModule())

        def test_username(self):
            username = self.__injector.get(str)
            self.assertEqual(username, 'Maria')

