# Lock-in: the shipped tina4css assets must be fully compiled CSS.
#
# The March 2026 artifacts vendored into all four frameworks contained literal
# SCSS variables inside calc() -- `calc($grid-gutter / 2)` and
# `calc($border-radius-lg - 1px)`. A browser treats those as invalid and DROPS
# the whole declaration, so .container padding, .row negative margins,
# .row > * padding and the card first/last-child corner radii silently did not
# apply. 12 declarations shipped broken in every framework.
#
# These tests read the REAL shipped files off disk -- no mocks, no fixtures.
import re
from pathlib import Path

import pytest

CSS_DIR = Path(__file__).resolve().parent.parent / "tina4_python" / "public" / "css"
SHIPPED = ["tina4.css", "tina4.min.css"]

# A `$name` that is not the CSS `[attr$="x"]` suffix operator.
UNRESOLVED_VARIABLE = re.compile(r"\$(?!=)[A-Za-z_][A-Za-z0-9_-]*")
CALC_WITH_VARIABLE = re.compile(r"calc\([^()]*\$[^()]*\)")


def read(name: str) -> str:
    path = CSS_DIR / name
    assert path.is_file(), f"shipped asset missing: {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", SHIPPED)
def test_no_unresolved_scss_variable(name):
    """NEGATIVE: no SCSS variable may survive into the shipped CSS."""
    leaked = UNRESOLVED_VARIABLE.findall(read(name))
    assert leaked == [], f"{name} ships unresolved SCSS variables: {sorted(set(leaked))}"


@pytest.mark.parametrize("name", SHIPPED)
def test_no_calc_containing_a_variable(name):
    """NEGATIVE: calc() is the exact construct that leaked -- pin it explicitly."""
    leaked = CALC_WITH_VARIABLE.findall(read(name))
    assert leaked == [], f"{name} ships calc() with a variable: {sorted(set(leaked))}"


@pytest.mark.parametrize("name", SHIPPED)
def test_grid_gutter_is_resolved(name):
    """POSITIVE: an empty file would pass the negative tests, so assert the values."""
    css = read(name)
    # The minifier drops a leading zero (0.75rem -> .75rem); accept both.
    assert re.search(r"padding-right:\s*0?\.75rem", css), f"{name} lost the gutter padding"
    assert re.search(r"margin-right:\s*-0?\.75rem", css), f"{name} lost the row negative margin"


@pytest.mark.parametrize("name", SHIPPED)
def test_card_radius_is_resolved(name):
    """POSITIVE: mixed units (rem - px) cannot fold, so a real calc() is correct."""
    assert re.search(r"calc\(0?\.5rem - 1px\)", read(name)), f"{name} lost the card radius"

# test_shipped_css_matches_the_vendored_scss_source removed (3.13.99): commit
# 386cd6d "chore(scss): remove the bundled tina4css SCSS source from the
# framework" deliberately deleted tina4_python/scss/tina4css/*.scss (dead
# weight -- source-only, no compiler, never compiled or served at runtime, an
# exact duplicate of the canonical source now owned by the tina4-css repo and
# compiled by the Rust CLI). This test compared the shipped CSS against that
# now-removed vendored copy, so its premise no longer holds. The regression it
# guarded against (a leaked "$variable" or "calc($var)" reaching the shipped
# CSS, and the gutter/radius values silently going missing) is still fully
# covered by the four tests above, which read the REAL shipped artifact
# directly and would fail on an empty or reverted file just the same.
