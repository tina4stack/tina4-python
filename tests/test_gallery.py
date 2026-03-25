# Tests for tina4_python.gallery (v3)
import pytest
import json
from pathlib import Path


# Resolve the gallery directory relative to the framework package
_GALLERY_DIR = Path(__file__).resolve().parent.parent / "tina4_python" / "gallery"

# Expected gallery examples
_EXPECTED_EXAMPLES = ["auth", "database", "error-overlay", "orm", "queue", "rest-api", "templates"]


class TestGalleryDirectoryExists:

    def test_gallery_dir_exists(self):
        assert _GALLERY_DIR.is_dir(), f"Gallery directory not found at {_GALLERY_DIR}"

    def test_gallery_has_subdirectories(self):
        subdirs = [d.name for d in _GALLERY_DIR.iterdir() if d.is_dir()]
        assert len(subdirs) > 0

    def test_all_expected_examples_present(self):
        subdirs = [d.name for d in sorted(_GALLERY_DIR.iterdir()) if d.is_dir()]
        for name in _EXPECTED_EXAMPLES:
            assert name in subdirs, f"Missing gallery example: {name}"


class TestGalleryMetadata:

    def test_every_example_has_meta_json(self):
        for name in _EXPECTED_EXAMPLES:
            meta_file = _GALLERY_DIR / name / "meta.json"
            assert meta_file.is_file(), f"Missing meta.json in gallery/{name}"

    def test_meta_json_is_valid_json(self):
        for name in _EXPECTED_EXAMPLES:
            meta_file = _GALLERY_DIR / name / "meta.json"
            content = meta_file.read_text()
            parsed = json.loads(content)
            assert isinstance(parsed, dict)

    def test_meta_json_has_name_field(self):
        for name in _EXPECTED_EXAMPLES:
            meta_file = _GALLERY_DIR / name / "meta.json"
            parsed = json.loads(meta_file.read_text())
            assert "name" in parsed, f"meta.json in {name} missing 'name' field"

    def test_meta_json_has_description_field(self):
        for name in _EXPECTED_EXAMPLES:
            meta_file = _GALLERY_DIR / name / "meta.json"
            parsed = json.loads(meta_file.read_text())
            assert "description" in parsed, f"meta.json in {name} missing 'description' field"

    def test_meta_json_name_is_string(self):
        for name in _EXPECTED_EXAMPLES:
            meta_file = _GALLERY_DIR / name / "meta.json"
            parsed = json.loads(meta_file.read_text())
            assert isinstance(parsed["name"], str)
            assert len(parsed["name"]) > 0

    def test_meta_json_description_is_string(self):
        for name in _EXPECTED_EXAMPLES:
            meta_file = _GALLERY_DIR / name / "meta.json"
            parsed = json.loads(meta_file.read_text())
            assert isinstance(parsed["description"], str)
            assert len(parsed["description"]) > 0


class TestGalleryExampleStructure:

    def test_each_example_has_src_directory(self):
        for name in _EXPECTED_EXAMPLES:
            src_dir = _GALLERY_DIR / name / "src"
            assert src_dir.is_dir(), f"Missing src/ in gallery/{name}"

    def test_each_example_has_python_files(self):
        for name in _EXPECTED_EXAMPLES:
            src_dir = _GALLERY_DIR / name / "src"
            py_files = list(src_dir.rglob("*.py"))
            assert len(py_files) > 0, f"No .py files in gallery/{name}/src"

    def test_rest_api_has_route_file(self):
        routes_dir = _GALLERY_DIR / "rest-api" / "src" / "routes"
        assert routes_dir.is_dir()
        py_files = list(routes_dir.rglob("*.py"))
        assert len(py_files) > 0

    def test_templates_has_twig_file(self):
        tpl_dir = _GALLERY_DIR / "templates" / "src" / "templates"
        assert tpl_dir.is_dir()
        twig_files = list(tpl_dir.rglob("*.twig"))
        assert len(twig_files) > 0


class TestGalleryRouteHandler:

    def test_gallery_list_handler_exists(self):
        from tina4_python.dev_admin import _api_gallery_list
        assert callable(_api_gallery_list)

    def test_gallery_deploy_handler_exists(self):
        from tina4_python.dev_admin import _api_gallery_deploy
        assert callable(_api_gallery_deploy)

    def test_dev_routes_include_gallery(self):
        from tina4_python.dev_admin import get_api_handlers
        routes = get_api_handlers()
        assert "/__dev/api/gallery" in routes
        assert "/__dev/api/gallery/deploy" in routes
