"""Tests for Kotlin parser."""

import pytest
from pathlib import Path

from mcp_anything.analysis.kotlin_parser import (
    parse_kotlin_data_class,
    parse_kotlin_enum,
    parse_kotlin_source,
    parse_kotlin_file,
    map_kotlin_type,
    KotlinTypeInfo,
)


class TestMapKotlinType:
    """Test Kotlin type mapping."""
    
    def test_simple_types(self):
        assert map_kotlin_type("String") == ("string", None)
        assert map_kotlin_type("Int") == ("integer", None)
        assert map_kotlin_type("Boolean") == ("boolean", None)
        assert map_kotlin_type("Double") == ("float", None)
    
    def test_nullable_types(self):
        assert map_kotlin_type("String?") == ("string", None)
        assert map_kotlin_type("Int?") == ("integer", None)
    
    def test_list_types(self):
        mcp_type, orig = map_kotlin_type("List<String>")
        assert mcp_type == "array"
    
    def test_complex_types(self):
        mcp_type, orig = map_kotlin_type("DateRangeFilter")
        assert mcp_type == "object"
        assert orig == "DateRangeFilter"
    
    def test_generic_complex_types(self):
        mcp_type, orig = map_kotlin_type("List<DateRangeFilter>")
        assert mcp_type == "array"


class TestParseKotlinDataClass:
    """Test data class parsing."""
    
    def test_simple_data_class(self):
        source = """
        data class Person(val name: String, val age: Int)
        """
        results = parse_kotlin_data_class(source)
        assert len(results) == 1
        
        info = results[0]
        assert info.name == "Person"
        assert info.kind == "data_class"
        assert len(info.fields) == 2
        assert info.fields[0].name == "name"
        assert info.fields[0].type == "string"
        assert info.fields[1].name == "age"
        assert info.fields[1].type == "integer"
    
    def test_nullable_fields(self):
        source = """
        data class Filter(
            var name: String? = null,
            var count: Int? = null
        )
        """
        results = parse_kotlin_data_class(source)
        assert len(results) == 1
        
        info = results[0]
        assert info.fields[0].required == False
        assert info.fields[1].required == False
    
    def test_nested_types(self):
        source = """
        data class CustomFilterRequest(
            var dateRange: DateRangeFilter? = null,
            var statuses: List<String>? = null
        )
        """
        results = parse_kotlin_data_class(source)
        assert len(results) == 1
        
        info = results[0]
        assert info.fields[0].name == "dateRange"
        assert info.fields[0].type == "object"
        assert info.fields[0].original_type == "DateRangeFilter"
        
        assert info.fields[1].name == "statuses"
        assert info.fields[1].type == "array"
    
    def test_specific_class_lookup(self):
        source = """
        data class Target(val x: Int)
        data class Other(val y: String)
        """
        results = parse_kotlin_data_class(source, class_name="Target")
        assert len(results) == 1
        assert results[0].name == "Target"
    
    def test_multiline_data_class(self):
        source = """
        data class MultiLine(
            val first: String,
            val second: Int,
            val third: Boolean
        )
        """
        results = parse_kotlin_data_class(source)
        assert len(results) == 1
        assert len(results[0].fields) == 3


class TestParseKotlinEnum:
    """Test enum parsing."""
    
    def test_simple_enum(self):
        source = """
        enum class ExportAs {
            STREAM_JSONL, STREAM_CSV, XLSX
        }
        """
        results = parse_kotlin_enum(source)
        assert len(results) == 1
        
        info = results[0]
        assert info.name == "ExportAs"
        assert info.kind == "enum"
        assert info.enum_values == ["STREAM_JSONL", "STREAM_CSV", "XLSX"]
    
    def test_enum_with_values(self):
        source = """
        enum class Status(val label: String) {
            ACTIVE("Active"),
            INACTIVE("Inactive")
        }
        """
        results = parse_kotlin_enum(source)
        assert len(results) == 1
        assert "ACTIVE" in results[0].enum_values
        assert "INACTIVE" in results[0].enum_values
    
    def test_multiline_enum(self):
        source = """
        enum class Color {
            RED,
            GREEN,
            BLUE
        }
        """
        results = parse_kotlin_enum(source)
        assert len(results) == 1
        assert results[0].enum_values == ["RED", "GREEN", "BLUE"]


class TestParseKotlinSource:
    """Test full source parsing."""
    
    def test_mixed_definitions(self):
        source = """
        package com.gigwell.reports
        
        data class DateRangeFilter(
            var field: String? = null,
            var start: String? = null,
            var end: String? = null
        )
        
        enum class ExportAs {
            STREAM_JSONL, STREAM_CSV, XLSX
        }
        
        data class CustomFilterRequest(
            var dateRange: DateRangeFilter? = null,
            var exportAs: ExportAs? = null
        )
        """
        results = parse_kotlin_source(source)
        
        assert len(results) == 3
        
        data_classes = [r for r in results if r.kind == "data_class"]
        enums = [r for r in results if r.kind == "enum"]
        
        assert len(data_classes) == 2
        assert len(enums) == 1
        
        # Verify CustomFilterRequest references
        custom_filter = next(r for r in data_classes if r.name == "CustomFilterRequest")
        assert custom_filter.fields[0].original_type == "DateRangeFilter"
        assert custom_filter.fields[1].original_type == "ExportAs"


class TestFixtures:
    """Test against real fixtures."""
    
    @pytest.fixture
    def fixtures_path(self):
        return Path(__file__).parent / "fixtures"
    
    def test_fixture_file(self, fixtures_path):
        fixture = fixtures_path / "kotlin_types.kt"
        if fixture.exists():
            results = parse_kotlin_file(fixture)
            
            # Should find all defined types
            names = {r.name for r in results}
            assert "CustomFilterRequest" in names
            assert "DateRangeFilter" in names
            assert "IdentityFilter" in names
            assert "LocationFilter" in names
            assert "FinancialFilter" in names
            assert "ExportAs" in names
            
            # Verify CustomFilterRequest structure
            custom = next(r for r in results if r.name == "CustomFilterRequest")
            assert custom.kind == "data_class"
            assert len(custom.fields) == 7
            
            # Check nested type references
            date_range_field = next(f for f in custom.fields if f.name == "dateRange")
            assert date_range_field.original_type == "DateRangeFilter"
            
            # Check enum reference
            export_field = next(f for f in custom.fields if f.name == "exportAs")
            assert export_field.original_type == "ExportAs"
            
            # Verify ExportAs enum values
            export_as = next(r for r in results if r.name == "ExportAs")
            assert export_as.kind == "enum"
            assert export_as.enum_values == ["STREAM_JSONL", "STREAM_CSV", "XLSX"]
    
    def test_parse_kotlin_file_returns_list(self, fixtures_path):
        """Test that parse_kotlin_file returns a list of KotlinTypeInfo."""
        fixture = fixtures_path / "kotlin_types.kt"
        if fixture.exists():
            results = parse_kotlin_file(fixture)
            assert isinstance(results, list)
            assert all(isinstance(r, KotlinTypeInfo) for r in results)
