Injector - Python dependency injection framework, inspired by Guice
===================================================================

This framework is also similar to snake-guice, but aims for simplification.

While being inspired by Guice, it does not slavishly replicate its API.
Providing a Pythonic API trumps faithfulness.

An Example
----------

*TODO: Write a more useful example.*

Here's a brief, completely contrived, example from the unit tests::

  from injector import Injector, Module, Key, injects, provides

  Weight = Key('Weight')
  Age = Key('Age')
  Description = Key('Description')

  class MyModule(Module):
      @provides(Weight)
      def provide_weight(self):
          return 50.0

      @provides(Age)
      def provide_age(self):
          return 25

      @provides(Description)
      @inject(age=Age, weight=Weight)
      def provide_description(self, age, weight):
          return 'Bob is %d and weighs %0.1fkg' % (age, weight)

  injector = Injector(MyModule())
  assert_equal(injector.get(Description), 'Bob is 25 and weighs 50.0kg')
