Logging
=======

Injector uses standard :mod:`logging` module, the logger name is ``injector``.

By default ``injector`` logger is not configured to print logs anywhere.

To enable ``get()`` tracing (and some other useful information) you need to set ``injector`` logger level to ``DEBUG``. You can do that by executing::

    import logging

    logging.getLogger('injector').setLevel(logging.DEBUG)

or by configuring :mod:`logging` module in any other way.
