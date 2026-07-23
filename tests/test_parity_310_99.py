# Tests for features added/changed in 3.10.99
import pytest
from tina4_python.database import Database
from tina4_python.orm import ORM, bind_database, Field
from tina4_python.frond import Frond


# ── Test Models ─────────────────────────────────────────────────


class Article(ORM):
    table_name = "articles"
    id = Field(int, primary_key=True, auto_increment=True)
    image_url = Field(str)
    created_at = Field(str)
    title = Field(str)


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """Fresh database with test tables."""
    db_path = tmp_path / "parity_test.db"
    d = Database(f"sqlite:///{db_path}")
    d.execute(
        "CREATE TABLE articles ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "image_url TEXT, "
        "created_at TEXT, "
        "title TEXT)"
    )
    d.commit()
    bind_database(d)
    yield d
    d.close()


@pytest.fixture
def engine(tmp_path):
    """Frond engine with temp template dir."""
    Frond.clear_registry()
    return Frond(template_dir=str(tmp_path))


# ── to_dict case Tests ──────────────────────────────────────────


class TestToDictCase:
    """Tests for to_dict case parameter (snake / camel)."""

    def test_to_dict_case_snake(self, db):
        """Default case='snake' returns snake_case keys."""
        article = Article({"image_url": "https://img.test/photo.jpg", "created_at": "2024-01-15", "title": "Hello"})
        article.save()

        found = Article.find_by_id(article.id)
        d = found.to_dict()

        assert "image_url" in d
        assert "created_at" in d
        assert "title" in d
        assert d["image_url"] == "https://img.test/photo.jpg"
        assert d["created_at"] == "2024-01-15"

    def test_to_dict_case_camel(self, db):
        """case='camel' returns camelCase keys."""
        article = Article({"image_url": "https://img.test/photo.jpg", "created_at": "2024-01-15", "title": "Hello"})
        article.save()

        found = Article.find_by_id(article.id)
        d = found.to_dict(case="camel")

        assert "imageUrl" in d
        assert "createdAt" in d
        assert "title" in d
        assert d["imageUrl"] == "https://img.test/photo.jpg"
        assert d["createdAt"] == "2024-01-15"
        # snake_case keys must NOT appear
        assert "image_url" not in d
        assert "created_at" not in d


# ── auto_map Default Tests ──────────────────────────────────────


class TestAutoMapDefault:
    """Tests for ORM auto_map class attribute."""

    def test_automap_default_true(self):
        """auto_map defaults to True for cross-language parity."""

        class Widget(ORM):
            table_name = "widgets"
            id = Field(int, primary_key=True)
            name = Field(str)

        assert Widget.auto_map is True


# ── Frond replace Filter Tests ──────────────────────────────────


class TestReplaceFilter:
    """Tests for Frond replace filter (dict and positional forms)."""

    def test_replace_filter_dict(self, engine):
        """replace({...}) applies all substitutions from a dict."""
        result = engine.render_string(
            '{{ val|replace({"T": " ", "-": "/"}) }}',
            {"val": "2024-01-15T10:30:00"},
        )
        assert result == "2024/01/15 10:30:00"

    def test_replace_filter_positional(self, engine):
        """replace("old", "new") applies a single substitution."""
        result = engine.render_string(
            '{{ val|replace("hello", "world") }}',
            {"val": "say hello"},
        )
        assert result == "say world"


# ── Background Task Registration Tests ──────────────────────────


class TestBackgroundRegistration:
    """Tests for background() task registration mechanism."""

    def test_background_registration(self):
        """background() is callable and appends to the task registry.

        The registry holds BackgroundTask handles rather than plain dicts since
        per-task stop() landed, so this reads the entry's attributes and cleans
        up through the handle's own stop() instead of popping the private list.
        """
        from tina4_python.core.server import (
            background,
            background_task_count,
            _background_tasks,
        )

        initial_count = background_task_count()

        def my_task():
            pass

        task = background(my_task, interval=5.0)

        assert background_task_count() == initial_count + 1
        entry = _background_tasks[-1]
        assert entry is task
        assert entry.callback is my_task
        assert entry.interval == 5.0

        # Clean up — stop() both ends the task and deregisters it.
        assert task.stop() is True
        assert background_task_count() == initial_count
