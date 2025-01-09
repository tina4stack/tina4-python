FROM python:3.12-alpine

RUN apk update && apk add python3-dev gcc libc-dev
RUN apk add --update alpine-sdk

RUN pip install poetry
RUN pip install jurigged
RUN pip install tina4_python

WORKDIR /app



