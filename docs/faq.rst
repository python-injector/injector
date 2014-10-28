.. _faq:

Frequently Asked Questions
==========================

* If I use :func:`~injector.inject` or scope decorators on my classess will
  I be able to create instances of them without using Injector?

    Yes. Scope decorators don't change the way you can construct your class
    instances without Injector interaction.

    :func:`~injector.inject` changes the constructor semantics slightly
    if you use it to decorate your class - in this case you need to use
    keyword arguments to pass values to the constructor.

    For example:

    .. code-block:: python

        @inject(s=str)
        class X(object):
            pass


        # will fail
        X('a')

        # will work
        X(s='a')
