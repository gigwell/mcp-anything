"""Kotlin source parser for data classes, enums, and sealed classes.

This module extracts type information from Kotlin source files to enable
proper MCP schema generation with nested types and enum values.
"""

import re
from dataclasses import dataclass, field
from typing import Optional, Literal
from pathlib import Path

from mcp_anything.models.analysis import ParameterSpec


@dataclass
class KotlinTypeInfo:
    """Resolved type information from a Kotlin source file."""
    name: str
    kind: Literal["data_class", "class", "enum", "sealed_class", "interface"]
    fields: list[ParameterSpec] = field(default_factory=list)
    enum_values: Optional[list[str]] = None
    generic_params: list[str] = field(default_factory=list)
    source_file: str = ""
    source_line: int = 0


# Regex patterns for Kotlin parsing

# data class ClassName<T>(val name: Type, ...)
_KOTLIN_DATA_CLASS_RE = re.compile(
    r'(?:public\s+|private\s+|internal\s+)?'
    r'data\s+class\s+(\w+)'
    r'(?:\s*<([^>]+)>)?'  # Generic parameters like <T, U>
    r'\s*\(([^)]+)\)',
    re.DOTALL
)

# class ClassName : Something (regular class with constructor)
_KOTLIN_CLASS_RE = re.compile(
    r'(?:public\s+|private\s+|internal\s+)?'
    r'(?:open\s+|abstract\s+)?'
    r'class\s+(\w+)'
    r'(?:\s*<([^>]+)>)?'
    r'(?:\s*:\s*\w+(?:\([^)]*\))?(?:\s*,\s*\w+)*)?'  # Inheritance
    r'\s*\(([^)]+)\)',  # Constructor parameters
    re.DOTALL
)

# enum class ExportAs { STREAM_JSONL, STREAM_CSV }
# Also handles: enum class Status(val label: String) { ... }
_KOTLIN_ENUM_RE = re.compile(
    r'(?:public\s+)?enum\s+class\s+(\w+)'
    r'(?:\([^)]*\))?'  # Optional constructor parameters like (val label: String)
    r'(?:\s*:\s*\w+)?'  # Optional underlying type
    r'\s*\{([^}]+)\}',
    re.DOTALL
)

# Individual enum values (handles simple and complex enums)
_KOTLIN_ENUM_VALUE_RE = re.compile(
    r'(\w+)'
    r'(?:\s*\([^)]*\))?'  # Optional constructor args
    r'(?:\s*\{[^}]*\})?'  # Optional body
    r'\s*(?:,|$)'
)

# Field in data class: val name: Type? = default
_KOTLIN_FIELD_RE = re.compile(
    r'(?:val|var)\s+'  # val or var
    r'(\w+)\s*:\s*'  # Field name
    r'([\w<>,?\s\[\]]+?)'  # Type (with generics, nullable)
    r'(?:\s*=\s*([^,)]+))?'  # Default value (captured)
    r'\s*(?:,|$)',
    re.DOTALL
)

# Sealed class: sealed class Result { class Success(...) : Result(); class Error(...) : Result() }
_KOTLIN_SEALED_RE = re.compile(
    r'(?:public\s+)?sealed\s+(?:class|interface)\s+(\w+)'
    r'(?:\s*<([^>]+)>)?'
    r'\s*\{([^}]+)\}',
    re.DOTALL
)


# Kotlin type mappings
_KOTLIN_TYPE_MAP = {
    # Primitives
    "String": "string",
    "Int": "integer",
    "Long": "integer",
    "Short": "integer",
    "Byte": "integer",
    "Float": "float",
    "Double": "float",
    "Boolean": "boolean",
    "Char": "string",
    
    # Collections
    "List": "array",
    "MutableList": "array",
    "ArrayList": "array",
    "Set": "array",
    "MutableSet": "array",
    "HashSet": "array",
    
    # Maps
    "Map": "object",
    "MutableMap": "object",
    "HashMap": "object",
    
    # Special
    "Any": "object",
    "Unit": "null",
    "Nothing": "null",
}


def map_kotlin_type(kotlin_type: str) -> tuple[str, Optional[str]]:
    """Map a Kotlin type to MCP schema type.
    
    Returns:
        Tuple of (mcp_type, original_type_if_complex)
    """
    # Clean up the type
    kotlin_type = kotlin_type.strip().rstrip('?')
    
    # Handle nullable
    is_nullable = kotlin_type.endswith('?')
    if is_nullable:
        kotlin_type = kotlin_type[:-1].strip()
    
    # Handle generics: List<String> -> array with item type String
    if '<' in kotlin_type:
        base_type = kotlin_type.split('<')[0].strip()
        inner_type = kotlin_type[kotlin_type.find('<')+1:kotlin_type.rfind('>')].strip()
        
        mcp_base = _KOTLIN_TYPE_MAP.get(base_type, "object")
        
        # For arrays, we might want to track the inner type
        if mcp_base == "array":
            inner_mcp, inner_orig = map_kotlin_type(inner_type)
            return mcp_base, None  # Could store inner type info
        
        return mcp_base, kotlin_type
    
    # Simple type
    base = kotlin_type.split('[')[0].strip()  # Handle Array<T> syntax
    
    mcp_type = _KOTLIN_TYPE_MAP.get(base, "object")
    
    # If it's not a primitive, it's a complex type
    original_type = base if mcp_type == "object" and base not in _KOTLIN_TYPE_MAP else None
    
    return mcp_type, original_type


