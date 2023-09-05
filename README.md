Injector - Python dependency injection framework, inspired by Guice
===================================================================

[![image](https://github.com/alecthomas/injector/workflows/CI/badge.svg)](https://github.com/alecthomas/injector/actions?query=workflow%3ACI+branch%3Amaster)
[![Coverage Status](https://codecov.io/gh/alecthomas/injector/branch/master/graph/badge.svg)](https://codecov.io/gh/alecthomas/injector)

Introduction
------------

While dependency injection is easy to do in Python due to its support for keyword arguments, the ease with which objects can be mocked and its dynamic nature, a framework for assisting in this process can remove a lot of boiler-plate from larger applications. That's where Injector can help. It automatically and transitively provides dependencies for you. As an added benefit, Injector encourages nicely compartmentalised code through the use of modules.

If you're not sure what dependency injection is or you'd like to learn more about it see:

* [The Clean Code Talks - Don't Look For Things! (a talk by Miško Hevery)](
  https://www.youtube.com/watch?v=RlfLCWKxHJ0)
* [Inversion of Control Containers and the Dependency Injection pattern (an article by Martin Fowler)](
  https://martinfowler.com/articles/injection.html)

The core values of Injector are:

* Simplicity - while being inspired by Guice, Injector does not slavishly replicate its API.
  Providing a Pythonic API trumps faithfulness. Additionally some features are omitted
  because supporting them would be cumbersome and introduce a little bit too much "magic"
  (member injection, method injection).

  Connected to this, Injector tries to be as nonintrusive as possible. For example while you may
  declare a class' constructor to expect some injectable parameters, the class' constructor
  remains a standard constructor – you may instantiate the class just the same manually, if you want.

* No global state – you can have as many [Injector](https://injector.readthedocs.io/en/latest/api.html#injector.Injector)
  instances as you like, each with a different configuration and each with different objects in different
  scopes. Code like this won't work for this very reason:

  ```python
    class MyClass:
        @inject
        def __init__(t: SomeType):
            # ...

    MyClass()
  ```

  This is simply because there's no global `Injector` to use. You need to be explicit and use
  [Injector.get](https://injector.readthedocs.io/en/latest/api.html#injector.Injector.get),
  [Injector.create_object](https://injector.readthedocs.io/en/latest/api.html#injector.Injector.create_object)
  or inject `MyClass` into the place that needs it.

* Cooperation with static type checking infrastructure – the API provides as much static type safety
  as possible and only breaks it where there's no other option. For example the
  [Injector.get](https://injector.readthedocs.io/en/latest/api.html#injector.Injector.get) method
  is typed such that `injector.get(SomeType)` is statically declared to return an instance of
  `SomeType`, therefore making it possible for tools such as [mypy](https://github.com/python/mypy) to
  type-check correctly the code using it.
  
* The client code only knows about dependency injection to the extent it needs – 
  [`inject`](https://injector.readthedocs.io/en/latest/api.html#injector.inject),
  [`Inject`](https://injector.readthedocs.io/en/latest/api.html#injector.Inject) and
  [`NoInject`](https://injector.readthedocs.io/en/latest/api.html#injector.NoInject) are simple markers
  that don't really do anything on their own and your code can run just fine without Injector
  orchestrating things.

### How to get Injector?

* GitHub (code repository, issues): https://github.com/alecthomas/injector

* PyPI (installable, stable distributions): https://pypi.org/project/injector/. You can install it using pip:

  ```bash
  pip install injector
  ```

* Documentation: https://injector.readthedocs.org
* Change log: https://injector.readthedocs.io/en/latest/changelog.html

Injector works with CPython 3.8+ and PyPy 3 implementing Python 3.8+.

A Quick Example
---------------


```python
>>> from injector import Injector, inject
>>> class Inner:
...     def __init__(self):
...         self.forty_two = 42
...
>>> class Outer:
...     @inject
...     def __init__(self, inner: Inner):
...         self.inner = inner
...
>>> injector = Injector()
>>> outer = injector.get(Outer)
>>> outer.inner.forty_two
42

```

Or with `dataclasses` if you like:

```python
from dataclasses import dataclass
from injector import Injector, inject
class Inner:
    def __init__(self):
        self.forty_two = 42

@inject
@dataclass
class Outer:
    inner: Inner

injector = Injector()
outer = injector.get(Outer)
print(outer.inner.forty_two)  # Prints 42
```


A Full Example
--------------

Here's a full example to give you a taste of how Injector works:


```python
>>> from injector import Module, provider, Injector, inject, singleton

```

We'll use an in-memory SQLite database for our example:


```python
>>> import sqlite3

```

And make up an imaginary `RequestHandler` class that uses the SQLite connection:


```python
>>> class RequestHandler:
...   @inject
...   def __init__(self, db: sqlite3.Connection):
...     self._db = db
...
...   def get(self):
...     cursor = self._db.cursor()
...     cursor.execute('SELECT key, value FROM data ORDER by key')
...     return cursor.fetchall()

```

Next, for the sake of the example, we'll create a configuration type:


```python
>>> class Configuration:
...     def __init__(self, connection_string):
...         self.connection_string = connection_string

```

Next, we bind the configuration to the injector, using a module:


```python
>>> def configure_for_testing(binder):
...     configuration = Configuration(':memory:')
...     binder.bind(Configuration, to=configuration, scope=singleton)

```

Next we create a module that initialises the DB. It depends on the configuration provided by the above module to create a new DB connection, then populates it with some dummy data, and provides a `Connection` object:


```python
>>> class DatabaseModule(Module):
...   @singleton
...   @provider
...   def provide_sqlite_connection(self, configuration: Configuration) -> sqlite3.Connection:
...     conn = sqlite3.connect(configuration.connection_string)
...     cursor = conn.cursor()
...     cursor.execute('CREATE TABLE IF NOT EXISTS data (key PRIMARY KEY, value)')
...     cursor.execute('INSERT OR REPLACE INTO data VALUES ("hello", "world")')
...     return conn

```

(Note how we have decoupled configuration from our database initialisation code.)

Finally, we initialise an `Injector` and use it to instantiate a `RequestHandler` instance. This first transitively constructs a `sqlite3.Connection` object, and the Configuration dictionary that it in turn requires, then instantiates our `RequestHandler`:


```python
>>> injector = Injector([configure_for_testing, DatabaseModule()])
>>> handler = injector.get(RequestHandler)
>>> tuple(map(str, handler.get()[0]))  # py3/py2 compatibility hack
('hello', 'world')

```

We can also verify that our `Configuration` and `SQLite` connections are indeed singletons within the Injector:


```python
>>> injector.get(Configuration) is injector.get(Configuration)
True
>>> injector.get(sqlite3.Connection) is injector.get(sqlite3.Connection)
True

```

You're probably thinking something like: "this is a large amount of work just to give me a database connection", and you are correct; dependency injection is typically not that useful for smaller projects. It comes into its own on large projects where the up-front effort pays for itself in two ways:

1.  Forces decoupling. In our example, this is illustrated by decoupling our configuration and database configuration.
2.  After a type is configured, it can be injected anywhere with no additional effort. Simply `@inject` and it appears. We don't really illustrate that here, but you can imagine adding an arbitrary number of `RequestHandler` subclasses, all of which will automatically have a DB connection provided.

Footnote
--------

This framework is similar to snake-guice, but aims for simplification.

&copy; Copyright 2010-2013 to Alec Thomas, under the BSD license
