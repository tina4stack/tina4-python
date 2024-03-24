from pathlib import Path

from setuptools import find_packages, setup

setup(
    name="tina4_python",
    version="0.1.32",
    description="Tina4Python - This is not a framework for Python",
    long_description=Path("README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="Andre van Zuydam",
    author_email="andrevanzuydam@gmail.com",
    url="https://github.com/tina4stack/tina4-python",
    project_urls={
        "Bug Reports": "https://github.com/tina4stack/tina4-python/issues",
        "Source": "https://github.com/tina4stack/tina4-python",
    },
    license="MIT",
    packages=find_packages(),
    install_requires=[
        "tina4_python>0.1.31",
    ],
    entry_points={"mkdocs.plugins": ["tina4_python = plugin:MetaPlugin"]},
)
