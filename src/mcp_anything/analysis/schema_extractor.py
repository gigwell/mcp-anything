"""Extract request/response schemas from type definitions."""

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from mcp_anything.models.analysis import Language

# Type mappings for each language
_PYTHON_TYPE_MAP = {
    "str": "string",
    "int": "integer",
    "float": "float",
    "bool": "boolean",
    "list": "array",
    "List": "array",
    "dict": "object",
    "Dict": "object",
}

_JAVA_TYPE_MAP = {
    "String": "string",
    "int": "integer",
    "Integer": "integer",
    "long": "integer",
    "Long": "integer",
    "float": "float",
    "Float": "float",
    "double": "float",
    "Double": "float",
    "boolean": "boolean",
    "Boolean": "boolean",
    "List": "array",
    "ArrayList": "array",
    "Set": "array",
    "Map": "object",
    "HashMap": "object",
}

# Java primitive types (always required unless nullable annotation present)
_JAVA_PRIMITIVE_TYPES = {
    "int", "long", "short", "byte", "float", "double", "boolean", "char",
}

# Java boxed primitive types (treated as potentially nullable)
_JAVA_BOXED_PRIMITIVES = {
    "Integer", "Long", "Short", "Byte", "Float", "Double", "Boolean", "Character",
}

_TS_TYPE_MAP = {
    "string": "string",
    "number": "integer",
    "boolean": "boolean",
    "any": "string",
    "object": "object",
    "Array": "array",
}


@dataclass
class SchemaField:
    """A field in a schema definition."""
    name: str
    type: str = "string"
    required: bool = True
    description: str = ""
    default: Optional[str] = None
    original_type: Optional[str] = None  # original language type name for nested resolution


def _python_type_to_schema(annotation_node: ast.expr) -> tuple[str, bool]:
    """Convert a Python AST annotation node to a schema type string and required flag.

    Returns (type_string, is_required).
    """
    required = True

    # Handle Optional[X] -> typing.Optional subscript
    if isinstance(annotation_node, ast.Subscript):
        # Optional[X] appears as Subscript(value=Name('Optional'), slice=...)
        if isinstance(annotation_node.value, ast.Name) and annotation_node.value.id == "Optional":
            required = False
            # Recurse into the inner type
            inner = annotation_node.slice
            schema_type, _ = _python_type_to_schema(inner)
            return schema_type, required
        # Handle List[X], Dict[X, Y], etc.
        if isinstance(annotation_node.value, ast.Name):
            base = annotation_node.value.id
            return _PYTHON_TYPE_MAP.get(base, "string"), required
        if isinstance(annotation_node.value, ast.Attribute):
            base = annotation_node.value.attr
            return _PYTHON_TYPE_MAP.get(base, "string"), required

    # Handle X | None (BinOp with BitOr)
    if isinstance(annotation_node, ast.BinOp) and isinstance(annotation_node.op, ast.BitOr):
        # Check if either side is None
        left = annotation_node.left
        right = annotation_node.right
        if isinstance(right, ast.Constant) and right.value is None:
            required = False
            schema_type, _ = _python_type_to_schema(left)
            return schema_type, required
        if isinstance(left, ast.Constant) and left.value is None:
            required = False
            schema_type, _ = _python_type_to_schema(right)
            return schema_type, required

    # Simple Name node
    if isinstance(annotation_node, ast.Name):
        return _PYTHON_TYPE_MAP.get(annotation_node.id, "string"), required

    # Attribute node (e.g., typing.List)
    if isinstance(annotation_node, ast.Attribute):
        return _PYTHON_TYPE_MAP.get(annotation_node.attr, "string"), required

    return "string", required


def _extract_field_call_info(call_node: ast.Call) -> dict:
    """Extract description and default from a Field(...) call."""
    info: dict = {}
    has_ellipsis_first_arg = False

    # Check first positional arg for Ellipsis (meaning required)
    if call_node.args:
        first = call_node.args[0]
        if isinstance(first, ast.Constant) and first.value is ...:
            has_ellipsis_first_arg = True

    for kw in call_node.keywords:
        if kw.arg == "description" and isinstance(kw.value, ast.Constant):
            info["description"] = str(kw.value.value)
        elif kw.arg == "default" and isinstance(kw.value, ast.Constant):
            info["default"] = str(kw.value.value)
            info["has_default"] = True

    if "has_default" not in info and not has_ellipsis_first_arg:
        # Check for default as first positional arg (non-ellipsis)
        if call_node.args and not has_ellipsis_first_arg:
            first = call_node.args[0]
            if isinstance(first, ast.Constant) and first.value is not ...:
                info["default"] = str(first.value)
                info["has_default"] = True

    return info


