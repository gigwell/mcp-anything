"""Tests for Type Registry."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch

from mcp_anything.analysis.type_registry import (
    TypeRegistry,
    TypeRegistryConfig,
)
from mcp_anything.models.analysis import ParameterSpec, Language
from mcp_anything.analysis.kotlin_parser import KotlinTypeInfo


class TestTypeRegistryConfig:
    """Test configuration."""
    
    def test_default_config(self):
        config = TypeRegistryConfig()
        assert config.max_depth == 5
        assert "**/*.kt" in config.include_patterns
    
    def test_custom_config(self):
        config = TypeRegistryConfig(
            max_depth=10,
            include_patterns=["**/*.kt"],
        )
        assert config.max_depth == 10


class TestTypeRegistry:
    """Test type registry functionality."""
    
    @pytest.fixture
    def registry(self):
        return TypeRegistry()
    
    @pytest.fixture
    def populated_registry(self, registry):
        """Registry with sample types."""
        # Manually add types
        registry._types["DateRangeFilter"] = KotlinTypeInfo(
            name="DateRangeFilter",
            kind="data_class",
            fields=[
                ParameterSpec(name="field", type="string", required=False),
                ParameterSpec(name="start", type="string", required=False),
                ParameterSpec(name="end", type="string", required=False),
            ]
        )
        registry._types["ExportAs"] = KotlinTypeInfo(
            name="ExportAs",
            kind="enum",
            enum_values=["STREAM_JSONL", "STREAM_CSV", "XLSX"]
        )
        registry._types["CustomFilterRequest"] = KotlinTypeInfo(
            name="CustomFilterRequest",
            kind="data_class",
            fields=[
                ParameterSpec(name="dateRange", type="object", required=False, original_type="DateRangeFilter"),
                ParameterSpec(name="exportAs", type="string", required=False, original_type="ExportAs"),
            ]
        )
        return registry
    
    def test_resolve_simple_type(self, registry):
        """Test that simple types pass through unchanged."""
        param = ParameterSpec(name="id", type="string", required=True)
        resolved = registry.resolve_parameter(param)
        assert resolved.name == "id"
        assert resolved.type == "string"
        assert resolved.properties is None
    
    def test_resolve_enum_type(self, populated_registry):
        """Test enum resolution."""
        param = ParameterSpec(
            name="exportAs",
            type="string",
            required=False,
            original_type="ExportAs"
        )
        resolved = populated_registry.resolve_parameter(param)
        
        assert resolved.enum_values == ["STREAM_JSONL", "STREAM_CSV", "XLSX"]
        assert resolved.type == "string"
    
    def test_resolve_nested_data_class(self, populated_registry):
        """Test nested type resolution."""
        param = ParameterSpec(
            name="filter",
            type="object",
            required=True,
            original_type="CustomFilterRequest"
        )
        resolved = populated_registry.resolve_parameter(param)
        
        assert resolved.type == "object"
        assert resolved.properties is not None
        assert len(resolved.properties) == 2
        
        # Check nested resolution
        date_range = resolved.properties[0]
        assert date_range.name == "dateRange"
        assert date_range.type == "object"
        assert date_range.properties is not None
        assert len(date_range.properties) == 3
    
    def test_resolve_missing_type(self, registry):
        """Test handling of missing types."""
        param = ParameterSpec(
            name="unknown",
            type="object",
            required=True,
            original_type="NonExistentType"
        )
        resolved = registry.resolve_parameter(param)
        
        # Should return unchanged
        assert resolved.original_type == "NonExistentType"
        assert resolved.properties is None
    
    def test_depth_limit(self):
        """Test depth limit enforcement."""
        config = TypeRegistryConfig(max_depth=2)
        registry = TypeRegistry(config)
        
        # Create circular reference
        registry._types["TypeA"] = KotlinTypeInfo(
            name="TypeA",
            kind="data_class",
            fields=[
                ParameterSpec(name="b", type="object", required=True, original_type="TypeB"),
            ]
        )
        registry._types["TypeB"] = KotlinTypeInfo(
            name="TypeB",
            kind="data_class",
            fields=[
                ParameterSpec(name="a", type="object", required=True, original_type="TypeA"),
            ]
        )
        
        param = ParameterSpec(name="test", type="object", required=True, original_type="TypeA")
        resolved = registry.resolve_parameter(param, depth=0)
        
        # Should not crash, should stop at depth limit
        assert resolved is not None
    
    def test_circular_reference_detection(self):
        """Test that circular references are detected."""
        config = TypeRegistryConfig(max_depth=10)
        registry = TypeRegistry(config)
        
        # Create circular reference
        registry._types["TypeA"] = KotlinTypeInfo(
            name="TypeA",
            kind="data_class",
            fields=[
                ParameterSpec(name="b", type="object", required=True, original_type="TypeB"),
            ]
        )
        registry._types["TypeB"] = KotlinTypeInfo(
            name="TypeB",
            kind="data_class",
            fields=[
                ParameterSpec(name="a", type="object", required=True, original_type="TypeA"),
            ]
        )
        
        param = ParameterSpec(name="test", type="object", required=True, original_type="TypeA")
        resolved = registry.resolve_parameter(param)
        
        # Should not crash, circular ref should be detected
        assert resolved is not None
    
    def test_resolve_all_parameters(self, populated_registry):
        """Test batch resolution."""
        params = [
            ParameterSpec(name="id", type="string", required=True),
            ParameterSpec(name="filter", type="object", required=False, original_type="CustomFilterRequest"),
            ParameterSpec(name="format", type="string", required=False, original_type="ExportAs"),
        ]
        
        resolved = populated_registry.resolve_all_parameters(params)
        
        assert len(resolved) == 3
        assert resolved[0].properties is None  # Simple type
        assert resolved[1].properties is not None  # Nested type
        assert resolved[2].enum_values is not None  # Enum type
    
    def test_get_type_count(self, populated_registry):
        """Test type count."""
        assert populated_registry.get_type_count() == 3
    
    def test_get_type_names(self, populated_registry):
        """Test type names list."""
        names = populated_registry.get_type_names()
        assert "CustomFilterRequest" in names
        assert "DateRangeFilter" in names
        assert "ExportAs" in names


class TestTypeRegistryScanning:
    """Test directory scanning."""
    
    def test_scan_kotlin_fixture(self):
        """Test scanning real Kotlin file."""
        registry = TypeRegistry()
        fixture_path = Path(__file__).parent / "fixtures"
        
        if (fixture_path / "kotlin_types.kt").exists():
            registry.scan_directory(fixture_path, Language.JAVA)
            
            assert registry.get_type_count() >= 5
            
            names = registry.get_type_names()
            assert "CustomFilterRequest" in names
            assert "ExportAs" in names
    
    def test_scan_resolves_nested_types(self):
        """Test that scanning enables nested type resolution."""
        registry = TypeRegistry()
        fixture_path = Path(__file__).parent / "fixtures"
        
        if (fixture_path / "kotlin_types.kt").exists():
            registry.scan_directory(fixture_path, Language.JAVA)
            
            # Resolve CustomFilterRequest with nested DateRangeFilter
            param = ParameterSpec(
                name="filter",
                type="object",
                required=True,
                original_type="CustomFilterRequest"
            )
            resolved = registry.resolve_parameter(param)
            
            # Should have nested properties
            assert resolved.properties is not None
            assert len(resolved.properties) == 7
            
            # DateRangeFilter should be resolved
            date_range = next(p for p in resolved.properties if p.name == "dateRange")
            assert date_range.type == "object"
            assert date_range.properties is not None
            assert len(date_range.properties) == 3
            
            # ExportAs should be resolved to enum
            export_as = next(p for p in resolved.properties if p.name == "exportAs")
            assert export_as.enum_values == ["STREAM_JSONL", "STREAM_CSV", "XLSX"]
    
    def test_exclude_patterns(self):
        """Test that exclude patterns work."""
        config = TypeRegistryConfig(
            exclude_patterns=["**/kotlin_types.kt"]
        )
        registry = TypeRegistry(config)
        fixture_path = Path(__file__).parent / "fixtures"
        
        if (fixture_path / "kotlin_types.kt").exists():
            registry.scan_directory(fixture_path, Language.JAVA)
            
            # Should not have scanned kotlin_types.kt
            assert registry.get_type_count() == 0


class TestTypeRegistryEdgeCases:
    """Test edge cases."""
    
    def test_unsupported_language(self):
        """Test that unsupported languages are handled."""
        registry = TypeRegistry()
        
        # Should not crash, should just warn
        registry.scan_directory(Path("/tmp"), Language.PYTHON)
        
        # No types should be found
        assert registry.get_type_count() == 0
    
    def test_resolve_parameter_without_original_type(self):
        """Test that params without original_type pass through."""
        registry = TypeRegistry()
        
        param = ParameterSpec(name="value", type="integer", required=True)
        resolved = registry.resolve_parameter(param)
        
        assert resolved.name == "value"
        assert resolved.type == "integer"
        assert resolved.properties is None
    
    def test_empty_registry(self):
        """Test operations on empty registry."""
        registry = TypeRegistry()
        
        assert registry.get_type_count() == 0
        assert registry.get_type_names() == []
        assert registry.resolve_type("NonExistent") is None
