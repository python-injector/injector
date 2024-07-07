Terminology
===========

At its heart, Injector is simply a dictionary for mapping types to things that create instances of those types. This could be as simple as::

    {str: 'an instance of a string'}

For those new to dependency-injection and/or Guice, though, some of the terminology used may not be obvious.

Provider
````````

A means of providing an instance of a type. Built-in providers include:

* :class:`~injector.ClassProvider` - creates a new instance from a class
* :class:`~injector.InstanceProvider` - returns an existing instance directly
* :class:`~injector.CallableProvider` - provides an instance by calling a function

In order to create custom provider you need to subclass :class:`~injector.Provider` and override its :meth:`~injector.Provider.get` method.

Scope
`````

By default, providers are executed each time an instance is required. Scopes allow this behaviour to be customised. For example, `SingletonScope` (typically used through the class decorator `singleton`), can be used to always provide the same instance of a class.

Other examples of where scopes might be a threading scope, where instances are provided per-thread, or a request scope, where instances are provided per-HTTP-request.

The default scope is :class:`NoScope`.

.. seealso:: :ref:`scopes`

Binding
```````

A binding is the mapping of a unique binding key to a corresponding provider. For example::

    >>> from injector import InstanceProvider
    >>> bindings = {
    ...   (Name, None): InstanceProvider('Sherlock'),
    ...   (Description, None): InstanceProvider('A man of astounding insight'),
    ... }


Binder
``````

The `Binder` is simply a convenient wrapper around the dictionary that maps types to providers. It provides methods that make declaring bindings easier.


.. _module:

Module
``````

A `Module` configures bindings. It provides methods that simplify the process of binding a key to a provider. For example the above bindings would be created with::

    >>> from injector import Module
    >>> class MyModule(Module):
    ...     def configure(self, binder):
    ...         binder.bind(Name, to='Sherlock')
    ...         binder.bind(Description, to='A man of astounding insight')

For more complex instance construction, methods decorated with `@provider` will be called to resolve binding keys::

    >>> from injector import provider
    >>> class MyModule(Module):
    ...     def configure(self, binder):
    ...         binder.bind(Name, to='Sherlock')
    ...
    ...     @provider
    ...     def describe(self) -> Description:
    ...         return 'A man of astounding insight (at %s)' % time.time()

Injection
`````````

Injection is the process of providing an instance of a type, to a method that uses that instance. It is achieved with the `inject` decorator. Keyword arguments to inject define which arguments in its decorated method should be injected, and with what.

Here is an example of injection on a module provider method, and on the constructor of a normal class::

    from typing import NewType

    from injector import Binder, Module, inject, provider

    Name = NewType("Name", str)
    Description = NewType("Description", str)

    class User:
        @inject
        def __init__(self, name: Name, description: Description):
            self.name = name
            self.description = description

    class UserModule(Module):
        def configure(self, binder: Binder):
           binder.bind(User)

    class UserAttributeModule(Module):
        def configure(self, binder: Binder):
            binder.bind(Name, to='Sherlock')

        @provider
        def describe(self, name: Name) -> Description:
            return '%s is a man of astounding insight' % name


Injector
````````

The `Injector` brings everything together. It takes a list of `Module` s, and configures them with a binder, effectively creating a dependency graph::

    from injector import Injector
    injector = Injector([UserModule(), UserAttributeModule()])

You can also pass classes instead of instances to `Injector`, it will instantiate them for you::

    injector = Injector([UserModule, UserAttributeModule])

The injector can then be used to acquire instances of a type, either directly::

    >>> injector.get(Name)
    'Sherlock'
    >>> injector.get(Description)
    'Sherlock is a man of astounding insight'

Or transitively::

    >>> user = injector.get(User)
    >>> isinstance(user, User)
    True
    >>> user.name
    'Sherlock'
    >>> user.description
    'Sherlock is a man of astounding insight'

Assisted injection
``````````````````

Sometimes there are classes that have injectable and non-injectable parameters in their constructors. Let's have for example::

    class Database: pass


    class User:
        def __init__(self, name):
            self.name = name


    class UserUpdater:
        def __init__(self, db: Database, user):
            pass

You may want to have database connection `db` injected into `UserUpdater` constructor, but in the same time provide `user` object by yourself, and assuming that `user` object is a value object and there's many users in your application it doesn't make much sense to inject objects of class `User`.

In this situation there's technique called Assisted injection::

    from injector import ClassAssistedBuilder
    injector = Injector()
    builder = injector.get(ClassAssistedBuilder[UserUpdater])
    user = User('John')
    user_updater = builder.build(user=user)

This way we don't get `UserUpdater` directly but rather a builder object. Such builder has `build(**kwargs)` method which takes non-injectable parameters, combines them with injectable dependencies of `UserUpdater` and calls `UserUpdater` initializer using all of them.

`AssistedBuilder[T]` and `ClassAssistedBuilder[T]` are injectable just as anything
else, if you need instance of it you just ask for it like that::

    class NeedsUserUpdater:
        @inject
        def __init__(self, builder: ClassAssistedBuilder[UserUpdater]):
            self.updater_builder = builder

        def method(self):
            updater = self.updater_builder.build(user=None)

`ClassAssistedBuilder` means it'll construct a concrete class and no bindings will be used.

If you want to follow bindings and construct class pointed to by a key you use `AssistedBuilder` and can do it like this::

    >>> DB = Key('DB')
    >>> class DBImplementation:
    ...     def __init__(self, uri):
    ...         pass
    ...
    >>> def configure(binder):
    ...     binder.bind(DB, to=DBImplementation)
    ...
    >>> injector = Injector(configure)
    >>> builder = injector.get(AssistedBuilder[DB])
    >>> isinstance(builder.build(uri='x'), DBImplementation)
    True

More information on this topic:

- `"How to use Google Guice to create objects that require parameters?" on Stack Overflow <http://stackoverflow.com/questions/996300/how-to-use-google-guice-to-create-objects-that-require-parameters>`_
- `Google Guice assisted injection <http://code.google.com/p/google-guice/wiki/AssistedInject>`_


Child injectors
```````````````

Concept similar to Guice's child injectors is supported by `Injector`. This way you can have one injector that inherits bindings from other injector (parent) but these bindings can be overriden in it and it doesn't affect parent injector bindings::

    >>> def configure_parent(binder):
    ...     binder.bind(str, to='asd')
    ...     binder.bind(int, to=42)
    ...
    >>> def configure_child(binder):
    ...     binder.bind(str, to='qwe')
    ...
    >>> parent = Injector(configure_parent)
    >>> child = parent.create_child_injector(configure_child)
    >>> parent.get(str), parent.get(int)
    ('asd', 42)
    >>> child.get(str), child.get(int)
    ('qwe', 42)

**Note**: Default scopes are bound only to root injector. Binding them manually to child injectors will result in unexpected behaviour. **Note 2**: Once a binding key is present in parent injector scope (like `singleton` scope), provider saved there takes predecence when binding is overridden in child injector in the same scope. This behaviour is subject to change::


    >>> def configure_parent(binder):
    ...     binder.bind(str, to='asd', scope=singleton)
    ...
    >>> def configure_child(binder):
    ...     binder.bind(str, to='qwe', scope=singleton)
    ...
    >>> parent = Injector(configure_parent)
    >>> child = parent.create_child_injector(configure_child)
    >>> child.get(str) # this behaves as expected
    'qwe'
    >>> parent.get(str) # wat
    'qwe'
