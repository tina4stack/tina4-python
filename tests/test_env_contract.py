"""The gate that keeps the test-service environment variables from drifting.

One test PostgreSQL once answered to thirteen different variable names and no
two frameworks read the same set, so exporting "the" variable turned some tests
on and left others silently skipped. tests/fixtures/test_env_contract.json is
now the single source of truth - identical bytes in all four frameworks - and
this module is Python's enforcement of it: every name this suite and the CI
workflows actually USE must be on that list, or the suite goes RED naming the
offender and the file it came from.

These tests read only real repository files. There are no doubles.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "test_env_contract.json"

# A name counts only where it is USED, never where it is merely discussed. A
# comment is documentation, not a read, so "the TINA4_TEST_* values" in prose
# must not be mistaken for a variable called TINA4_TEST_. A use site is one of:
#
#   ['"]           a quoted literal - os.environ.get("X"), getenv('X'),
#                  a name listed in an array, and shell `echo "X=value"`
#   process\.env\. Node's form. Python never emits it; the rule is kept
#                  identical in all four frameworks so the gate behaves the same
#   export\s+      a shell export ANYWHERE on the line, which is how
#                  tests/mqtt-infra.sh emits its coordinates:
#                      echo "export TINA4_TEST_MQTT_URL=..."
#                  Anchoring export to the line start instead would miss all
#                  five of those - a CI file that SETS a name no test READS is
#                  precisely the failure this gate exists to catch
#   ^\s*           a YAML env key or a bare shell assignment at line start
#
# The trailing + (never *) means a bare prefix with no attribute is not a name.
# That is also why the literals in this file are safe: "TINA4_TEST_" written
# alone is followed by a quote, so it never matches itself.
NAME_PATTERN = re.compile(
    r"""(?:['"]|process\.env\.|export\s+|^\s*)(TINA4_TEST_[A-Z0-9_]+)""",
    re.MULTILINE,
)

# Compiled bytecode is generated output, not source. A stale .pyc can still
# carry a name the .py no longer has, which would make this gate lie.
SKIPPED_DIRECTORY_NAMES = {"__pycache__"}


def load_contract():
    """The shared fixture. Never edited per-framework - all four carry it byte
    for byte, exactly like tests/fixtures/write_path_contract.json."""
    return json.loads(FIXTURE_PATH.read_text())


def canonical_names(contract):
    """Every name the contract permits.

    The grammar is TINA4_TEST_<SERVICE>_<ATTRIBUTE>, mirroring the runtime's own
    TINA4_<SUBSYSTEM>_<SERVICE>_<ATTRIBUTE>, plus the test-owned fixture names
    that carry no service grammar.
    """
    names = {
        f"TINA4_TEST_{service}_{attribute}"
        for service, attributes in contract["services"].items()
        for attribute in attributes
    }
    names.update(contract["fixtures"])
    return names


def scan_sources(contract):
    """(path_for_humans, text) for every file the Python gate covers.

    Workflows are scanned as well as tests, deliberately: a CI file that SETS a
    name no test READS is the exact failure that hid four Node tests and three
    PHP sites. The gate has to catch a rogue set, not just a rogue read.
    """
    sources = []
    for scan_path in contract["scan_paths"]["python"]:
        for path in sorted((REPO_ROOT / scan_path).rglob("*")):
            if not path.is_file():
                continue
            if SKIPPED_DIRECTORY_NAMES.intersection(path.parts):
                continue
            if path == FIXTURE_PATH:
                # The definition itself. Its "fixtures" and "dynamic_prefixes"
                # arrays are quoted literals and its prose names the retired
                # spellings on purpose, so it would only ever match itself.
                continue
            sources.append(
                (path.relative_to(REPO_ROOT).as_posix(), path.read_text(errors="ignore"))
            )
    return sources


def find_violations(sources, canonical, dynamic_prefixes):
    """Every used name that is neither canonical nor a declared dynamic prefix.

    Returns sorted (name, where) pairs so a failure names the variable AND the
    file, which is the whole point - "something is wrong somewhere" is what the
    old ad-hoc allow-lists gave us.
    """
    violations = set()
    for where, text in sources:
        for name in NAME_PATTERN.findall(text):
            if name in canonical or name in dynamic_prefixes:
                continue
            violations.add((name, where))
    return sorted(violations)


def test_every_test_environment_name_is_canonical():
    """No name outside tests/fixtures/test_env_contract.json may be used."""
    contract = load_contract()
    violations = find_violations(
        scan_sources(contract),
        canonical_names(contract),
        set(contract["dynamic_prefixes"]),
    )

    assert not violations, "\n".join(
        f"{name} is not on the canonical list ({where}). "
        "Add it to tests/fixtures/test_env_contract.json or use a canonical name."
        for name, where in violations
    )


def test_the_scan_actually_reads_the_suite():
    """Guard against a vacuous pass.

    A scanner whose glob is broken reads nothing, finds no violations, and goes
    green while enforcing exactly nothing. Prove it read real files, from BOTH
    scan roots, and saw names we know are there.
    """
    contract = load_contract()
    sources = scan_sources(contract)
    names_found = [name for _, text in sources for name in NAME_PATTERN.findall(text)]

    assert len(sources) >= 40, f"only {len(sources)} files scanned - the glob is broken"
    assert len(names_found) >= 40, (
        f"only {len(names_found)} names found across {len(sources)} files - "
        "the scan is not reading the suite"
    )

    scanned_roots = {where.split("/")[0] for where, _ in sources}
    assert "tests" in scanned_roots, "the tests directory was never scanned"
    assert ".github" in scanned_roots, "the workflows directory was never scanned"

    for expected in ("TINA4_TEST_PG_URL", "TINA4_TEST_PG_USERNAME"):
        assert expected in names_found, f"{expected} was not seen - the scan is not real"


def test_a_name_outside_the_contract_is_reported():
    """The negative case: the checker must actually catch an off-list name.

    The bogus name is concatenated at runtime so its literal never appears in
    this file - written out, the real scan above would find it here and fail.
    """
    contract = load_contract()
    canonical = canonical_names(contract)
    dynamic = set(contract["dynamic_prefixes"])

    bogus_name = "TINA4_TEST_" + "PG_FOO"
    source = (
        f'url = os.environ.get("{bogus_name}")\n'
        'user = os.environ.get("TINA4_TEST_PG_USERNAME")\n'
    )

    violations = find_violations([("tests/test_synthetic.py", source)], canonical, dynamic)

    assert violations == [(bogus_name, "tests/test_synthetic.py")], (
        f"expected {bogus_name} to be reported against its file, got {violations}"
    )
    # The canonical name sharing that source must NOT be reported: a checker
    # that flags everything is as useless as one that flags nothing.
    assert "TINA4_TEST_PG_USERNAME" not in [name for name, _ in violations]


def test_a_name_is_caught_in_every_form_it_can_be_used():
    """Teeth check, one case per use site the rule claims to cover.

    Each line below sets or reads the SAME off-list name a different way. If any
    form stops matching, the gate develops a blind spot in exactly the place the
    thirteen-spellings incident happened - a name that is set but never read.
    """
    contract = load_contract()
    canonical = canonical_names(contract)
    dynamic = set(contract["dynamic_prefixes"])
    bogus_name = "TINA4_TEST_" + "PG_FOO"

    forms = {
        "python read": f'os.environ.get("{bogus_name}")',
        "single quoted": f"os.getenv('{bogus_name}')",
        "node read": f"process.env.{bogus_name}",
        "yaml env key": f"      {bogus_name}: postgres://host/db",
        "shell export": f"export {bogus_name}=postgres://host/db",
        "echoed export": f'echo "export {bogus_name}=postgres://host/db"',
        "echoed assignment": f'echo "{bogus_name}=$RUNNER_TEMP/x" >> "$GITHUB_ENV"',
    }
    for label, source in forms.items():
        violations = find_violations([(label, source)], canonical, dynamic)
        assert violations == [(bogus_name, label)], f"{label!r} form was not caught"


def test_prose_about_the_variables_is_not_mistaken_for_a_name():
    """A comment is documentation, not a use.

    Without this the gate punishes anyone who writes a glob in a comment, which
    is pressure to weaken the gate rather than to fix a real drift.
    """
    contract = load_contract()
    canonical = canonical_names(contract)
    dynamic = set(contract["dynamic_prefixes"])

    prose = (
        "# ports mirror the local harness so the same TINA4_TEST_* values work\n"
        "    CI sets every TINA4_TEST_* URL, so these integration tests run.\n"
    )

    assert find_violations([("tests/test_prose.py", prose)], canonical, dynamic) == []


def test_the_match_rule_matches_the_one_the_contract_publishes():
    """Python's rule must be the rule all four frameworks implement.

    The fixture publishes the reference regex precisely because a gate that
    means something slightly different in each language is worse than no gate.
    If the shared contract's rule changes, this fails here rather than letting
    Python drift away from the other three in silence.
    """
    contract = load_contract()
    published = [
        line.strip()
        for line in contract["_match_rule_comment"]
        if line.strip().startswith("(?:")
    ]
    assert len(published) == 1, f"expected one reference regex, found {len(published)}"

    assert NAME_PATTERN.pattern.strip() == published[0], (
        "this module's match rule has drifted from the shared contract's:\n"
        f"  contract: {published[0]}\n"
        f"  here    : {NAME_PATTERN.pattern.strip()}"
    )


def test_a_declared_dynamic_prefix_is_allowed():
    """The one documented escape hatch still works.

    PHP appends uniqid() to a prefix to get a name guaranteed to be unset. No
    static scan can resolve that, so the contract declares the literal prefix.
    Python does not use it, but the checker is shared behaviour and the four
    frameworks must agree on it.
    """
    contract = load_contract()
    dynamic_prefixes = set(contract["dynamic_prefixes"])
    assert dynamic_prefixes, "the contract declares no dynamic prefixes to verify"

    source = "".join(f'getenv("{prefix}" . uniqid());\n' for prefix in dynamic_prefixes)
    violations = find_violations(
        [("tests/test_synthetic.php", source)], canonical_names(contract), dynamic_prefixes
    )

    assert violations == [], f"a declared dynamic prefix was rejected: {violations}"
