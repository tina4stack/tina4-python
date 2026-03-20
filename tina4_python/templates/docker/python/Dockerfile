# Tina4 Python — pip
# docker build -f docker/python/Dockerfile -t my-app .
# docker run -p 7145:7145 my-app

FROM python:3.13-alpine AS builder
RUN apk add --no-cache build-base libffi-dev
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir --prefix=/install .

# Strip unused stdlib, caches, and binaries
RUN set -e; \
    find /usr/local/lib/python3.13 /install/lib -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
    rm -rf /usr/local/lib/python3.13/test \
           /usr/local/lib/python3.13/tkinter \
           /usr/local/lib/python3.13/idlelib \
           /usr/local/lib/python3.13/turtledemo \
           /usr/local/lib/python3.13/ensurepip \
           /usr/local/lib/python3.13/lib2to3 \
           /usr/local/lib/python3.13/pydoc_data \
           /usr/local/lib/python3.13/pydoc.py \
           /usr/local/lib/python3.13/turtle.py \
           /usr/local/lib/python3.13/doctest.py \
           /usr/local/lib/python3.13/xmlrpc \
           /usr/local/lib/python3.13/curses \
           /usr/local/lib/python3.13/dbm \
           /usr/local/lib/python3.13/venv \
           /usr/local/lib/python3.13/distutils \
           /usr/local/lib/python3.13/ctypes \
           /usr/local/lib/python3.13/unittest \
           /usr/local/lib/python3.13/_pyrepl \
           /usr/local/lib/python3.13/wsgiref \
           /usr/local/lib/python3.13/config-* \
    ; \
    cd /usr/local/lib/python3.13/lib-dynload && \
    rm -f _tkinter* _curses* _dbm* _lzma* _bz2* \
          _test* audioop* nis* ossaudio* \
          _ctypes_test* _xxtestfuzz* \
          _multiprocessing* _xxsubinterpreters* _xxinterpchannels* \
    ; \
    find /install/lib -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null; \
    strip /usr/local/bin/python3.13 2>/dev/null; \
    strip /usr/local/lib/libpython3.13.so.1.0 2>/dev/null; \
    true

FROM alpine:3.21
RUN apk add --no-cache libffi
WORKDIR /app

COPY --from=builder /usr/local/bin/python3.13 /usr/local/bin/python
COPY --from=builder /usr/local/lib/libpython3.13.so.1.0 /usr/local/lib/libpython3.13.so.1.0
COPY --from=builder /usr/local/lib/python3.13 /usr/local/lib/python3.13
COPY --from=builder /install/lib /usr/local/lib
COPY --from=builder /app /app

RUN ln -s /usr/local/bin/python /usr/local/bin/python3 && \
    ln -s /usr/local/lib/libpython3.13.so.1.0 /usr/local/lib/libpython3.13.so && \
    ldconfig /usr/local/lib 2>/dev/null || true

EXPOSE 7145
CMD ["python", "app.py", "0.0.0.0:7145"]
