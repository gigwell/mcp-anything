"""Type registry for resolving complex types from source code.

This module scans source directories for type definitions and provides
recursive type resolution for generating proper MCP schemas.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Literal
import logging

from mcp_anything.models.analysis import ParameterSpec, Language
from mcp_anything.analysis.kotlin_parser import (
    parse_kotlin_file,
    KotlinTypeInfo,
)
from mcp_anything.analysis.schema_extractor import extract_java_pojo_fields

logger = logging.getLogger(__name__)


@dataclass
class TypeRegistryConfig:
    """Configuration for type registry behavior."""
    max_depth: int = 5
    include_patterns: list[str] = field(default_factory=lambda: ["**/*.kt", "**/*.java"])
    exclude_patterns: list[str] = field(default_factory=lambda: ["**/test/**", "**/Test*.kt"])


class TypeRegistry:
    """Registry of resolved types from the codebase.
    
    Scans source files for type definitions and provides resolution
    of nested types for MCP schema generation.
    
    Usage:
        registry = TypeRegistry()
        registry.scan_directory(Path("/path/to/src"), Language.JAVA)
        
        # Resolve a parameter with nested types
        param = ParameterSpec(name="filter", type="object", original_type="CustomFilterRequest")
        resolved = registry.resolve_parameter(param)
        # resolved.properties now contains nested fields
    """
    
    def __init__(self, config: Optional[TypeRegistryConfig] = None):
        self.config = config or TypeRegistryConfig()
        self._types: dict[str, KotlinTypeInfo] = {}
        self._file_index: dict[str, Path] = {}  # class_name -> source_file
    
    def scan_directory(self, path: Path, language: Language) -> None:
        """Scan a directory for type definitions.
        
        Args:
            path: Root directory to scan
            language: Source language (JAVA for Kotlin/Java)
        """
        if language not in (Language.JAVA,):
            logger.warning(f"Type registry only supports Java/Kotlin, got {language}")
            return
        
        # Resolve symlinks
        path = path.resolve()
        
        for pattern in self.config.include_patterns:
            for file_path in path.glob(pattern):
                # Skip excluded patterns
                if any(file_path.match(p) for p in self.config.exclude_patterns):
                    continue
                
                self._scan_file(file_path)
        
        logger.info(f"Type registry scanned {len(self._types)} types from {len(self._file_index)} files")
    
    def _scan_file(self, file_path: Path) -> None:
        """Scan a single file for type definitions."""
        try:
            if file_path.suffix == '.kt':
                types = parse_kotlin_file(file_path)
                for t in types:
                    self._types[t.name] = t
                    self._file_index[t.name] = file_path
            elif file_path.suffix == '.java':
                # For Java files, we need to extract classes and their fields
                source = file_path.read_text(encoding='utf-8')
                # Find all class definitions in the file
                import re
                class_pattern = r'(?:public\s+)?class\s+(\w+)\s*(?:extends\s+\w+\s*)?(?:implements\s+[\w,\s]+)?\s*\{'
                for match in re.finditer(class_pattern, source):
                    class_name = match.group(1)
                    # Extract fields using schema_extractor
                    fields = extract_java_pojo_fields(source, class_name)
                    if fields:
                        # Convert SchemaField to ParameterSpec
                        params = [
                            ParameterSpec(
                                name=f.name,
                                type=f.type,
                                required=f.required,
                                original_type=f.original_type,
                                description=f.description,
                                default=f.default,
                            )
                            for f in fields
                        ]
                        # Create a KotlinTypeInfo-like structure for consistency
                        type_info = KotlinTypeInfo(
                            name=class_name,
                            kind="class",
                            fields=params,
                            source_file=str(file_path),
                            source_line=source[:match.start()].count('\n') + 1,
                        )
                        self._types[class_name] = type_info
                        self._file_index[class_name] = file_path
        except Exception as e:
            logger.warning(f"Failed to parse {file_path}: {e}")
    
    def resolve_type(self, name: str) -> Optional[KotlinTypeInfo]:
        """Look up a type by name.
        
        Args:
            name: Type name to look up
            
        Returns:
            KotlinTypeInfo if found, None otherwise
        """
        return self._types.get(name)
    
    def resolve_parameter(
        self,
        param: ParameterSpec,
        depth: int = 0,
        visited: Optional[set[str]] = None
    ) -> ParameterSpec:
        """Recursively resolve a parameter's nested types.
        
        Args:
            param: Parameter to resolve
            depth: Current recursion depth
            visited: Set of visited type names (for cycle detection)
            
        Returns:
            ParameterSpec with properties populated for object types
        """
        # Initialize visited set
        if visited is None:
            visited = set()
        
        # Check depth limit
        if depth > self.config.max_depth:
            logger.warning(f"Max depth ({self.config.max_depth}) reached for {param.name}")
            return param
        
        # Check for cycles
        if param.original_type and param.original_type in visited:
            logger.warning(f"Circular reference detected: {param.original_type}")
            return param
        
        # Only resolve if we have an original_type reference
        if not param.original_type:
            return param
        
        # Look up the type
        type_info = self.resolve_type(param.original_type)
        if not type_info:
            logger.debug(f"Type not found in registry: {param.original_type}")
            return param
        
        # Add to visited set
        visited = visited | {param.original_type}
        
        # Handle enum types
        if type_info.kind == "enum" and type_info.enum_values:
            param.enum_values = type_info.enum_values
            param.type = "string"  # Enums are strings in MCP schema
            return param
        
        # Handle object types (data class, class)
        if type_info.kind in ("data_class", "class"):
            param.type = "object"
            param.properties = [
                self.resolve_parameter(p, depth + 1, visited)
                for p in type_info.fields
            ]
        
        return param
    
    def resolve_all_parameters(
        self,
        parameters: list[ParameterSpec]
    ) -> list[ParameterSpec]:
        """Resolve all parameters in a list.
        
        Args:
            parameters: List of parameters to resolve
            
        Returns:
            List of resolved parameters
        """
        return [self.resolve_parameter(p) for p in parameters]
    
    def get_type_count(self) -> int:
        """Return the number of types in the registry."""
        return len(self._types)
    
    def get_type_names(self) -> list[str]:
        """Return all type names in the registry."""
        return list(self._types.keys())
