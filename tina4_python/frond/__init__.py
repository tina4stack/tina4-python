# Tina4 Frond — Zero-dependency template engine.
"""
Twig-like template engine built from scratch.

    from tina4_python.frond import Frond

    engine = Frond(template_dir="src/templates")
    output = engine.render("page.html", {"name": "World"})
"""
from tina4_python.frond.engine import Frond

__all__ = ["Frond"]
