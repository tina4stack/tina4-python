### Tina4Python - This is not a framework for Python

Tina4Python is a light-weight routing and twig based templating system based on the [Tina4](https://github.com/tina4stack/tina4-php) stack which allows you to write websites and API applications very quickly.
.
### System Requirements

- Install Poetry:
```bash
curl -sSL https://install.python-poetry.org | python3 - 
```

- Install Jurigged (Enables Hot Reloading):
```bash
pip install jurigged
```

### Quick Start

After installing poetry you can do the following:
```bash
poetry new project-name
cd project-name
poetry add tina4_python
poetry add jurigged
```
Create an entry point for Tina4 called ```app.py``` and add the following to the file
```python
from tina4_python import *
```

### Overview
The basic tina4 project uses an autoloader methodology from the src folder
All the source folders you should need are created there and they are run from __init__.py

If you are developing on Tina4, make sure you copy the public folder from tina4_python into src

### Installation

#### Windows

1.) Install Poetry:
```powershell
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
```

2.) Add the following path to the system PATH:
```
%APPDATA%\pypoetry\venv\Scripts
```

3.) Install Tina4Python and Jurigged:
```bash
poetry add tina4_python
poetry add jurigged
```

**or**

```bash
pip install tina4_python
pip install jurigged
```

### Usage

After defining templates and routes, run the Tina4Python server:

- **Normal Server**:
```bash
poetry run python app.py
```

- **Server with Hot Reloading**:
```bash
poetry run jurigged app.py
```

- **Server on a Specific Port**:
```bash
poetry run python app.py 7777
```

- **Server to not autostart **:
```bash
poetry run python app.py manual
```
  
- **Server with alternate language** (for example fr = French):
```bash
poetry run python app.py fr
```

Add more translations by going [here](TRANSLATIONS.md)

### Templating
Tina4 uses Jinja2 (Twig) templating to provide a simple and efficient way to create web pages.

1.) **Twig Files**: Add your Twig files within the `src/templates` folder. For instance, you might create files like `index.twig`, `base.twig`, etc., containing your HTML structure with Twig templating syntax for dynamic content.

2.) **Using Twig**: In these Twig files, you can use Twig syntax to embed dynamic content, control structures, variables, and more. For example:

```twig
<!-- index.twig -->
<!DOCTYPE html>
<html>
<head>
    <title>Welcome</title>
</head>
<body>
    <h1>Hello, {{ name }}!</h1>
</body>
</html>
```

### Defining Routes


The routing in Tina4Python can be defined in the `__init__.py` file or any file used as an entry point to your application. Tina4Python provides decorators to define routes easily.

1.) **Creating Routes**: Define routes using decorators from Tina4Python to handle HTTP requests.

Example:
```python
from tina4_python.Router import get
from tina4_python.Response import Response
@get("/hello")
async def hello(request, response):
  return response("Hello, World!")
```

This code creates a route for a GET request to `/hello`, responding with "Hello, World!".

2.) **Route Parameters**: You can define route parameters by enclosing variables with curly braces { }. The parameters are passed to the function as arguments.

 Example:
```python
from tina4_python.Router import get
from tina4_python.Response import Response

@get("/hello/{name}")
async def greet(**params): #(request, response)
   name = params['request'].params['name']
   return params['response'](f"Hello, {name}!") # return response()
````

This code creates a route for a GET request to `/hello/{name}`, where `name` is a parameter in the URL. The function `greet` accepts this parameter and responds with a personalized greeting.

Example:
- Visiting `/hello/John` will respond with "Hello, John!"
- Visiting `/hello/Alice` will respond with "Hello, Alice!"

3.) POST routes now require jwt token or API key to validate requests with an Authorization header
```
Authorization: Bearer <token>
```
You can generate tokens using tina4_python.tina4_auth which takes in a payload parameter which is a dictionary:
#### Example of a post with a form, assume the route is ```/capture```

You need the following twig file in the ```src/templates``` folder called ```something.twig```

```twig something.twig
<form method="post">
    <input name="email" type="text" placeholder="Email">
    <button type="submit">Send</button>
    <input type="hidden" name="formToken" value="{{ token }}" >
