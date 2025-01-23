from tina4_python import get
from tina4_python.Template import Template
from ..orm.User import User

@get("/some/other/page")
async def get_some_page(request, response):
    user = User()
    user.load('id = 1')
    html = Template.render_twig_template("index.twig", data={"user": user.to_dict()})
    return response(html)