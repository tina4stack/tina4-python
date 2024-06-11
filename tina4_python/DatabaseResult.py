#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import json


class DatabaseResult:
    def __init__(self, _records=None, _columns=None, _error=None):
        if _records is not None:
            self.records = _records
        else:
            self.records = []

        if _columns is not None:
            self.columns = _columns
        else:
            self.columns = []

        self.error = _error

    def to_json(self):
        if self.error is not None:
            return json.dumps({"error": self.error})
        elif len(self.records) > 0:
            return json.dumps(self.records)
        else:
            return "[]"

    def __getitem__(self, item):
        if item < len(self.records):
            return self.records[item]
        else:
            return {}

    def __str__(self):
        return self.to_json()
