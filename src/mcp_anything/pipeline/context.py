"""Shared pipeline context."""

from pathlib import Path
from typing import Optional, TYPE_CHECKING

from rich.console import Console

from mcp_anything.config import CLIOptions
from mcp_anything.models.manifest import GenerationManifest

if TYPE_CHECKING:
    from mcp_anything.analysis.type_registry import TypeRegistry


class PipelineContext:
    """Shared state passed through all pipeline phases."""

    def __init__(self, options: CLIOptions, manifest: GenerationManifest, console: Console) -> None:
        self.options = options
        self.manifest = manifest
        self.console = console
        self.type_registry: Optional["TypeRegistry"] = None

    @property
    def codebase_path(self) -> Path:
        return self.options.codebase_path.resolve()

    @property
    def output_dir(self) -> Path:
        return Path(self.manifest.output_dir)

    @property
    def manifest_path(self) -> Path:
        return self.output_dir / "mcp-anything-manifest.json"

    def save_manifest(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.manifest.save(self.manifest_path)