def extract_pydantic_fields(source: str, class_name: str) -> list[SchemaField]:
    """Extract fields from a Pydantic BaseModel subclass using AST."""
    tree = ast.parse(source)
    fields: list[SchemaField] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue

        for item in node.body:
            if not isinstance(item, ast.AnnAssign):
                continue
            if not isinstance(item.target, ast.Name):
                continue

            name = item.target.id
            annotation = item.annotation
            schema_type, required = _python_type_to_schema(annotation)
            description = ""
            default = None

            # Check if there's a default value
            if item.value is not None:
                if isinstance(item.value, ast.Call):
                    # Could be Field(...)
                    func = item.value.func
                    is_field_call = (
                        (isinstance(func, ast.Name) and func.id == "Field")
                        or (isinstance(func, ast.Attribute) and func.attr == "Field")
                    )
                    if is_field_call:
                        info = _extract_field_call_info(item.value)
                        description = info.get("description", "")
                        if "has_default" in info:
                            required = False
                            default = info.get("default")
                    else:
                        # Some other call as default value
                        required = False
                elif isinstance(item.value, ast.Constant):
                    required = False
                    default = str(item.value.value) if item.value.value is not None else None
                    if item.value.value is None:
                        required = False
                else:
                    # Any other default value expression
                    required = False

            fields.append(SchemaField(
                name=name,
                type=schema_type,
                required=required,
                description=description,
                default=default,
            ))

        break  # Found the class, stop searching

    return fields


def _is_java_field_required(java_type: str, field_context: str = "") -> bool:
    """Determine if a Java field should be required in the schema.

    For MCP schema purposes, ALL fields are optional to allow partial updates.
    This means clients can send only the fields they want to modify without
    validation errors for missing fields.

    Args:
        java_type: The Java type of the field
        field_context: Optional surrounding text to check for annotations (unused, kept for API compatibility)
    """
    # All fields are optional for MCP schema to support partial updates
    return False


def _parse_java_default_value(java_type: str, default_str: str) -> tuple[Optional[str], bool]:
    """Parse a Java default value expression to a Python default literal.

    Returns (python_default, has_default) where:
    - python_default: Python literal string like "False", "True", '"USD"', "42", or None
    - has_default: True if a non-null default was found

    Args:
        java_type: The Java type of the field (e.g., "boolean", "String", "int")
        default_str: The default value expression (e.g., "false", '"USD"', "42", "null")
    """
    if not default_str:
        return None, False

    default_str = default_str.strip()

    # Handle null explicitly
    if default_str == "null":
        return None, False

    # Handle primitive boolean: false/true
    if java_type == "boolean":
        if default_str == "false":
            return "False", True
        elif default_str == "true":
            return "True", True

    # Handle boxed Boolean: Boolean.FALSE/Boolean.TRUE
    if java_type == "Boolean":
        if default_str == "Boolean.FALSE":
            return "False", True
        elif default_str == "Boolean.TRUE":
            return "True", True
        elif default_str == "false":
            return "False", True
        elif default_str == "true":
            return "True", True

    # Handle numeric types (int, long, float, double, Integer, Long, Float, Double)
    if java_type in ("int", "long", "float", "double", "Integer", "Long", "Float", "Double"):
        # Just use the numeric value as-is (valid Python syntax)
        try:
            # Validate it's a valid number
            float(default_str)
            return default_str, True
        except ValueError:
            pass

    # Handle String: "value" -> "value" (strip Java quotes, add Python quotes)
    if java_type == "String":
        # Check for string literal like "USD"
        if default_str.startswith('"') and default_str.endswith('"'):
            inner = default_str[1:-1]
            # Escape any internal quotes and backslashes
            inner = inner.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{inner}"', True

    # Handle new Type() instantiations - no sensible default, treat as null
    if default_str.startswith("new "):
        return None, False

    # Handle static references with dot notation
    # Only treat as enum if the java_type suggests it's an enum type
    # (not a collection type like List, Set, etc.)
    if "." in default_str and not default_str.startswith('"'):
        parts = default_str.split(".")
        if len(parts) == 2:
            # Check if this is likely an enum by examining the java_type
            # Enums have simple type names like "ExportAs", "Status", etc.
            # Collections have types like "List<X>", "Set<X>"
            base_type = java_type.split("<")[0].strip()  # Handle generics
            is_collection = base_type in ("List", "ArrayList", "Set", "HashSet", "Collection", "Map", "HashMap")
            is_array = java_type.endswith("[]")

            # Only treat as enum if NOT a collection/array type
            if not is_collection and not is_array and parts[1].isupper():
                return f'"{parts[1]}"', True

            # For collections/arrays with static defaults, no valid Python default
            return None, False

    return None, False


