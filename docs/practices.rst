.. _practices:

Good and bad practices
======================

Side effects
````````````

You should avoid creating side effects in your modules for two reasons:

* Side effects will make it more difficult to test a module if you want to do it
* Modules expose a way to acquire some resource but they don't provide any way
  to release it. If, for example, your module connects to a remote server while
  creating a service you have no way of closing that connection unless the
  service exposes it.


Injecting into constructors vs injecting into other methods
```````````````````````````````````````````````````````````

.. note::

  Injector 0.11+ doesn't support injecting into non-constructor methods,
  this section is kept for historical reasons.

.. note::

  Injector 0.11 deprecates using @inject with keyword arguments to declare
  bindings, this section remains unchanged for historical reasons.

In general you should prefer injecting into constructors to injecting into
other methods because:

* it can expose potential issues earlier (at object construction time rather
  than at the method call)
* it exposes class' dependencies more openly. Constructor injection:

  .. code-block:: python

    class Service1(object):
        @inject(http_client=HTTP)
        def __init__(self, http_client):
            self.http_client = http_client
            # some other code

        # tens or hundreds lines of code

        def method(self):
            # do something
            pass

  Regular method injection:

  .. code-block:: python

    class Service2(object):
        def __init__(self):
            # some other code

        # tens or hundreds lines of code

        @inject(http_client=HTTP)
        def method(self, http_client):
            # do something
            pass


  In first case you know all the dependencies by looking at the class'
  constructor, in the second you don't know about ``HTTP`` dependency until
  you see the method definition.

  Slightly different approach is suggested when it comes to Injector modules -
  in this case injecting into their constructors (or ``configure`` methods)
  would make the injection process dependent on the order of passing modules
  to Injector and therefore quite fragile. See this code sample:

  .. code-block:: python

    A = Key('A')
    B = Key('B')

    class ModuleA(Module):
        @inject(a=A)
        def configure(self, binder, a):
            pass

    class ModuleB(Module):
        @inject(b=B)
        def __init__(self, b):
            pass

    class ModuleC(Module):
        def configure(self, binder):
            binder.bind(A, to='a')
            binder.bind(B, to='b')


    # error, at the time of ModuleA processing A is unbound
    Injector([ModuleA, ModuleC])

    # error, at the time of ModuleB processing B is unbound
    Injector([ModuleB, ModuleC])

    # no error this time
    Injector([ModuleC, ModuleA, ModuleB])


Doing too much in modules and/or providers
``````````````````````````````````````````

An implementation detail of Injector: Injector and accompanying classes are
protected by a lock to make them thread safe. This has a downside though:
in general only one thread can use dependency injection at any given moment.

In best case scenario you "only" slow other threads' dependency injection
down. In worst case scenario (performing blocking calls without timeouts) you
can **deadlock** whole application.

**It is advised to avoid performing any IO, particularly without a timeout
set, inside modules code.**

As an illustration:

.. code-block:: python

    from threading import Thread
    from time import sleep

    from injector import inject, Injector, Module, provider

    class A: pass
    class SubA(A): pass
    class B: pass


    class BadModule(Module):
        @provider
        def provide_a(self, suba: SubA) -> A:
            return suba

        @provider
        def provide_suba(self) -> SubA:
            print('Providing SubA...')
            while True:
                print('Sleeping...')
                sleep(1)

            # This never executes
            return SubA()

        @provider
        def provide_b(self) -> B:
            return B()


    injector = Injector([BadModule])

    thread = Thread(target=lambda: injector.get(A))

    # to make sure the thread doesn't keep the application alive
    thread.daemon = True
    thread.start()

    # This will never finish
    injector.get(B)
    print('Got B')


Here's the output of the application::

    Providing SubA...
    Sleeping...
    Sleeping...
    Sleeping...
    (...)


Injecting Injector and abusing Injector.get
```````````````````````````````````````````

Sometimes code like this is written:

.. code-block:: python

    class A:
        pass

    class B:
        pass

    class C:
        @inject
        def __init__(self, injector: Injector):
            self.a = injector.get(A)
            self.b = injector.get(B)


It is advised to use the following pattern instead:

.. code-block:: python

    class A:
        pass

    class B:
        pass

    class C:
        @inject
        def __init__(self, a: A, b: B):
            self.a = a
            self.b = b


The second form has the benefits of:

* expressing clearly what the dependencies of ``C`` are
* making testing of the ``C`` class easier - you can provide the dependencies
  (whether they are mocks or not) directly, instead of having to mock
  :class:`Injector` and make the mock handle :meth:`Injector.get` calls
* following the common practice and being easier to understand


Injecting dependencies only to pass them somewhere else
```````````````````````````````````````````````````````

A pattern similar to the one below can emerge:

.. code-block:: python

    class A:
        pass

    class B:
        def __init__(self, a):
            self.a = a

    class C:
        @inject
        def __init__(self, a: A):
            self.b = B(a)

Class ``C`` in this example has the responsibility of gathering dependencies of
class ``B`` and constructing an object of type ``B``, there may be a valid reason
for it but in general it defeats the purpose of using ``Injector`` and should
be avoided.

The appropriate pattern is:

.. code-block:: python

    class A:
        pass

    class B:
        @inject
        def __init__(self, a: A):
            self.a = a

    class C:
        @inject
        def __init__(self, b: B):
            self.b = b
