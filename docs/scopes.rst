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

ThreadLocals
``````````

ThreadLocals (instances local to a thread) are declared by binding them in the ThreadLocalScope. Just like for Singletons, this can be done in three ways:

1.  Decorating the class with `@threadlocal`.
2.  Decorating a `@provider` decorated Module method with `@threadlocal`.
3.  Explicitly calling `binder.bind(X, scope=threadlocal)`.

A (redundant) example showing all three methods::

    @threadlocal
    class Thing: pass
    class ThingModule(Module):
        def configure(self, binder):
            binder.bind(Thing, scope=threadlocal)
        @threadlocal
        @provider
        def provide_thing(self) -> Thing:
            return Thing()

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

Scopes can be retrieved from the injector, as with any other instance. They are singletons across the life of the injector::

    >>> injector = Injector([MyModule()])
    >>> injector.get(CustomScope) is injector.get(CustomScope)
    True

Scopes have `configure` method that will be called once per each injector and can be used for any required initialization.

For scopes with a transient lifetime, such as those tied to HTTP requests, the usual solution is to use a thread or greenlet-local cache inside the scope. The scope is "entered" in some low-level code by calling a method on the scope instance that creates this cache. Once the request is complete, the scope is "left" and the cache cleared.