def extract_java_pojo_fields(source: str, class_name: str) -> list[SchemaField]:
    """Extract fields from a Java class (POJOs, records).

    Rules for field inclusion and optionality:
    - Static fields (static, static final) are excluded
    - Injected fields (@Inject, @Autowired) are excluded
    - Logger fields (LOGGER, LOG) are excluded
    - @JsonIgnore fields are excluded (they're not serialized)
    - Java primitive types (int, long, boolean, etc.) are required
    - All other types (String, custom classes, collections) are optional
      unless marked with @NotNull/@NonNull annotations
    - Default values are extracted from field initializers
    """
    fields: list[SchemaField] = []

    # Try to find the class block
    class_pattern = r'(?:public\s+)?class\s+' + re.escape(class_name) + r'\s*(?:extends\s+\w+\s*)?(?:implements\s+[\w,\s]+)?\s*\{([\s\S]*)'
    class_match = re.search(class_pattern, source)

    if class_match:
        class_body = class_match.group(1)
        # Balance braces to find end of class
        depth = 1
        end = 0
        for i, ch in enumerate(class_body):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        class_body = class_body[:end]

        # Match field declarations including preceding annotations
        # Captures: (1) annotations and modifiers, (2) type, (3) name, (4) optional initializer
        field_pattern = r'((?:@\w+(?:\s*\([^)]*\))?\s*)*)\s*(?:private|public|protected)\s+(?:static\s+)?(?:final\s+)?([\w<>,\s\[\]]+)\s+(\w+)\s*(?:=\s*([^;]+))?\s*;'
        for match in re.finditer(field_pattern, class_body):
            annotations_and_modifiers = match.group(1)
            java_type = match.group(2).strip()
            field_name = match.group(3)
            default_expr = match.group(4)  # May be None if no initializer

            # Skip static fields (already filtered in pattern, but double-check)
            if 'static' in annotations_and_modifiers:
                continue

            # Skip injected fields (@Inject, @Autowired)
            if re.search(r'@(Inject|Autowired)', annotations_and_modifiers):
                continue

            # Skip @JsonIgnore fields (not part of the API)
            if re.search(r'@JsonIgnore', annotations_and_modifiers):
                continue

            # Skip logger fields (common pattern)
            if field_name in ('LOGGER', 'LOG', 'logger', 'log'):
                continue

            # Map Java type to schema type
            base_type = re.split(r'[<\[\s]', java_type)[0]
            
            # Determine schema type and original_type for nested resolution
            if base_type in _JAVA_TYPE_MAP:
                schema_type = _JAVA_TYPE_MAP[base_type]
                original_type = None
            else:
                # Custom class type - set as object with original_type for nested resolution
                schema_type = "object"
                original_type = base_type

            # Determine if required based on type and annotations
            field_context = annotations_and_modifiers
            required = _is_java_field_required(java_type, field_context)

            # Parse default value from Java to Python
            python_default, has_default = _parse_java_default_value(java_type, default_expr or "")

            fields.append(SchemaField(
                name=field_name,
                type=schema_type,
                required=required,
                original_type=original_type,
                default=python_default if has_default else None,
            ))
    else:
        # Try Java record syntax: record Foo(String name, int age)
        record_pattern = r'(?:public\s+)?record\s+' + re.escape(class_name) + r'\s*\(([^)]+)\)'
        record_match = re.search(record_pattern, source)
        if record_match:
            params = record_match.group(1)
            for param in params.split(','):
                param = param.strip()
                if not param:
                    continue
                parts = param.rsplit(None, 1)
                if len(parts) == 2:
                    java_type, field_name = parts
                    base_type = re.split(r'[<\[\s]', java_type.strip())[0]
                    
                    # Determine schema type and original_type for nested resolution
                    if base_type in _JAVA_TYPE_MAP:
                        schema_type = _JAVA_TYPE_MAP[base_type]
                        original_type = None
                    else:
                        # Custom class type - set as object with original_type for nested resolution
                        schema_type = "object"
                        original_type = base_type
                    
                    # Records: use same logic for required/optional
                    required = _is_java_field_required(java_type)
                    fields.append(SchemaField(
                        name=field_name,
                        type=schema_type,
                        required=required,
                        original_type=original_type,
                    ))

    return fields


def extract_typescript_interface_fields(source: str, interface_name: str) -> list[SchemaField]:
    """Extract fields from a TypeScript interface."""
    fields: list[SchemaField] = []

    # Find the interface or type block
    iface_pattern = r'(?:interface|type)\s+' + re.escape(interface_name) + r'\s*(?:extends\s+[\w,\s]+)?\s*\{([^}]+)\}'
    iface_match = re.search(iface_pattern, source)
    if not iface_match:
        return fields

    body = iface_match.group(1)

    field_pattern = r'(\w+)(\?)?\s*:\s*([\w\[\]|<>,\s"\']+)'
    for match in re.finditer(field_pattern, body):
        field_name = match.group(1)
        optional = match.group(2) == '?'
        ts_type = match.group(3).strip().rstrip(';').strip()

        # Map TS type to schema type
        base_type = re.split(r'[\[\]|<>,\s]', ts_type)[0]
        schema_type = _TS_TYPE_MAP.get(base_type, "string")

        fields.append(SchemaField(
            name=field_name,
            type=schema_type,
            required=not optional,
        ))

    return fields


def extract_schema(source: str, type_name: str, language: Language) -> list[SchemaField]:
    """Dispatch to the appropriate extractor based on language."""
    if language == Language.PYTHON:
        return extract_pydantic_fields(source, type_name)
    elif language == Language.JAVA:
        return extract_java_pojo_fields(source, type_name)
    elif language in (Language.TYPESCRIPT, Language.JAVASCRIPT):
        return extract_typescript_interface_fields(source, type_name)
    return []
