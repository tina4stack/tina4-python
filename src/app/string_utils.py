"""String utilities — simple, tested, no deps."""
def slugify(text):
    return text.lower().replace(" ", "-")

def truncate(text, length=100):
    return text[:length] + "..." if len(text) > length else text
