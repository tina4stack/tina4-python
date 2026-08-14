# Lock-in tests for 3.13.100's Frond cache bounds (ADR-0004).
#
# Before this fix, Python was the outlier: PHP/Ruby/Node already capped their
# TEMPLATE caches at TEMPLATE_CACHE_MAX (256), but Python's `_compiled`,
# `_compiled_strings` and `_compiled_fn` were plain unbounded dicts. And in
# ALL FOUR frameworks the `{% cache %}` fragment store (`_fragment_cache`) was
# both unbounded AND never swept a TTL-expired entry: a key that expired and
# was never read again sat in memory for the life of the worker. This file
# also locks in `_filter_chain_cache`, a per-expression memo that turned out
# to still be a plain unbounded instance dict despite being the direct
# Python counterpart of Ruby's `@filter_chain_cache` / Node's
# `filterChainCache` (both capped) -- the four already-`@lru_cache`d module
# functions (`_split_dotted`, `_has_low_precedence_op`, `_expr_descriptor`,
# `_split_on_pipe`) are pure functions and don't cover it, since it's an
# INSTANCE dict on a bound method.
#
# Reproduced for real below: real renders through the real engine, real
# template files on disk, and the real instance caches read directly. No
# mocks: nothing here stands in for the engine, the clock, or the filesystem.
import time

import pytest

from tina4_python.frond import Frond
from tina4_python.frond.engine import TEMPLATE_CACHE_MAX, MEMO_CACHE_MAX


@pytest.fixture
def engine(tmp_path):
    Frond.clear_registry()
    return Frond(template_dir=str(tmp_path))


@pytest.fixture
def tpl_dir(tmp_path):
    return tmp_path


class TestCacheCapConstants:
    def test_template_cache_max_is_a_positive_cap(self):
        assert TEMPLATE_CACHE_MAX > 0

    def test_memo_cache_max_is_a_positive_cap_not_smaller_than_template_cap(self):
        assert MEMO_CACHE_MAX > 0
        assert MEMO_CACHE_MAX >= TEMPLATE_CACHE_MAX


class TestTemplateCacheBound:
    """`_compiled` / `_compiled_strings` / `_compiled_fn` were unbounded."""

    def test_compiled_strings_and_compiled_fn_do_not_grow_without_limit(self, engine):
        distinct = TEMPLATE_CACHE_MAX * 2 + 13

        for index in range(distinct):
            rendered = engine.render_string(f"t{index}={{{{ n + {index} }}}}", {"n": 10})
            assert rendered == f"t{index}={10 + index}"

        strings_size = len(engine._compiled_strings)
        assert strings_size <= TEMPLATE_CACHE_MAX, (
            f"_compiled_strings grew to {strings_size} entries for {distinct} distinct "
            f"sources; cap is {TEMPLATE_CACHE_MAX}"
        )

        fn_size = len(engine._compiled_fn)
        assert fn_size <= TEMPLATE_CACHE_MAX, (
            f"_compiled_fn grew to {fn_size} entries for {distinct} distinct sources; "
            f"cap is {TEMPLATE_CACHE_MAX}"
        )

    def test_evicted_string_template_recompiles_and_stays_correct(self, engine):
        first_source = "first={{ n + 1 }}"
        assert engine.render_string(first_source, {"n": 10}) == "first=11"

        for index in range(TEMPLATE_CACHE_MAX * 2):
            engine.render_string(f"filler{index}={{{{ n }}}}", {"n": index})

        import hashlib
        first_key = hashlib.md5(first_source.encode()).hexdigest()
        assert first_key not in engine._compiled_strings, "the first entry should have been evicted"

        # Re-tokenizes from cold, still byte-correct, still tracks the data.
        assert engine.render_string(first_source, {"n": 10}) == "first=11"
        assert engine.render_string(first_source, {"n": 100}) == "first=101"

    def test_file_template_cache_is_bounded(self, engine, tpl_dir):
        distinct = TEMPLATE_CACHE_MAX + 41

        for index in range(distinct):
            (tpl_dir / f"tpl{index}.twig").write_text(f"T{index}={{{{ n + {index} }}}}", encoding="utf-8")

        for index in range(distinct):
            assert engine.render(f"tpl{index}.twig", {"n": 5}) == f"T{index}={5 + index}"

        compiled_size = len(engine._compiled)
        assert compiled_size <= TEMPLATE_CACHE_MAX, (
            f"_compiled grew to {compiled_size} entries for {distinct} distinct templates; "
            f"cap is {TEMPLATE_CACHE_MAX}"
        )

        # Every template still renders correctly after the sweep, including
        # the earliest ones, which were evicted and must re-read from disk.
        for index in range(distinct):
            assert engine.render(f"tpl{index}.twig", {"n": 7}) == f"T{index}={7 + index}"

    def test_cache_below_the_cap_is_not_evicted(self, engine):
        below_cap = TEMPLATE_CACHE_MAX - 1
        for index in range(below_cap):
            engine.render_string(f"u{index}={{{{ n }}}}", {"n": index})

        assert len(engine._compiled_strings) == below_cap

    def test_clear_cache_still_empties_every_template_cache(self, engine, tpl_dir):
        (tpl_dir / "page.twig").write_text("page={{ n }}", encoding="utf-8")
        assert engine.render("page.twig", {"n": 3}) == "page=3"
        assert engine.render_string("str={{ n }}", {"n": 4}) == "str=4"

        assert engine._compiled
        assert engine._compiled_strings
        assert engine._compiled_fn

        engine.clear_cache()

        assert engine._compiled == {}
        assert engine._compiled_strings == {}
        assert engine._compiled_fn == {}

        # Still renders correctly from cold after a clear.
        assert engine.render("page.twig", {"n": 3}) == "page=3"
        assert engine.render_string("str={{ n }}", {"n": 4}) == "str=4"

    def test_inheritance_survives_an_eviction_storm(self, engine, tpl_dir):
        (tpl_dir / "base.twig").write_text(
            "BASE[{% block body %}dflt{% endblock %}]", encoding="utf-8"
        )
        (tpl_dir / "child.twig").write_text(
            '{% extends "base.twig" %}{% block body %}{{ n * 2 }}{% endblock %}', encoding="utf-8"
        )

        assert engine.render("child.twig", {"n": 4}) == "BASE[8]"

        for index in range(TEMPLATE_CACHE_MAX * 2):
            engine.render_string(f"storm{index}={{{{ n }}}}", {"n": index})

        assert engine.render("child.twig", {"n": 4}) == "BASE[8]"
        assert engine.render("child.twig", {"n": 10}) == "BASE[20]"


