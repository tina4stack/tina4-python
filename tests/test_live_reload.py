# Tests for tina4_python.dev_reload (v3)
import pytest
import time
from pathlib import Path
from tina4_python.dev_reload import (
    _WATCH_EXTENSIONS,
    _IGNORE_DIRS,
    _should_ignore,
    _scan_mtime,
    get_last_mtime,
    get_last_change_file,
)


class TestWatchExtensions:

    def test_py_is_watched(self):
        assert ".py" in _WATCH_EXTENSIONS

    def test_twig_is_watched(self):
        assert ".twig" in _WATCH_EXTENSIONS

    def test_html_is_watched(self):
        assert ".html" in _WATCH_EXTENSIONS

    def test_css_is_watched(self):
        assert ".css" in _WATCH_EXTENSIONS

    def test_scss_is_watched(self):
        assert ".scss" in _WATCH_EXTENSIONS

    def test_js_is_watched(self):
        assert ".js" in _WATCH_EXTENSIONS

    def test_txt_not_watched(self):
        assert ".txt" not in _WATCH_EXTENSIONS

    def test_md_not_watched(self):
        assert ".md" not in _WATCH_EXTENSIONS

    def test_json_not_watched(self):
        assert ".json" not in _WATCH_EXTENSIONS


class TestIgnoreDirs:

    def test_venv_ignored(self):
        assert ".venv" in _IGNORE_DIRS

    def test_pycache_ignored(self):
        assert "__pycache__" in _IGNORE_DIRS

    def test_node_modules_ignored(self):
        assert "node_modules" in _IGNORE_DIRS

    def test_git_ignored(self):
        assert ".git" in _IGNORE_DIRS

    def test_vendor_ignored(self):
        assert "vendor" in _IGNORE_DIRS

    def test_data_ignored(self):
        assert "data" in _IGNORE_DIRS

    def test_mypy_cache_ignored(self):
        assert ".mypy_cache" in _IGNORE_DIRS

    def test_ruff_cache_ignored(self):
        assert ".ruff_cache" in _IGNORE_DIRS


class TestShouldIgnore:

    def test_ignore_venv_path(self):
        assert _should_ignore(Path("project/.venv/lib/site.py")) is True

    def test_ignore_pycache_path(self):
        assert _should_ignore(Path("src/__pycache__/module.cpython.pyc")) is True

    def test_ignore_node_modules(self):
        assert _should_ignore(Path("frontend/node_modules/pkg/index.js")) is True

    def test_ignore_git_dir(self):
        assert _should_ignore(Path(".git/objects/abc123")) is True

    def test_allow_normal_path(self):
        assert _should_ignore(Path("src/routes/users.py")) is False

    def test_allow_src_public(self):
        assert _should_ignore(Path("src/public/css/main.css")) is False


class TestScanMtime:

    def test_scan_empty_dir(self, tmp_path):
        mtime, file_path = _scan_mtime([str(tmp_path)])
        assert mtime == 0.0
        assert file_path == ""

    def test_scan_detects_py_file(self, tmp_path):
        py_file = tmp_path / "app.py"
        py_file.write_text("print('hello')")
        mtime, file_path = _scan_mtime([str(tmp_path)])
        assert mtime > 0
        assert file_path == str(py_file)

    def test_scan_ignores_txt_file(self, tmp_path):
        txt_file = tmp_path / "readme.txt"
        txt_file.write_text("readme")
        mtime, file_path = _scan_mtime([str(tmp_path)])
        assert mtime == 0.0
        assert file_path == ""

    def test_scan_detects_html_file(self, tmp_path):
        html_file = tmp_path / "index.html"
        html_file.write_text("<h1>hello</h1>")
        mtime, file_path = _scan_mtime([str(tmp_path)])
        assert mtime > 0
        assert file_path == str(html_file)

    def test_scan_detects_css_file(self, tmp_path):
        css_file = tmp_path / "style.css"
        css_file.write_text("body { color: red; }")
        mtime, file_path = _scan_mtime([str(tmp_path)])
        assert mtime > 0
        assert file_path == str(css_file)

    def test_scan_returns_latest_mtime(self, tmp_path):
        old = tmp_path / "old.py"
        old.write_text("# old")
        time.sleep(0.05)
        new = tmp_path / "new.py"
        new.write_text("# new")
        mtime, file_path = _scan_mtime([str(tmp_path)])
        assert file_path == str(new)

    def test_scan_ignores_pycache_subdir(self, tmp_path):
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "module.py").write_text("cached")
        mtime, file_path = _scan_mtime([str(tmp_path)])
        assert mtime == 0.0

    def test_scan_nonexistent_dir(self):
        mtime, file_path = _scan_mtime(["/nonexistent/dir/abc123"])
        assert mtime == 0.0
        assert file_path == ""

    def test_scan_multiple_directories(self, tmp_path):
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        (dir1 / "a.py").write_text("# a")
        time.sleep(0.05)
        (dir2 / "b.js").write_text("// b")
        mtime, file_path = _scan_mtime([str(dir1), str(dir2)])
        assert file_path == str(dir2 / "b.js")


class TestFileChangeDetection:

    def test_detect_modification(self, tmp_path):
        py_file = tmp_path / "app.py"
        py_file.write_text("v1")
        mtime1, _ = _scan_mtime([str(tmp_path)])

        time.sleep(0.05)
        py_file.write_text("v2")
        mtime2, _ = _scan_mtime([str(tmp_path)])

        assert mtime2 > mtime1

    def test_detect_new_file(self, tmp_path):
        mtime1, _ = _scan_mtime([str(tmp_path)])
        assert mtime1 == 0.0

        (tmp_path / "new.py").write_text("# new")
        mtime2, _ = _scan_mtime([str(tmp_path)])
        assert mtime2 > 0


class TestModuleState:

    def test_get_last_mtime_returns_float(self):
        result = get_last_mtime()
        assert isinstance(result, float)

    def test_get_last_change_file_returns_string(self):
        result = get_last_change_file()
        assert isinstance(result, str)
