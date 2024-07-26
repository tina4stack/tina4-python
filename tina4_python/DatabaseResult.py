#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import base64
import json


class DatabaseResult:
    def __init__(self, _records=None, _columns=None, _error=None):
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

    def to_array(self):
        if self.error is not None:
            return {"error": self.error}
        elif len(self.records) > 0:
            # check all the records - if we get bytes we base64encode them for the json to work
            json_records = []
            for record in self.records:
                json_record = {}
                for key in record:
                    if isinstance(record[key], bytes):
                        json_record[key] = base64.b64encode(record[key]).decode('utf-8')
                    else:
                        json_record[key] = record[key]
                json_records.append(json_record)
            return json_records
        else:
            return []

    def to_json(self):
        return json.dumps(self.to_array())

    def __getitem__(self, item):
        if item < len(self.records):
            return self.records[item]
        else:
            return {}

    def __str__(self):
        return self.to_json()
