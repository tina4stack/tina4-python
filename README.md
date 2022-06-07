================
Tina4Python - This is not a framework for Python
================

Running the system

Install
    ``poetry install tina4_python``
Normal "production" server on port 7145
    ``poetry run``

Server with hot reloading
    ``poetry run jurigged main.py``

Server with own port
    ``poetry run main.py 7777``

Todo:
 - localization
 - routing
 - template handling
 - open api - swagger
 -

Building:
    ``python3 -m pip install --upgrade build``

    ``python3 -m build``

    ``python3 -m pip install --upgrade twine``
    
    ``python3 -m twine upload dist/*``
