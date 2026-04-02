"""Tests for Kotlin JAX-RS/Jersey support — scanner, detector, analyzer, capabilities."""

import pytest

from mcp_anything.analysis.detectors.jaxrs_detector import JaxRSDetector
from mcp_anything.analysis.java_analyzer import (
    analyze_java_file,
    java_results_to_capabilities,
)
from mcp_anything.analysis.scanner import classify_language, scan_codebase
from mcp_anything.models.analysis import FileInfo, IPCType, Language
from pathlib import Path


class TestKotlinScanner:
    def test_kt_classified_as_kotlin(self, tmp_path):
        f = tmp_path / "Foo.kt"
        f.write_text("class Foo")
        assert classify_language(f) == Language.KOTLIN

    def test_kts_classified_as_kotlin(self, tmp_path):
        f = tmp_path / "build.kts"
        f.write_text("plugins { kotlin(\"jvm\") }")
        assert classify_language(f) == Language.KOTLIN

    def test_kotlin_files_scanned(self, fake_kotlin_jaxrs_app):
        files = scan_codebase(fake_kotlin_jaxrs_app)
        kotlin_files = [f for f in files if f.language == Language.KOTLIN]
        assert len(kotlin_files) >= 1
        assert any("ItemResource.kt" in f.path for f in kotlin_files)


class TestKotlinDetector:
    def test_detects_jaxrs_in_kotlin(self, fake_kotlin_jaxrs_app):
        files = scan_codebase(fake_kotlin_jaxrs_app)
        detector = JaxRSDetector()
        mechanisms = detector.detect(fake_kotlin_jaxrs_app, files)

        assert len(mechanisms) == 1
        mech = mechanisms[0]
        assert mech.ipc_type == IPCType.PROTOCOL
        assert mech.confidence >= 0.85
        assert mech.details["protocol"] == "http"

    def test_framework_is_jaxrs(self, fake_kotlin_jaxrs_app):
        files = scan_codebase(fake_kotlin_jaxrs_app)
        detector = JaxRSDetector()
        mechanisms = detector.detect(fake_kotlin_jaxrs_app, files)
        assert mechanisms[0].details["framework"] == "jaxrs"


class TestKotlinAnalyzer:
    def _get_fi(self) -> FileInfo:
        return FileInfo(
            path="src/main/kotlin/com/example/api/ItemResource.kt",
            language=Language.KOTLIN,
            size_bytes=500,
            line_count=40,
        )

    def test_finds_endpoints(self, fake_kotlin_jaxrs_app):
        result = analyze_java_file(fake_kotlin_jaxrs_app, self._get_fi())

        assert result is not None
        assert len(result.endpoints) >= 5
        assert "ItemResource" in result.controllers

    def test_extracts_http_methods(self, fake_kotlin_jaxrs_app):
        result = analyze_java_file(fake_kotlin_jaxrs_app, self._get_fi())

        methods = {ep.http_method for ep in result.endpoints}
        assert "GET" in methods
        assert "POST" in methods
        assert "PUT" in methods
        assert "DELETE" in methods

    def test_extracts_paths(self, fake_kotlin_jaxrs_app):
        result = analyze_java_file(fake_kotlin_jaxrs_app, self._get_fi())

        paths = {ep.path for ep in result.endpoints}
        assert "/api/items" in paths
        assert "/api/items/{id}" in paths

    def test_extracts_path_params(self, fake_kotlin_jaxrs_app):
        result = analyze_java_file(fake_kotlin_jaxrs_app, self._get_fi())

        get_by_id = next(ep for ep in result.endpoints if ep.method_name == "getItem")
        assert len(get_by_id.parameters) == 1
        assert get_by_id.parameters[0].name == "id"
        assert get_by_id.parameters[0].required is True

    def test_extracts_query_params(self, fake_kotlin_jaxrs_app):
        result = analyze_java_file(fake_kotlin_jaxrs_app, self._get_fi())

        list_items = next(ep for ep in result.endpoints if ep.method_name == "listItems")
        assert len(list_items.parameters) == 1
        assert list_items.parameters[0].name == "category"
        assert list_items.parameters[0].required is False

    def test_nullable_params_are_not_required(self, fake_kotlin_jaxrs_app):
        result = analyze_java_file(fake_kotlin_jaxrs_app, self._get_fi())

        list_items = next(ep for ep in result.endpoints if ep.method_name == "listItems")
        # category is String? (nullable) → should not be required
        assert list_items.parameters[0].required is False