def _parse_kotlin_default_value(kotlin_type: str, default_str: Optional[str]) -> tuple[Optional[str], bool]:
    """Parse a Kotlin default value expression to a Python default literal.

    Returns (python_default, has_default) where:
    - python_default: Python literal string like "False", "True", '"value"', "42", or None
    - has_default: True if a non-null default was found

    Args:
        kotlin_type: The Kotlin type of the field (e.g., "Boolean", "String", "Int")
        default_str: The default value expression (e.g., "false", '"value"', "42", "null")
    """
    if not default_str:
        return None, False

    default_str = default_str.strip()

    # Handle null explicitly
    if default_str == "null":
        return None, False

    # Handle boolean: false/true
    if kotlin_type in ("Boolean", "boolean"):
        if default_str == "false":
            return "False", True
        elif default_str == "true":
            return "True", True

    # Handle numeric types (Int, Long, Float, Double)
    if kotlin_type in ("Int", "Long", "Float", "Double", "Int?", "Long?", "Float?", "Double?"):
        try:
            # Validate it's a valid number
            float(default_str)
            return default_str, True
        except ValueError:
            pass

    # Handle String: "value" -> "value" (strip Kotlin quotes, add Python quotes)
    if "String" in kotlin_type:
        if default_str.startswith('"') and default_str.endswith('"'):
            inner = default_str[1:-1]
            # Escape any internal quotes and backslashes
            inner = inner.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{inner}"', True

    # Handle empty string
    if default_str == '""':
        return '""', True

    return None, False


def parse_kotlin_data_class(source: str, class_name: Optional[str] = None) -> list[KotlinTypeInfo]:
    """Parse all Kotlin data classes from source.

    Args:
        source: Kotlin source code
        class_name: Optional specific class to find

    Returns:
        List of KotlinTypeInfo objects
    """
    results = []

    for match in _KOTLIN_DATA_CLASS_RE.finditer(source):
        name = match.group(1)

        # Skip if looking for specific class
        if class_name and name != class_name:
            continue

        generic_params = match.group(2)
        params_str = match.group(3)

        fields = []
        for field_match in _KOTLIN_FIELD_RE.finditer(params_str):
            field_name = field_match.group(1)
            field_type = field_match.group(2).strip()
            default_expr = field_match.group(3)  # May be None

            mcp_type, original_type = map_kotlin_type(field_type)
            is_required = not ('?' in field_type or field_type.endswith('?'))

            # Parse default value from Kotlin to Python
            python_default, has_default = _parse_kotlin_default_value(field_type, default_expr)

            fields.append(ParameterSpec(
                name=field_name,
                type=mcp_type,
                required=is_required,
                original_type=original_type,
                description="",
                default=python_default if has_default else None,
            ))

        results.append(KotlinTypeInfo(
            name=name,
            kind="data_class",
            fields=fields,
            generic_params=generic_params.split(',') if generic_params else [],
            source_line=source[:match.start()].count('\n') + 1,
        ))

    return results


def parse_kotlin_enum(source: str, enum_name: Optional[str] = None) -> list[KotlinTypeInfo]:
    """Parse all Kotlin enum classes from source.
    
    Args:
        source: Kotlin source code
        enum_name: Optional specific enum to find
        
    Returns:
        List of KotlinTypeInfo objects with enum_values populated
    """
    results = []
    
    for match in _KOTLIN_ENUM_RE.finditer(source):
        name = match.group(1)
        
        if enum_name and name != enum_name:
            continue
        
        values_str = match.group(2)
        values = []
        
        for val_match in _KOTLIN_ENUM_VALUE_RE.finditer(values_str):
            val_name = val_match.group(1)
            if val_name:  # Skip empty matches
                values.append(val_name)
        
        results.append(KotlinTypeInfo(
            name=name,
            kind="enum",
            enum_values=values,
            source_line=source[:match.start()].count('\n') + 1,
        ))
    
    return results


def parse_kotlin_file(file_path: Path) -> list[KotlinTypeInfo]:
    """Parse a Kotlin file and return all type definitions."""
    source = file_path.read_text(encoding='utf-8')
    
    results = []
    results.extend(parse_kotlin_data_class(source))
    results.extend(parse_kotlin_enum(source))
    
    for r in results:
        r.source_file = str(file_path)
    
    return results


def parse_kotlin_source(source: str) -> list[KotlinTypeInfo]:
    """Parse Kotlin source string and return all type definitions."""
    results = []
    results.extend(parse_kotlin_data_class(source))
    results.extend(parse_kotlin_enum(source))
    return results
