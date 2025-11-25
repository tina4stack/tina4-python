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
from tina4_python.CRUD import CRUD
class DatabaseResult(CRUD):
    def __init__(self, _records=None, _columns=None, _error=None, count=None, limit=None, skip=None, sql=None, dba=None):
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

        if dba is not None:
            self.dba = dba

        self.error = _error

    def to_paginate(self):

        return {"recordsTotal": self.total_count, "recordsOffset": self.skip, "recordCount": self.count,
                "recordsFiltered": self.total_count, "fields": self.columns, "data": self.to_array(),
                "dataError": self.error}




