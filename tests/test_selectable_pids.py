"""Lock-in tests for the port-reclaim PID safety rule.

`tina4 serve` reclaims a port from a stale dev server by reading `lsof -ti`
and signalling what it finds. Before 3.13.84 that output was never validated,
so a non-numeric field coerced to 0 -- and signalling PID 0 sends the signal
to EVERY process in the caller's own process group. In a container the server
IS PID 1, so it killed itself: the Node image logged "Killed existing process
on port 7148 (PID: 1 ...)" and exited 143.

These tests pin the rule that stops that. selectable_pids is pure, so this is
a real test over real inputs -- no double stands in for anything.
"""

from tina4_python.cli import selectable_pids


# ── negative cases: what must NEVER be signalled ──────────────────────────

def test_non_numeric_token_is_never_coerced_into_a_pid():
    # The original bug: this whole line used to become PID 0 or PID 1.
    assert selectable_pids("php", me=999) == []
    assert selectable_pids("1 /usr/local/bin/php -S 0.0.0.0:7145", me=999) == []


def test_pid_zero_is_never_signalled():
    # kill(0) signals the caller's entire process group -- suicide.
    assert selectable_pids("0", me=999) == []


def test_pid_one_is_never_signalled():
    # PID 1 is init; in a container that is the server itself.
    assert selectable_pids("1", me=999) == []


def test_own_pid_is_never_signalled():
    assert selectable_pids("4242", me=4242) == []


def test_own_process_group_is_never_signalled():
    assert selectable_pids("777", me=4242, my_group=777) == []


def test_empty_and_whitespace_output_yield_nothing():
    assert selectable_pids("", me=999) == []
    assert selectable_pids("   \n\t ", me=999) == []


# ── positive cases: a real stale sibling still gets reclaimed ─────────────

def test_a_real_foreign_pid_is_selected():
    assert selectable_pids("5150", me=4242) == [5150]


def test_multiple_pids_are_all_selected():
    assert selectable_pids("5150\n5151\n5152", me=4242) == [5150, 5151, 5152]


def test_unsafe_pids_are_dropped_while_safe_ones_survive():
    # Mixed real-world shape: junk + 0 + 1 + self + group + two real siblings.
    out = "php 0 1 4242 777 5150 5151"
    assert selectable_pids(out, me=4242, my_group=777) == [5150, 5151]


def test_duplicate_pids_are_reported_once():
    assert selectable_pids("5150 5150 5150", me=4242) == [5150]
