# ChangeLog for Injector

## 0.7.8

- Exception is raised when Injector can't install itself into a class instance due to __slots__ presence
- Some of exception messages are now more detailed to make debugging easier when injection fails

## 0.7.7

- Made AssistedBuilder behave more explicitly: it can build either innstance of a concrete class (``AssistedBuilder(cls=Class)``) or it will follow Injector bindings (if exist) and construct instance of a class pointed by an interface (``AssistedBuilder(interface=Interface)``). ``AssistedBuilder(X)`` behaviour remains the same, it's equivalent to ``AssistedBuilder(interface=X)``

## 0.7.6

- Auto-convert README.md to RST for PyPi.

## 0.7.5

- Added a ChangeLog!
- Added support for using Python3 annotations as binding types.
