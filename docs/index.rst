.. Injector documentation master file, created by
   sphinx-quickstart on Mon Sep 16 02:58:17 2013.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to Injector's documentation!
====================================

.. image:: https://travis-ci.org/alecthomas/injector.png?branch=master
   :alt: Build status
   :target: https://travis-ci.org/alecthomas/injector

Introduction
------------

Dependency injection as a formal pattern is less useful in Python than in other languages, primarily due to its support for keyword arguments, the ease with which objects can be mocked, and its dynamic nature.

That said, a framework for assisting in this process can remove a lot of boiler-plate from larger applications. That's where Injector can help. It automatically and transitively provides keyword arguments with their values. As an added benefit, Injector encourages nicely compartmentalised code through the use of :ref:`modules <module>`.

While being inspired by Guice, it does not slavishly replicate its API. Providing a Pythonic API trumps faithfulness.

Contents:

.. toctree::
   :maxdepth: 1

   changelog
   terminology
   testing
   scopes
   logging
   api
