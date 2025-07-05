del dist/*.whl
del dist/*.tar.gz
uv export --format requirements-txt
uv build --no-sources
uv publish --username __token__ --password %UV_PYPI_PASSWORD%