class TestFilterChainCacheBound:
    """`_filter_chain_cache` was a plain unbounded instance dict."""

    def test_does_not_grow_without_limit_for_distinct_filter_expressions(self, engine):
        distinct = MEMO_CACHE_MAX * 2 + 17

        for index in range(distinct):
            result = engine.render_string(f"{{{{ n | default({index}) }}}}", {})
            assert result == str(index)

        size = len(engine._filter_chain_cache)
        assert size <= MEMO_CACHE_MAX, (
            f"_filter_chain_cache grew to {size} entries for {distinct} distinct "
            f"expressions; cap is {MEMO_CACHE_MAX}"
        )

    def test_evicts_nothing_while_under_the_cap(self, engine):
        below_cap = MEMO_CACHE_MAX - 1
        for index in range(below_cap):
            engine.render_string(f"{{{{ n | default({index}) }}}}", {})

        assert len(engine._filter_chain_cache) == below_cap

    def test_clear_cache_empties_it(self, engine):
        engine.render_string("{{ n | default(1) }}", {})
        assert engine._filter_chain_cache

        engine.clear_cache()
        assert engine._filter_chain_cache == {}
        assert engine.render_string("{{ n | default(1) }}", {}) == "1"


class TestFragmentCacheBoundAndSweep:
    """`_fragment_cache` was unbounded AND a TTL-expired entry was never swept."""

    def test_does_not_grow_without_limit_for_many_distinct_cache_keys(self, engine):
        distinct = TEMPLATE_CACHE_MAX * 2 + 13

        for index in range(distinct):
            result = engine.render_string(
                f'{{% cache "frag{index}" 300 %}}{{{{ n }}}}{{% endcache %}}', {"n": index}
            )
            assert result == str(index)

        size = len(engine._fragment_cache)
        assert size <= TEMPLATE_CACHE_MAX, (
            f"_fragment_cache grew to {size} entries for {distinct} distinct keys; "
            f"cap is {TEMPLATE_CACHE_MAX}"
        )

    def test_evicts_nothing_while_under_the_cap(self, engine):
        below_cap = TEMPLATE_CACHE_MAX - 1
        for index in range(below_cap):
            engine.render_string(
                f'{{% cache "under{index}" 300 %}}{{{{ n }}}}{{% endcache %}}', {"n": index}
            )

        assert len(engine._fragment_cache) == below_cap

    def test_recomputes_a_fragment_evicted_by_the_size_cap_and_stays_correct(self, engine):
        first = engine.render_string('{% cache "first_evictable" 300 %}{{ n }}{% endcache %}', {"n": "one"})
        assert first == "one"

        for index in range(TEMPLATE_CACHE_MAX * 2):
            engine.render_string(
                f'{{% cache "filler{index}" 300 %}}{{{{ n }}}}{{% endcache %}}', {"n": index}
            )

        assert "first_evictable" not in engine._fragment_cache, (
            "the first fragment should have been evicted by the size cap"
        )

        # Recomputes from cold with fresh data -- never reads stale content.
        recomputed = engine.render_string('{% cache "first_evictable" 300 %}{{ n }}{% endcache %}', {"n": "two"})
        assert recomputed == "two"

    def test_sweeps_a_ttl_expired_fragment_instead_of_leaving_it_stale_forever(self, engine):
        short_lived = engine.render_string('{% cache "short_lived" 1 %}{{ n }}{% endcache %}', {"n": "first"})
        assert short_lived == "first"
        engine.render_string('{% cache "control" 300 %}{{ n }}{% endcache %}', {"n": "control"})

        time.sleep(1.1)

        # Touch a DIFFERENT cache key -- proving the sweep runs as a side
        # effect of any fragment-cache render, not only on a re-read of the
        # SAME key (which the old code already handled by silent overwrite).
        engine.render_string('{% cache "trigger" 300 %}{{ n }}{% endcache %}', {"n": "trigger"})

        assert "short_lived" not in engine._fragment_cache, (
            "the expired entry should have been swept, not merely left stale"
        )
        assert "control" in engine._fragment_cache, "a still-live entry must not be swept early"

        # A fresh render recomputes rather than ever reading stale content.
        refreshed = engine.render_string('{% cache "short_lived" 1 %}{{ n }}{% endcache %}', {"n": "second"})
        assert refreshed == "second"
