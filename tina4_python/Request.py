class Request:
    """
    Request object to store parameters, headers, etc.
    """

    def __init__(self, params=None, headers=None, request=None):
        self.params = params if params is not None else {}
        self.headers = headers if headers is not None else {}
        self.request = request if request is not None else {}
        # add more stuff here as needed
