#
# Tina4 - This is not a 4ramework.
# Copy-right 2007 - current Tina4
# License: MIT https://opensource.org/licenses/MIT
#
# flake8: noqa: E501
import csv
import io
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
        """
        Pagination result with all the needed information
        :return:
        """

        return {"recordsTotal": self.total_count, "recordsOffset": self.skip, "recordCount": self.count,
                "recordsFiltered": self.total_count, "fields": self.columns, "data": self.to_array(),
                "dataError": self.error}



    def to_csv(self, quoting=csv.QUOTE_ALL):
        """
        Makes a csv file
        :param quoting:
        :return:
        """
        if not self.columns:
            return ''
        output = io.StringIO()
        writer = csv.writer(output, quoting=quoting)
        writer.writerow(self.columns)
        if self.records:
            first_record = self.records[0]
            if isinstance(first_record, dict):
                rows = [[str(row.get(col, '')) for col in self.columns] for row in self.records]
            else:
                rows = [list(map(str, row)) for row in self.records]
            writer.writerows(rows)
        return output.getvalue()
