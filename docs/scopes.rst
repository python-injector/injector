.. _scopes:

Scopes
======

Singletons
``````````

Singletons are declared by binding them in the SingletonScope. This can be done in three ways:

1.  Decorating the class with `@singleton`.
2.  Decorating a `@provider` decorated Module method with `@singleton`.
3.  Explicitly calling `binder.bind(X, scope=singleton)`.

A (redundant) example showing all three methods::

    @singleton
    class Thing: pass
    class ThingModule(Module):
        def configure(self, binder):
            binder.bind(Thing, scope=singleton)
        @singleton
        @provider
        def provide_thing(self) -> Thing:
            return Thing()

If using hierarchies of injectors, classes decorated with `@singleton` will be created by and bound to the parent/ancestor injector closest to the root that can provide all of its dependencies.

Implementing new Scopes
```````````````````````

In the above description of scopes, we glossed over a lot of detail. In particular, how one would go about implementing our own scopes.

Basically, there are two steps. First, subclass `Scope` and implement `Scope.get`::

     from injector import Scope
     class CustomScope(Scope):
         def get(self, key, provider):
             return provider

Then create a global instance of :class:`ScopeDecorator` to allow classes to be easily annotated with your scope::

    from injector import ScopeDecorator
    customscope = ScopeDecorator(CustomScope)

This can be used like so::

    @customscope
    class MyClass:
        pass

Scopes are bound in modules with the :meth:`Binder.install` method::

    class MyModule(Module):
        def configure(self, binder):
            binder.install(CustomScope)

Scopes can be retrieved from the injector, as with any other instance. They are singletons across the life of the injector::

    >>> injector = Injector([MyModule()])
    >>> injector.get(CustomScope) is injector.get(CustomScope)
    True

For scopes with a transient lifetime, such as those tied to HTTP requests, the usual solution is to use a thread or greenlet-local cache inside the scope. The scope is "entered" in some low-level code by calling a method on the scope instance that creates this cache. Once the request is complete, the scope is "left" and the cache cleared.

Using Scopes to manage Resources
````````````````````````````````

Sometimes You need to inject classes, which manage resources, like database
connections. Imagine You have an :class:`App`, which depends on multiple other
services and some of these services need to access the Database. The naive
approach would be to open and close the connection everytime it is needed::

    class App:
       @inject
        def __init__(self, service1: Service1, service2: Service2):
            Service1()
            Service2()

    class Service1:
        def __init__(self, cm: ConnectionManager):
            cm.openConnection()
            # do something with the opened connection
            cm.closeConnection()

    class Service2:
        def __init__(self, cm: ConnectionManager):
            cm.openConnection()
            # do something with the opened connection
            cm.closeConnection()

Now You may figure, that this is inefficient. Instead of opening a new
connection everytime a connection is requested, it may be useful to reuse
already opened connections. But how and when should these connections be closed
in the example above?

This can be achieved with some small additions to the :class:`SingletonScope` and
to :class:`Injector` we can create singletons, which will be
cared for automatically, if they only implement a :meth:`cleanup` method and are
associated with our custom scope. Let's reduce our example from above a bit for
the sake of brevity to just one class, which needs cleanup. Remark the `@cleaned`
decorator, which we will implement shortly afterwards and which will associate the
class with our custom scope::

    @cleaned
    class NeedsCleanup:
        def __init__(self) -> None:
            print("NeedsCleanup: I'm alive and claiming lot's of resources!")

        def doSomething(self):
            print("NeedsCleanup: Now I have plenty of time to work with these resources.")

        def cleanup(self):
            print("NeedsCleanup: Freeing my precious resources!")

To achieve this, we first need to create a custom scope. This scope will just
collect all singletons, which were accessed using the :meth:`Scope.get`-method::

    T = TypeVar('T')

    class CleanupScope(SingletonScope):
        def __init__(self, injector: 'Injector') -> None:
            super().__init__(injector)
            # We have singletons here, so never cache them twice, since otherwise
            # the cleanup method might be invoked twice.
            self.cachedProviders = set()

        def get(self, key: Type[T], provider: Provider[T]) -> Provider[T]:
            obj = super().get(key, provider)
            self.cachedProviders.add(obj)
            return obj

    cleaned = ScopeDecorator(CleanupScope)

Next we will also create a custom :class:`Injector`, which will do the cleanup of all
our objects belonging to :class:`CleanupScope` after a call to :meth:`get`::

    ScopeType = Union[ScopeDecorator, Type[Scope], None]

    class CleanupInjector:
        def __init__(self, injector: Injector) -> None:
            self.injector = injector

        @contextmanager
        def get(self, interface: Type[T], scope: ScopeType = None) -> Generator[T, None, None]:
            yield self.injector.get(interface, scope)
            self.cleanup()

        def cleanup(self):
            print("CleanupInjector: Invoking 'cleanup' for all who need it.")
            cleanupScope = self.injector.get(CleanupScope)
            for provider in cleanupScope.cachedProviders:
                obj = provider.get(self.injector)
                if hasattr(obj, 'cleanup') and callable(obj.cleanup):
                    obj.cleanup()

Now we can simply use our custom injector and freeing resources will be done for
each object in :class:`CleanupScope` automatically::

    injector = CleanupInjector(Injector())
    with injector.get(NeedsCleanup) as obj:
        obj.doSomething()

This is of course a simple example. In a real world example `NeedsCleanup` could
be nested deep and multiple times anywhere in a dependency structure. This
pattern would work irrespectively of where `NeedsCleanup` would be injected.