</form>
```

You can add the following code to ```src/routes/example.py```

```python
# get router which renders the twig form html
@get("/capture")
async def capture_get(request, response):
    # get a token to add to the form
    token = tina4_python.tina4_auth.get_token({"data": {"formName": "capture"}})
    html = Template.render_twig_template("somefile.twig", {"token": token})
    return response(html)

# returns back to the user the form data that has been posted
@post("/capture")
async def capture_post(request, response):
    return response(request.body)
```

In your ```src/__init__.py``` add the following code

```python
from .routes.example import *
```
Generate tokens with the following code as per the example above, tokens carry a payload and we add an additional ```expires``` value to the token based on the env variable ```TINA4_TOKEN_LIMIT``` 

```python
import tina4_python

tina4_python.tina4_auth.get_token({"data": {"something":"more"}})
```

OR 

For ease of use you can supply an `API_KEY` param to your .env with a secret of your choice to use:

```dotenv
API_KEY=somehash
```


### Features
| Completed                  | To Do                |
|----------------------------|----------------------|
| Python pip package         |                      |
| Basic environment handling |                      |
| Basic routing              | OpenAPI (Swagger)    |
| Enhanced routing           |                      |
| CSS Support                |                      |
| Image Support              |                      |
| Localization               |                      |
| Error Pages                |                      |
| Template handling          |                      |
| Form posting               |                      |
| Migrations                 |                      |
| Colored Debugging          |                      |
|                            | Database Abstraction |

### Database

```bash

dba = Database("sqlite3:test.db", "username", "password")
dba = Database("mysql:localhost/3306:myschema", "username", "password")
dba = Database("postgres:localhost/5432:myschema", "username", "password")
dba = Database("firebird:localhost/3050:/home/database/FIREBIRD.FDB", "username", "password")

NoSQL support

dba = Database("mongodb:localhost/27017:mycollection", "username", "password")
dba = Database("firebase:https://your_storage.firebaseio.com", "username", "password")


records = dba.fetch("select * from table where something = ? and something2 = ?", params=["something", "something2"], limit=10, skip=5)

print (records)

print (records.to_json())

{
  id : 1
  something: "something",
  something2: "something2"
}

print(records[0].id)

1

record = dba.fetch_one("select * from table where something = ? and something2 = ?", params=["something", "something2"])

print(record.id)

print (records.to_json())

1

dba.execute ("update table set something = ? and something2 = ? where id = ?", params=["something", "something2", 1])
dba.execute ("delete from table where id = ?", params=[1])

dba.start_transaction()

dba.roll_back()

dba.commit()

dba.select(["id", "something", "something2"], "table_name", filter={"id": 1}, limit=10, skip=0)
dba.select(["id", "something", "something2"], "table_name", filter=[{"id": 1}, {"id": 2}], limit=10, skip=0)
dba.select(["id", "something", "sum(id)"])
   .from(["table"])
   .join(["tabel2"])
   .on([""])
   .and([{"id": 1}])
   .where({"id" : 2}, "id = ?", [{"id": 2}])
   .having()
   .group_by()
   .order_by(["id"])

dba.update(table_name="table_name", records.fromJSON(json_string))
dba.update(table_name="table_name", records, primary_key="id")

dba.update(table_name="table_name", record, primary_key="id") # primary key implied by first key value pair
dba.insert(table_name="table_name", dba.from_json(json_string))
dba.insert(table_name="table_name", {"id": 1, "something": "hello", "something2": "world"})
dba.insert(table_name="table_name", [{"id": 1, "something": "hello", "something2": "world"}, 
{"id": 2, "something": "hello2", "something2": "world2"}])

dba.delete("table_name", record, primary_key="id")
dba.delete("table_name", filter={"id": 1})

dba.delete("table_name", filter=[{"id": 1}, {"id": 2}])




```


### Building and Deployment

#### Using Python

Building the package:
 ```bash
python3 -m pip install --upgrade build
python3 -m build
python3 -m pip install --upgrade twine
python3 -m twine upload dist/*
 ```

#### Using Poetry

Building the package:
```bash
poetry build
```

Publishing the package:
```bash
poetry publish
```

#### Running tests & checks

PyTests
```
poetry run pytest ./tests
```

Flake8 Code tests
```
poetry run flake8 ./tina4_python
```
