#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import base64
import json
import datetime
from decimal import Decimal


class DatabaseResult:
    def __init__(self, _records=None, _columns=None, _error=None, count=None, limit=None, skip=None):
        """
        DatabaseResult constructor
        :param _records:
        :param _columns:
        :param _error:
        :param count:
        :param limit:
        :param skip:
        """
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

        self.error = _error

    def to_paginate(self):

        return {"recordsTotal": self.total_count, "recordsOffset": self.skip,  "recordCount": self.count, "recordsFiltered": self.total_count, "fields": self.columns, "data": self.to_array(), "dataError": self.error}

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

