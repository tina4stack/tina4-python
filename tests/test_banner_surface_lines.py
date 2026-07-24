"""Lock-in: the startup banner only advertises surfaces that are REACHABLE.

Regression this pins down (issue #99)
-------------------------------------
The banner printed

    Swagger:   http://localhost:7146/swagger
    Dashboard: http://localhost:7146/__dev

unconditionally. In production (or with TINA4_DEBUG off) both of those return
404, so the banner (a) told an operator a dev surface was exposed when it was
not, and (b) sent a developer to a dead link. Worse, an operator reading
"Dashboard:" in a production log had no way to tell a real exposure from a
cosmetic line.

``banner_surface_lines`` is deliberately a PURE function of (port, two
booleans) so this contract is testable without booting a server and grepping
stdout. Pure function, no dependency, no double -- this is not a mock test.

Parity: PHP ``App::bannerSurfaceLines``, Ruby ``Tina4.banner_surface_lines``,
Node ``bannerSurfaceLines`` -- all four render the same banner rows.
"""

from tina4_python.core.server import banner_surface_lines

PORT = 7146


def test_both_off_emits_nothing() -> None:
    """Production: neither surface is reachable, so neither is advertised."""
    swagger_line, dashboard_line = banner_surface_lines(
        PORT, swagger_enabled=False, dev_admin_enabled=False
    )
    assert swagger_line == ""
    assert dashboard_line == ""


def test_both_off_never_leaks_a_path() -> None:
    """Negative: the words /swagger and /__dev must not appear at all."""
    combined = "".join(
        banner_surface_lines(PORT, swagger_enabled=False, dev_admin_enabled=False)
    )
    assert "/swagger" not in combined
    assert "/__dev" not in combined


def test_swagger_only() -> None:
    """Swagger exposed in production (TINA4_SWAGGER_ENABLED=true), debug off."""
    swagger_line, dashboard_line = banner_surface_lines(
        PORT, swagger_enabled=True, dev_admin_enabled=False
    )
    assert swagger_line == f"\n  Swagger:   http://localhost:{PORT}/swagger"
    assert dashboard_line == ""


def test_dev_admin_only() -> None:
    """Debug on but swagger explicitly disabled (TINA4_SWAGGER_ENABLED=false)."""
    swagger_line, dashboard_line = banner_surface_lines(
        PORT, swagger_enabled=False, dev_admin_enabled=True
    )
    assert swagger_line == ""
    assert dashboard_line == f"\n  Dashboard: http://localhost:{PORT}/__dev"


def test_both_on() -> None:
    """Ordinary dev: both surfaces live, both advertised."""
    swagger_line, dashboard_line = banner_surface_lines(
        PORT, swagger_enabled=True, dev_admin_enabled=True
    )
    assert swagger_line == f"\n  Swagger:   http://localhost:{PORT}/swagger"
    assert dashboard_line == f"\n  Dashboard: http://localhost:{PORT}/__dev"


def test_port_is_interpolated() -> None:
    """The printed link must carry the port the server actually bound."""
    swagger_line, dashboard_line = banner_surface_lines(
        9999, swagger_enabled=True, dev_admin_enabled=True
    )
    assert "9999" in swagger_line
    assert "9999" in dashboard_line
    assert str(PORT) not in swagger_line


def test_each_line_starts_on_its_own_row() -> None:
    """Both lines are interpolated into one banner string, so each owns its newline."""
    for line in banner_surface_lines(
        PORT, swagger_enabled=True, dev_admin_enabled=True
    ):
        assert line.startswith("\n")
        assert line.count("\n") == 1
