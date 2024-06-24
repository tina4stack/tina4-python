

def description(*arguments):
    def actual_description(param):
        print("Swagger  Description ", param, arguments)
        if len(arguments) > 0:
            # decide what to do
            pass

    return actual_description

def secure(*arguments):
    def actual_secure(param):
        print("Swagger  Description ", param, arguments)
        if len(arguments) > 0:
            # decide what to do
            pass

    return actual_secure


def tags(*arguments):
    def actual_tags(param):
        print("Swagger  Description ", param, arguments)
        if len(arguments) > 0:
            # decide what to do
            pass

    return actual_tags

def example(*arguments):
    def actual_example(param):
        print("Swagger  Description ", param, arguments)
        if len(arguments) > 0:
            # decide what to do
            pass

    return actual_example


def params(*arguments):
    def actual_params(param):
        print("Swagger  Description ", param, arguments)
        if len(arguments) > 0:
            # decide what to do
            pass

    return actual_params