"""Regression: Response.file() must not serve a file outside its root.

The bug: the natural spelling of a download route,

    response.file("downloads/" + name)      # name = "../secret.env"

served any file the process could read. Measured before the fix at 200 with
the contents of /etc/passwd (9344 bytes).

Two properties are pinned here, and BOTH matter:

  * the single-hop escape ``downloads/../secret.env`` is refused. This is the
    discriminating case. A deep ``../../../..`` chain can climb above / and
    resolve to nothing, so it returns 404 on a VULNERABLE build too - a test
    that only checks the deep chain passes against the bug.
  * a legitimate file inside the root is still served. Without this negative
    control, a "fix" that simply breaks file() would pass.

No mocks: real files on a real temp filesystem.
"""

import os

import pytest

from tina4_python.core.response import Response


@pytest.fixture()
def confined(tmp_path, monkeypatch):
    """A project root with a public download dir and a secret beside it."""
    (tmp_path / "downloads").mkdir()
    (tmp_path / "downloads" / "report.txt").write_text("PUBLIC REPORT\n")
    (tmp_path / "secret.env").write_text("TINA4_SECRET=super-secret-value\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_file_serves_a_file_inside_the_root(confined):
    """NEGATIVE CONTROL - a fix that breaks file() outright must not pass."""
    response = Response()
    response.file("downloads/report.txt")
    assert response.status_code == 200
    assert response.content == b"PUBLIC REPORT\n"


def test_file_refuses_single_hop_escape(confined):
    """The reliable discriminator: one ``..`` reaching a real file next door."""
    response = Response()
    response.file("downloads/../secret.env")
    assert response.status_code == 403
    assert b"super-secret-value" not in response.content


def test_file_refuses_deep_traversal_chain(confined):
    response = Response()
    response.file("../../../../../../etc/passwd")
    assert response.status_code == 403


def test_file_refuses_absolute_path_outside_a_declared_root(confined):
    """No ``..`` at all - containment, not the ``..`` check, has to catch this.

    Containment applies ONLY when the caller declared a root, so the root is
    what makes this 403.
    """
    response = Response()
    response.file("/etc/passwd", root=str(confined))
    assert response.status_code == 403


def test_file_serves_an_absolute_path_when_no_root_is_declared(confined):
    """REGRESSION CONTROL. Confinement once defaulted to the cwd, so every
    legitimate absolute path outside the project answered 403 - a missing file
    reported Forbidden instead of Not Found. Unrooted, an absolute path is the
    caller's business (Express res.sendFile, Rails send_file, ASP.NET
    PhysicalFile all serve one), so this must NOT be 403.
    """
    outside = confined.parent / "outside.txt"
    outside.write_text("OUTSIDE\n")
    response = Response()
    response.file(str(outside))
    assert response.status_code == 200
    assert response.content == b"OUTSIDE\n"

    missing = Response()
    missing.file("/nonexistent/path/to/file.css")
    assert missing.status_code == 404


def test_file_honours_an_explicit_root(confined):
    """With root= given, the confinement follows it rather than the cwd."""
    os.chdir(confined / "downloads")
    response = Response()
    response.file("report.txt", root=str(confined / "downloads"))
    assert response.status_code == 200
    assert response.content == b"PUBLIC REPORT\n"

    escaped = Response()
    escaped.file("../secret.env", root=str(confined / "downloads"))
    assert escaped.status_code == 403
