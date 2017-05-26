.. _faq:

Frequently Asked Questions
==========================

If I use :func:`~injector.inject` or scope decorators on my classess will I be able to create instances of them without using Injector?
---------------------------------------------------------------------------------------------------------------------------------------

Yes. Scope decorators don't change the way you can construct your class
instances without Injector interaction.

I'm calling this method (/function/class) but I'm getting "TypeError: XXX() takes exactly X arguments (Y given)"
----------------------------------------------------------------------------------------------------------------

Example code:

.. code-block:: python

    class X:
        @inject
        def __init__(self, s: str):
            self.s = s

    def configure(binder):
        binder.bind(s, to='some string')

    injector = Injector(configure)
    x = X()

Result?

::

    TypeError: __init__() takes exactly 2 arguments (1 given)

Reason? There's *no* global state that :class:`Injector` modifies when
it's instantiated and configured. Its whole knowledge about bindings etc.
is stored in itself. Moreover :func:`inject` will *not* make
dependencies appear out of thin air when you for example attempt to create
an instance of a class manually (without ``Injector``'s help) - there's no
global state ``@inject`` decorated methods can access.

In order for ``X`` to be able to use bindings defined in ``@inject``
decoration :class:`Injector` needs to be used (directly or indirectly)
to create an instance of ``X``. This means most of the time you want to just
inject ``X`` where you need it, you can also use :meth:`Injector.get` to obtain
an instance of the class (see its documentation for usage notes).
