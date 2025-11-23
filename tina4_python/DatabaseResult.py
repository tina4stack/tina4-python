#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import base64
import json
import datetime
import os
import shutil
from decimal import Decimal
import tina4_python
from tina4_python.CRUD import CRUD
from tina4_python.Debug import Debug
from tina4_python.HtmlElement import add_html_helpers
import re
from tina4_python.Template import Template
from tina4_python.Constant import *
from tina4_python.Router import Router

add_html_helpers(globals())


class DatabaseResult(CRUD):
    def __init__(self, _records=None, _columns=None, _error=None, count=None, limit=None, skip=None, sql=None):
        """
        DatabaseResult constructor
        :param _records:
        :param _columns:
        :param _error:
        :param count:
        :param limit:
        :param skip:
        """
        super().__init__()
        if count is not None:
            self.total_count = count
        else:
            self.total_count = 0

        if limit is not None:
            self.limit = limit
        else:
            self.limit = 0

        if skip is not None:
            self.skip = skip
        else:
            self.skip = 0

        if _records is not None:
            self.records = _records
        else:
            self.records = []

        self.count = len(self.records)

        if _columns is not None:
            self.columns = _columns
        else:
            self.columns = []

        if sql is not None:
            self.sql = sql

        self.error = _error

    def to_paginate(self):

        return {"recordsTotal": self.total_count, "recordsOffset": self.skip, "recordCount": self.count,
                "recordsFiltered": self.total_count, "fields": self.columns, "data": self.to_array(),
                "dataError": self.error}

    def to_array(self, _filter=None):
        """
        Creates an array or list of the items
        :return:
        """
        if self.error is not None:
            return {"error": self.error}
        elif len(self.records) > 0:
            # check all the records - if we get bytes we base64encode them for the json to work
            json_records = []
            for record in self.records:
                json_record = {}
                for key in record:
                    if isinstance(record[key], Decimal):
                        json_record[key] = float(record[key])
                    elif isinstance(record[key], (datetime.date, datetime.datetime)):
                        json_record[key] = record[key].isoformat()
                    elif isinstance(record[key], memoryview):
                        json_record[key] = base64.b64encode(record[key].tobytes()).decode('utf-8')
                    elif isinstance(record[key], bytes):
                        json_record[key] = base64.b64encode(record[key]).decode('utf-8')
                    else:
                        json_record[key] = record[key]

                if _filter is not None:
                    json_record = _filter(json_record)

                json_records.append(json_record)

            return json_records
        else:
            return []

    def to_list(self, _filter=None):
        return self.to_array(_filter)

    def to_json(self, _filter=None):
        return json.dumps(self.to_array(_filter))

    def __iter__(self):
        return iter(self.to_array())

    def __getitem__(self, item):
        if item < len(self.records):
            return self.records[item]
        else:
            return {}

    def __str__(self):
        return self.to_json()

    def get_table_name(self, query):
        """
        Gets the table name
        :param query:
        :return:
        """
        # Remove LIMIT and everything after
        query = re.sub(r'\s+LIMIT\s+.*$', '', query, flags=re.I)
        # Find innermost FROM table (non-subquery)
        from_parts = re.findall(r'\bFROM\s+([a-zA-Z0-9_]+)(?:\s+AS\s+\w+)?(?:\s+|$|\))', query, re.I)
        return from_parts[-1] if from_parts else None

    def ensure_crud_template(self, filename: str):
        """
        Checks to see if the template exists otherwise copies it over
        :param filename:
        :return:
        """
        root = tina4_python.root_path
        target_dir = os.path.join(root, "src", "templates", "crud")
        target_path = os.path.join(target_dir, filename)
        Debug.info("CRUD Template", target_path)

        if os.path.exists(target_path):
            return target_path  # already exists

        os.makedirs(target_dir, exist_ok=True)

        source_path = os.path.join(os.path.dirname(__file__), "templates", "components", "crud.twig")

        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Default template {filename} not found")

        shutil.copy(source_path, target_path)
        return target_path

    def to_crud(self, request, options=None):
        Debug.info(self.records)
        table_name = self.get_table_name(self.sql)

        async def post_record(request, response):
            return response("OK", HTTP_OK, APPLICATION_JSON)

        async def update_record(request, response):
            return response("OK", HTTP_OK, APPLICATION_JSON)

        async def delete_record(request, response):
            return response("OK", HTTP_OK, APPLICATION_JSON)

        Router.add(TINA4_POST, os.path.join(request.url, table_name), post_record)
        Router.add(TINA4_POST, os.path.join(request.url, table_name, "{id}"), update_record)
        Router.add(TINA4_DELETE, os.path.join(request.url, table_name, "{id}"), delete_record)

        twig_file = self.ensure_crud_template(table_name + ".twig")

        fields = []
        for column in self.columns:
            fields.append({"name": column, "label": Template.get_nice_label(column)})

        html = Template.render(twig_file.replace(os.path.join(tina4_python.root_path, "src", "templates"), ""),
                               {"columns": fields, "records": self.records, "table_name": table_name,
                                "options": options})

        return html
