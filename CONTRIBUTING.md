How to contribute to Injector
==========================

Thank you for considering contributing to `Injector`!


First time setup
------------------

1. Create a virtualenv.

```bash
# macOS/Linux
python3 -m venv .venv
source .venv/bin/activate
````

```bash
# Windows
py -3 -m venv venv
venv\Scripts\activate
```

2. Install `Injector` in editable mode with development dependencies.

```bash
pip install -e '.[dev]'
```


Running the tests
------------------

```bash
pytest
```
