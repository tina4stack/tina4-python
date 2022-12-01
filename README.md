================
Tina4Python - This is not a framework for Python
================

Running the system

Requirements

```
pip install poetry
```

Windows
```
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
```
Add to path %APPDATA%\pypoetry\venv\Scripts 

Install

```
poetry init
poetry add tina4_python
poetry add jurigged
```

or 

```
pip install tina4_python
pip install jurigged
```

#### Create a starting app.py file to start with

```
from tina4_python import *
```

Normal "production" server on port 7145
```
poetry run
```

Server with hot reloading
```
poetry run jurigged main.py
```

Server with own port

```
poetry run main.py 7777
```

Done:
 - python pip package
 - basic env file handling
 - basic routing

Todo:
 - localization
 - routing - partially done, supports get & post
 - template handling
 - open api - swagger
 - add jwt form token

Building:
```
python3 -m pip install --upgrade build
python3 -m build
python3 -m pip install --upgrade twine
python3 -m twine upload dist/*
```
    
OR
    
```
poetry build
poetry publish
```
    