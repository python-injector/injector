Injector - Python dependency injection framework, inspired by Guice
===================================================================

[![image](https://secure.travis-ci.org/alecthomas/injector.png?branch=master)](https://travis-ci.org/alecthomas/injector)

Introduction
------------

Dependency injection as a formal pattern is less useful in Python than in other languages, primarily due to its support for keyword arguments, the ease with which objects can be mocked, and its dynamic nature.

That said, a framework for assisting in this process can remove a lot of boiler-plate from larger applications. That's where Injector can help. It automatically and transitively provides keyword arguments with their values. As an added benefit, Injector encourages nicely compartmentalised code through the use of `Module` s.

While being inspired by Guice, it does not slavishly replicate its API. Providing a Pythonic API trumps faithfulness.

How to get Injector?
--------------------

GitHub page: https://github.com/alecthomas/injector

Injector is also available on PyPI: https://pypi.python.org/pypi/injector. You can install it using pip:

```python
pip install injector
```


Supported Python versions
-------------------------

Injector works with the following Python interpreters:

-   CPython 2.6+, 3.2+
-   PyPy 1.9+

Recent Notable Changes
----------------------

### Added support for using Python3 annotations instead of @inject.

eg. The following code:

```python
class B(object):
    @inject(a=A):
    def __init__(self, a):
        self.a = a
```

Can now be written as:

```python3
class B(object):
    def __init__(self, a:A):
        self.a = a
```

To enable this support, instantiate your `Injector` with `Injector(..., use_annotations=True)`

### If you inject a function, an injection-aware wrapper is provided

Example:

```python
>>> from injector import Injector, inject, Key
>>> GreetingType = Key('GreetingType')
>>>
>>> @inject(greeting_type=GreetingType)
... def greet(greeting_type, who):
...     print('%s, %s!' % (greeting_type, who))
...
>>> def configure(binder):
...     binder.bind(GreetingType, to='Hello')
...
>>> injector = Injector(configure)
>>> greet_wrapper = injector.get(greet)
>>> greet_wrapper(who='John')
Hello, John!

```

A Quick Example
---------------


```pycon
>>> from injector import Injector, inject
>>> class Inner(object):
...     def __init__(self):
...         self.forty_two = 42
...
>>> class Outer(object):
...     @inject(inner=Inner)
...     def __init__(self, inner):
...         self.inner = inner
...
>>> injector = Injector()
>>> outer = injector.get(Outer)
>>> outer.inner.forty_two
42

```

A Full Example
--------------

Here's a full example to give you a taste of how Injector works:


```pycon
>>> from injector import Module, Key, provides, Injector, inject, singleton

```

We'll use an in-memory SQLite database for our example:


```pycon
>>> import sqlite3

```

And make up an imaginary `RequestHandler` class that uses the SQLite connection:


```pycon
>>> class RequestHandler(object):
...   @inject(db=sqlite3.Connection)
...   def __init__(self, db):
...     self._db = db
...
...   def get(self):
...     cursor = self._db.cursor()
...     cursor.execute('SELECT key, value FROM data ORDER by key')
...     return cursor.fetchall()

```

Next, for the sake of the example, we'll create a "configuration" annotated type:


```pycon
>>> Configuration = Key('configuration')

```

Key is used to uniquely identifies the configuration dictionary. Next, we bind the configuration to the injector, using a module:


```pycon
>>> def configure_for_testing(binder):
...     configuration = {'db_connection_string': ':memory:'}
...     binder.bind(Configuration, to=configuration, scope=singleton)

```

Next we create a module that initialises the DB. It depends on the configuration provided by the above module to create a new DB connection, then populates it with some dummy data, and provides a `Connection` object:


```pycon
>>> class DatabaseModule(Module):
...   @singleton
...   @provides(sqlite3.Connection)
...   @inject(configuration=Configuration)
...   def provide_sqlite_connection(self, configuration):
...     conn = sqlite3.connect(configuration['db_connection_string'])
...     cursor = conn.cursor()
...     cursor.execute('CREATE TABLE IF NOT EXISTS data (key PRIMARY KEY, value)')
...     cursor.execute('INSERT OR REPLACE INTO data VALUES ("hello", "world")')
...     return conn

```

(Note how we have decoupled configuration from our database initialisation code.)

Finally, we initialise an `Injector` and use it to instantiate a `RequestHandler` instance. This first transitively constructs a `sqlite3.Connection` object, and the Configuration dictionary that it in turn requires, then instantiates our `RequestHandler`:


```pycon
>>> injector = Injector([configure_for_testing, DatabaseModule()])
>>> handler = injector.get(RequestHandler)
>>> tuple(map(str, handler.get()[0]))  # py3/py2 compatibility hack
('hello', 'world')

```

We can also veryify that our `Configuration` and `SQLite` connections are indeed singletons within the Injector:


```pycon
>>> injector.get(Configuration) is injector.get(Configuration)
True
>>> injector.get(sqlite3.Connection) is injector.get(sqlite3.Connection)
True

```

You're probably thinking something like: "this is a large amount of work just to give me a database connection", and you are correct; dependency injection is typically not that useful for smaller projects. It comes into its own on large projects where the up-front effort pays for itself in two ways:

1.  Forces decoupling. In our example, this is illustrated by decoupling our configuration and database configuration.
2.  After a type is configured, it can be injected anywhere with no additional effort. Simply `@inject` and it appears. We don't really illustrate that here, but you can imagine adding an arbitrary number of `RequestHandler` subclasses, all of which will automatically have a DB connection provided.

Terminology
-----------

At its heart, Injector is simply a dictionary for mapping types to things that create instances of those types. This could be as simple as:

```python
{str: 'an instance of a string'}
```

For those new to dependency-injection and/or Guice, though, some of the terminology used may not be obvious.

### Provider

A means of providing an instance of a type. Built-in providers include `ClassProvider` (creates a new instance from a class), `InstanceProvider` (returns an existing instance directly), `CallableProvider` (provides an instance by calling a function).

### Scope

By default, providers are executed each time an instance is required. Scopes allow this behaviour to be customised. For example, `SingletonScope` (typically used through the class decorator `singleton`), can be used to always provide the same instance of a class.

Other examples of where scopes might be a threading scope, where instances are provided per-thread, or a request scope, where instances are provided per-HTTP-request.

The default scope is `NoScope`.

### Binding Key

A binding key uniquely identifies a provider of a type. It is effectively a tuple of `(type, annotation)` where `type` is the type to be provided and `annotation` is additional, optional, uniquely identifying information for the type.

For example, the following are all unique binding keys for `str`:

```python
(str, 'name')
(str, 'description')
```

For a generic type such as `str`, annotations are very useful for unique identification.

As an *alternative* convenience to using annotations, `Key` may be used to create unique types as necessary:


```pycon
>>> from injector import Key
>>> Name = Key('name')
>>> Description = Key('description')

```

Which may then be used as binding keys, without annotations, as they already uniquely identify a particular provider:

```python
(Name, None)
(Description, None)
```

Though of course, annotations may still be used with these types, like any other type.

### Annotation

An annotation is additional unique information about a type to avoid binding key collisions. It creates a new unique binding key for an existing type.

### Binding

A binding is the mapping of a unique binding key to a corresponding provider. For example:


```pycon
>>> from injector import InstanceProvider
>>> bindings = {
...   (Name, None): InstanceProvider('Sherlock'),
...   (Description, None): InstanceProvider('A man of astounding insight'),
... }

```

### Binder

The `Binder` is simply a convenient wrapper around the dictionary that maps types to providers. It provides methods that make declaring bindings easier.

### Module

A `Module` configures bindings. It provides methods that simplify the process of binding a key to a provider. For example the above bindings would be created with:


```pycon
>>> from injector import Module
>>> class MyModule(Module):
...     def configure(self, binder):
...         binder.bind(Name, to='Sherlock')
...         binder.bind(Description, to='A man of astounding insight')

```

For more complex instance construction, methods decorated with `@provides` will be called to resolve binding keys:


```pycon
>>> from injector import provides
>>> class MyModule(Module):
...     def configure(self, binder):
...         binder.bind(Name, to='Sherlock')
...
...     @provides(Description)
...     def describe(self):
...         return 'A man of astounding insight (at %s)' % time.time()

```

### Injection

Injection is the process of providing an instance of a type, to a method that uses that instance. It is achieved with the `inject` decorator. Keyword arguments to inject define which arguments in its decorated method should be injected, and with what.

Here is an example of injection on a module provider method, and on the constructor of a normal class:


```pycon
>>> from injector import inject
>>> class User(object):
...     @inject(name=Name, description=Description)
...     def __init__(self, name, description):
...         self.name = name
...         self.description = description

```


```pycon
>>> class UserModule(Module):
...     def configure(self, binder):
...        binder.bind(User)

```


```pycon
>>> class UserAttributeModule(Module):
...     def configure(self, binder):
...         binder.bind(Name, to='Sherlock')
...
...     @provides(Description)
...     @inject(name=Name)
...     def describe(self, name):
...         return '%s is a man of astounding insight' % name

```

You can also `inject`-decorate class itself. This code:


```pycon
>>> @inject(name=Name)
... class Item(object):
...     pass

```

is equivalent to:


```pycon
>>> class Item(object):
...     @inject(name=Name)
...     def __init__(self, name):
...         self.name = name

```

**Note 1**: You can also begin the name of injected member with an underscore(s) (to indicate the member being private for example). In such case the member will be injected using the name you specified, but corresponding parameter in a constructor (let's say you instantiate the class manually) will have the underscore prefix stripped (it makes it consistent with most of the usual parameter names):


```pycon
>>> @inject(_y=int)
... class X(object):
...     pass
...
>>> x1 = injector.get(X)
>>> x1.y
Traceback (most recent call last):
AttributeError: 'X' object has no attribute 'y'
>>> x1._y
0
>>> x2 = X(y=2)
>>> x2.y
Traceback (most recent call last):
AttributeError: 'X' object has no attribute 'y'
>>> x2._y
2

```

**Note 2**: When class is decorated with `inject` decorator you need to use keyword arguments when instantiating the class manually:

```python
x = X(y=2)  # that's ok
x = X(2)  # this'll raise CallError
```

### Injector

The `Injector` brings everything together. It takes a list of `Module` s, and configures them with a binder, effectively creating a dependency graph:


```pycon
>>> from injector import Injector
>>> injector = Injector([UserModule(), UserAttributeModule()])

```

You can also pass classes instead of instances to `Injector`, it will instantiate them for you:


```pycon
>>> injector = Injector([UserModule, UserAttributeModule])

```

The injector can then be used to acquire instances of a type, either directly:


```pycon
>>> injector.get(Name)
'Sherlock'
>>> injector.get(Description)
'Sherlock is a man of astounding insight'

```

Or transitively:


```pycon
>>> user = injector.get(User)
>>> isinstance(user, User)
True
>>> user.name
'Sherlock'
>>> user.description
'Sherlock is a man of astounding insight'

```

### Assisted injection

Sometimes there are classes that have injectable and non-injectable parameters in their constructors. Let's have for example:


```pycon
>>> class Database(object): pass

```


```pycon
>>> class User(object):
...     def __init__(self, name):
...         self.name = name

```


```pycon
>>> @inject(db=Database)
... class UserUpdater(object):
...     def __init__(self, user):
...         pass

```

You may want to have database connection `db` injected into `UserUpdater` constructor, but in the same time provide `user` object by yourself, and assuming that `user` object is a value object and there's many users in your application it doesn't make much sense to inject objects of class `User`.

In this situation there's technique called Assisted injection:


```pycon
>>> from injector import AssistedBuilder
>>> injector = Injector()
>>> builder = injector.get(AssistedBuilder(cls=UserUpdater))
>>> user = User('John')
>>> user_updater = builder.build(user=user)

```

This way we don't get `UserUpdater` directly but rather a builder object. Such builder has `build(**kwargs)` method which takes non-injectable parameters, combines them with injectable dependencies of `UserUpdater` and calls `UserUpdater` initializer using all of them.

`AssistedBuilder(...)` is injectable just as anything else, if you need instance of it you just ask for it like that:


```pycon
>>> @inject(updater_builder=AssistedBuilder(cls=UserUpdater))
... class NeedsUserUpdater(object):
...     def method(self):
...         updater = self.updater_builder.build(user=None)

```

`cls` needs to be a concrete class and no bindings will be used.

If you want `AssistedBuilder` to follow bindings and construct class pointed to by a key you can do it like this:

```pycon
>>> DB = Key('DB')
>>> class DBImplementation(object):
...     def __init__(self, uri):
...         pass
...
>>> def configure(binder):
...     binder.bind(DB, to=DBImplementation)
...
>>> injector = Injector(configure)
>>> builder = injector.get(AssistedBuilder(interface=DB))
>>> isinstance(builder.build(uri='x'), DBImplementation)
True

```

Note: ``AssistedBuilder(X)`` is a shortcut for ``AssistedBuilder(interface=X)``

More information on this topic:

- ["How to use Google Guice to create objects that require parameters?" on Stack Overflow](http://stackoverflow.com/questions/996300/how-to-use-google-guice-to-create-objects-that-require-parameters)
- [Google Guice assisted injection](http://code.google.com/p/google-guice/wiki/AssistedInject)

### Child injectors


Concept similar to Guice's child injectors is supported by `Injector`. This way you can have one injector that inherits bindings from other injector (parent) but these bindings can be overriden in it and it doesn't affect parent injector bindings:


```pycon
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

```

**Note**: Default scopes are bound only to root injector. Binding them manually to child injectors will result in unexpected behaviour. **Note 2**: Once a binding key is present in parent injector scope (like `singleton` scope), provider saved there takes predecence when binding is overridden in child injector in the same scope. This behaviour is subject to change:


```pycon
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

```

Scopes
------

### Singletons

Singletons are declared by binding them in the SingletonScope. This can be done in three ways:

1.  Decorating the class with `@singleton`.
2.  Decorating a `@provides(X)` decorated Module method with `@singleton`.
3.  Explicitly calling `binder.bind(X, scope=singleton)`.

A (redundant) example showing all three methods:


```pycon
>>> @singleton
... class Thing(object): pass
>>> class ThingModule(Module):
...   def configure(self, binder):
...     binder.bind(Thing, scope=singleton)
...   @singleton
...   @provides(Thing)
...   def provide_thing(self):
...     return Thing()

```

### Implementing new Scopes

In the above description of scopes, we glossed over a lot of detail. In particular, how one would go about implementing our own scopes.

Basically, there are two steps. First, subclass `Scope` and implement `Scope.get`:


```pycon
>>> from injector import Scope
>>> class CustomScope(Scope):
...   def get(self, key, provider):
...     return provider

```

Then create a global instance of `ScopeDecorator` to allow classes to be easily annotated with your scope:


```pycon
>>> from injector import ScopeDecorator
>>> customscope = ScopeDecorator(CustomScope)

```

This can be used like so:

```pycon
>>> @customscope
... class MyClass(object):
...   pass

```

Scopes are bound in modules with the `Binder.bind_scope` method:


```pycon
>>> class MyModule(Module):
...   def configure(self, binder):
...     binder.bind_scope(CustomScope)

```

Scopes can be retrieved from the injector, as with any other instance. They are singletons across the life of the injector:


```pycon
>>> injector = Injector([MyModule()])
>>> injector.get(CustomScope) is injector.get(CustomScope)
True

```

For scopes with a transient lifetime, such as those tied to HTTP requests, the usual solution is to use a thread or greenlet-local cache inside the scope. The scope is "entered" in some low-level code by calling a method on the scope instance that creates this cache. Once the request is complete, the scope is "left" and the cache cleared.

Tests
-----

When you use unit test framework such as `unittest2` or `nose` you can also profit from `injector`. However, manually creating injectors and test classes can be quite annoying. There is, however, `with_injector` method decorator which has parameters just as `Injector` construtor and installes configured injector into class instance on the time of method call:


```pycon
>>> from injector import Module, with_injector
>>> class UsernameModule(Module):
...   def configure(self, binder):
...     binder.bind(str, 'Maria')
...
>>> class TestSomethingClass(object):
...   @with_injector(UsernameModule())
...   def setup(self):
...      pass
...
...   @inject(username=str)
...   def test_username(self, username):
...      assert (username == 'Maria')

```

*Each* method call re-initializes `Injector` - if you want to you can also put `with_injector` decorator on class constructor.

After such call all `inject`-decorated methods will work just as you'd expect them to work.

Logging
=======

Injector uses standard :mod:`logging` module, the logger name is ``injector``.

By default ``injector`` logger is not configured to print logs anywhere.

To enable ``get()`` tracing you need to set ``injector`` logger level to ``DEBUG``. You can do that programatically by executing:

```pycon
>>> import logging
>>> logging.getLogger('injector').setLevel(logging.DEBUG)

```

Thread safety
-------------

The following functions are thread safe:

-   `Injector.get`
-   injection provided by `inject` decorator (please note, however, that it doesn't say anything about decorated function thread safety)

Footnote
--------

This framework is similar to snake-guice, but aims for simplification.

&copy; Copyright 2010-2013 to Alec Thomas, under the BSD license

