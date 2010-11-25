Injector - Python dependency injection framework, inspired by Guice
===================================================================

This framework is also similar to snake-guice, but aims for simplification.

While being inspired by Guice, it does not slavishly replicate its API.
Providing a Pythonic API trumps faithful replication.

An Example
----------

Here's a brief, completely contrived, example from the unit tests::

  from injector import Injector, Module, Key, injects, provides

  Weight = Key('Weight')
  Age = Key('Age')

  class MyModule(Module):
      @provides(Weight)
      def provide_weight(self):
          return 50.0

      @provides(Age)
      def provide_age(self):
          return 25

      # TODO(alec) Make provides/inject order independent.
      @provides(str)
      @inject(age=Age, weight=Weight)
      def provide_description(self, age, weight):
          return 'Bob is %d and weighs %0.1fkg' % (age, weight)

  assert_equal(Injector(MyModule()).get(str), 'Bob is 25 and weighs 50.0kg')
