"""Minimal Django benchmark app (single-file).

Usage:
    gunicorn -w 4 -b 0.0.0.0:8104 app_django:application
    or: python app_django.py  (dev server)
"""
import os
import sys
import json

import django
from django.conf import settings
from django.http import JsonResponse
from django.urls import path

# Minimal Django settings
if not settings.configured:
    settings.configure(
        DEBUG=False,
        SECRET_KEY="benchmark-secret-key-not-for-production",
        ROOT_URLCONF=__name__,
        ALLOWED_HOSTS=["*"],
        MIDDLEWARE=[],
    )
    django.setup()


def hello(request):
    return JsonResponse({"message": "Hello, World!"})


urlpatterns = [
    path("api/hello", hello),
]

# WSGI application for gunicorn
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()

if __name__ == "__main__":
    from django.core.management import execute_from_command_line
    sys.argv = ["app_django.py", "runserver", "0.0.0.0:8104", "--noreload"]
    execute_from_command_line(sys.argv)
