from tina4_python.Debug import Debug

class CRUD:

    def __init__(self):
        self.records = []

    def to_crud(self, request):
        html = "1121112222AAA"

        Debug.info("RECORDS", self.records)
        for record in self.records:
            html += record["name"]+"\n"

        return html.__str__()