class TestKotlinSpring:
    def _get_fi(self) -> FileInfo:
        return FileInfo(
            path="src/main/kotlin/com/example/api/UserController.kt",
            language=Language.KOTLIN,
            size_bytes=600,
            line_count=30,
        )

    def test_finds_endpoints(self, fake_kotlin_spring_app):
        result = analyze_java_file(fake_kotlin_spring_app, self._get_fi())
        assert result is not None
        assert len(result.endpoints) >= 5
        assert "UserController" in result.controllers

    def test_extracts_http_methods(self, fake_kotlin_spring_app):
        result = analyze_java_file(fake_kotlin_spring_app, self._get_fi())
        methods = {ep.http_method for ep in result.endpoints}
        assert "GET" in methods
        assert "POST" in methods
        assert "PUT" in methods
        assert "DELETE" in methods

    def test_extracts_paths(self, fake_kotlin_spring_app):
        result = analyze_java_file(fake_kotlin_spring_app, self._get_fi())
        paths = {ep.path for ep in result.endpoints}
        assert "/api/users" in paths
        assert "/api/users/{id}" in paths

    def test_extracts_path_variable(self, fake_kotlin_spring_app):
        result = analyze_java_file(fake_kotlin_spring_app, self._get_fi())
        get_user = next(ep for ep in result.endpoints if ep.method_name == "getUser")
        assert len(get_user.parameters) == 1
        assert get_user.parameters[0].name == "id"
        assert get_user.parameters[0].required is True

    def test_extracts_request_param(self, fake_kotlin_spring_app):
        result = analyze_java_file(fake_kotlin_spring_app, self._get_fi())
        list_users = next(ep for ep in result.endpoints if ep.method_name == "listUsers")
        assert len(list_users.parameters) == 1
        assert list_users.parameters[0].name == "role"
        assert list_users.parameters[0].required is False

    def test_extracts_request_body(self, fake_kotlin_spring_app):
        result = analyze_java_file(fake_kotlin_spring_app, self._get_fi())
        create_user = next(ep for ep in result.endpoints if ep.method_name == "createUser")
        assert len(create_user.parameters) == 1
        assert create_user.parameters[0].name == "body"
        assert create_user.parameters[0].type == "object"
        assert create_user.parameters[0].required is True

    def test_detector_scans_kotlin_spring(self, fake_kotlin_spring_app):
        from mcp_anything.analysis.detectors.spring_detector import SpringDetector
        from mcp_anything.analysis.scanner import scan_codebase
        files = scan_codebase(fake_kotlin_spring_app)
        detector = SpringDetector()
        mechanisms = detector.detect(fake_kotlin_spring_app, files)
        assert len(mechanisms) == 1


class TestKotlinCapabilities:
    def test_endpoints_become_capabilities(self, fake_kotlin_jaxrs_app):
        fi = FileInfo(
            path="src/main/kotlin/com/example/api/ItemResource.kt",
            language=Language.KOTLIN,
            size_bytes=500,
            line_count=40,
        )
        result = analyze_java_file(fake_kotlin_jaxrs_app, fi)
        caps = java_results_to_capabilities({fi.path: result})

        assert len(caps) >= 5
        cap_names = [c.name for c in caps]
        assert any("get" in n and "items" in n for n in cap_names)
        assert any("post" in n and "items" in n for n in cap_names)
        assert any("delete" in n and "items" in n for n in cap_names)

    def test_capabilities_have_correct_ipc_type(self, fake_kotlin_jaxrs_app):
        fi = FileInfo(
            path="src/main/kotlin/com/example/api/ItemResource.kt",
            language=Language.KOTLIN,
            size_bytes=500,
            line_count=40,
        )
        result = analyze_java_file(fake_kotlin_jaxrs_app, fi)
        caps = java_results_to_capabilities({fi.path: result})

        for cap in caps:
            assert cap.ipc_type == IPCType.PROTOCOL
            assert cap.category == "api"


class TestKotlinJaxRSEdgeCases:
    """Test edge cases in Kotlin JAX-RS parsing: trailing comments, single-line annotations."""

    def _get_fi(self) -> FileInfo:
        return FileInfo(
            path="src/main/kotlin/com/example/api/ItemResource.kt",
            language=Language.KOTLIN,
            size_bytes=800,
            line_count=60,
        )

    def test_trailing_comment_on_annotation(self, fake_kotlin_jaxrs_app):
        """@GET with trailing comment on annotation line should still be detected."""
        result = analyze_java_file(fake_kotlin_jaxrs_app, self._get_fi())
        # Should find method 'getStatus' even with // comment
        method_names = {ep.method_name for ep in result.endpoints}
        assert "getStatus" in method_names, f"getStatus not found in {method_names}"

    def test_naked_get_uses_class_path(self, fake_kotlin_jaxrs_app):
        """Method without @Path should use class-level @Path."""
        result = analyze_java_file(fake_kotlin_jaxrs_app, self._get_fi())
        # getStatus has no @Path, should use class path /api/items
        status_ep = next((ep for ep in result.endpoints if ep.method_name == "getStatus"), None)
        assert status_ep is not None, "getStatus endpoint not found"
        assert status_ep.path == "/api/items", f"Expected /api/items, got {status_ep.path}"

    def test_multiple_annotations_on_one_line(self, fake_kotlin_jaxrs_app):
        """Single-line annotation pattern should parse correctly."""
        result = analyze_java_file(fake_kotlin_jaxrs_app, self._get_fi())
        health_ep = next((ep for ep in result.endpoints if ep.method_name == "getHealth"), None)
        assert health_ep is not None, "getHealth endpoint not found"
        assert "/health" in health_ep.path, f"Expected /health in path, got {health_ep.path}"

    def test_list_items_uses_class_path(self, fake_kotlin_jaxrs_app):
        """Existing test: listItems has no @Path, uses class path."""
        result = analyze_java_file(fake_kotlin_jaxrs_app, self._get_fi())
        list_ep = next((ep for ep in result.endpoints if ep.method_name == "listItems"), None)
        assert list_ep is not None
        assert list_ep.path == "/api/items"

    def test_all_endpoints_found(self, fake_kotlin_jaxrs_app):
        """All 7 endpoints should be detected."""
        result = analyze_java_file(fake_kotlin_jaxrs_app, self._get_fi())
        expected = {"listItems", "getItem", "createItem", "updateItem", "deleteItem", "getStatus", "getHealth"}
        found = {ep.method_name for ep in result.endpoints}
        assert found == expected, f"Expected {expected}, got {found}"
