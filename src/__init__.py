#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
import os
import sys
import  tina4_python
from datetime import datetime
from src.app.MiddleWare import MiddleWare
from src.orm.Log import Log
from tina4_python import Migration, tina4_auth
from tina4_python.Constant import HTTP_OK, APPLICATION_XML
from tina4_python.ORM import orm
from tina4_python.Migration import migrate
from tina4_python.Template import Template
from tina4_python.Debug import Debug
from tina4_python.Router import get, cached, secured
from tina4_python.Router import post, middleware, noauth
from tina4_python.Database import Database
from tina4_python.Swagger import description, secure, summary, example, tags, params

import xml.etree.ElementTree as ET
from xml.dom import minidom

dba = Database("sqlite3:test3.db", "username", "password")
migrate(dba)

orm(dba)

def dict_to_xml(tag, data):
    elem = ET.Element(tag)
    if "@attributes" in data:
        for k, v in data["@attributes"].items():
            elem.set(k, v)
    for k, v in data.items():
        if k == "@attributes":
            continue
        if k == "value":
            elem.text = v
            continue
        if isinstance(v, dict):
            sub_elem = dict_to_xml(k, v)
            elem.append(sub_elem)
        else:
            sub_elem = ET.SubElement(elem, k)
            sub_elem.text = str(v)
    return elem


def generate_xml(xml_dict):
    root_tag = list(xml_dict.keys())[0]
    root = dict_to_xml(root_tag, xml_dict[root_tag])
    xml_str = ET.tostring(root, encoding='unicode', method='xml')
    dom = minidom.parseString(xml_str)
    return dom.toprettyxml(indent="  ")



@get("/some/page")
async def some_page(request, response):
    global dba
    result = dba.fetch("select id, name from test_record where id = 2")

    html = Template.render_twig_template("index.twig", data={"persons": result.to_array()})
    return response(html)

@post("/some/page")
@secure()
async def some_page_post(request, response):
    print(request.params)
    print(request.body)

    token = tina4_auth.get_payload(request.params["formToken"])
    print(token)


@get("/hello/{name}")
@description("Some description")
@params(["limit=10", "offset=0"])
@summary("Some summary")
@tags(["hello", "cars"])
async def greet(**params):  #(request, response)
    Debug("Hello", params['request'], file_name="test.log")
    name = params['request'].params['name']
    sys.stdout.flush()
    return params['response'](f"Hello, {name}  !")  # return response()


@post("/hello/{name}")
@description("Some description")
@summary("Some summary")
@example({"id": 1, "name": "Test"})
@tags("OK")
@secure()
async def greet_again(**params):  #(request, response)
    print(params['request'])
    return params['response'](params['request'].body)  # return response()


@post("/upload/files")
async def upload_file(request, response):
    return response(request.body)


@get("/system/roles")
async def system_roles(request, response):
    print("roles")
    a = a / 0


@get("/session/set")
async def session_set(request, response):
    request.session.set("name", "Tina")
    request.session.set("user", {"name": "Tina", "email": "test@email.com", "date_created": datetime.now()})
    print("session set")

@get("/session/get")
async def session_get(request, response):

    for pair in request.session:
        print(pair)


    print("session get")


@middleware(MiddleWare, ["before_and_after"])
@get("/system/roles/data")
async def system_roles(request, response):
    print("roles ggg")

    return response("OK")


@get("/system/roles/{id}")
async def system_roles(request, response):
    print("roles id")


@middleware(MiddleWare)
@get("/test/redirect")
async def redirect(request, response):
    return response.redir
    ect("/hello/world")


@cached(False)
@get("/mee")
async def index_html(request, response):
    request.session.set("name", "Tina4 222")

    return response(Template.render_twig_template("index.twig"))


@get("/test/vars")
async def run_test_vars(request, response):
    print("<pre>")
    print("vars")
    print(request.params)

@get("/healthcheck")
@secured()
async def get_healthcheck(request, response):
    if os.path.isfile(tina4_python.root_path + "/broken"):
        Debug.error("broken", tina4_python.root_path + "/broken")
        return response("Broken", 503)
    return response("OK")


@post("/generic/post")
@middleware(MiddleWare)
@noauth()
async def some_generic_post(request, response):

    #determine the WSDL operation
    #call the method

    xml_response = {"Envelope" : {"@attributes": {"xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                                                  "xmlns:xsd":"http://www.w3.org/2001/XMLSchema",
                                                  "xmlns:soap":"http://schemas.xmlsoap.org/soap/envelope/"},
                                  "Body": {
                                      "@attributes": {},
                                      "GetVersionResponse": {
                                          "@attributes": {"xmlns": "DVSE.WebApp.CISService"},
                                          "GetVersionResult": {"value": "1.0.0.0"},
                                          "OrderItems": [{
                                            "OrderId": 11,
                                            "Description":"Test"
                                          }]
                                      }
                                  }
                              }
                    }

    return response(generate_xml(xml_response), HTTP_OK, APPLICATION_XML)

Debug.info("Routes")
from .routes import meme
from .routes import test_queue
from .routes import crud
Debug.info("Done Routes")