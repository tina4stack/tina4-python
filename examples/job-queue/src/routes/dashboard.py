from tina4_python.Router import get
from src.orm.Job import Job


@get("/")
async def dashboard(request, response):
    jobs = Job().select("*", order_by="created_at desc", limit=50)
    return response.render("pages/dashboard.twig", {"jobs": jobs.to_array()})


@get("/api/jobs")
async def api_jobs(request, response):
    jobs = Job().select("*", order_by="created_at desc", limit=50)
    return response(jobs.to_array())
