"""Frozen file computation — determine which paths are read-only for a given layer."""

from __future__ import annotations

from sorkit.config import SorConfig


def get_frozen_paths(config: SorConfig, layer_idx: int) -> list[str]:
    """Get all frozen paths when working on a given layer.

    Frozen = always_frozen + surface files from all layers below this one.
    """
    paths = list(config.always_frozen)
    for i in range(layer_idx):
        paths.extend(config.layers[i].surface)
    return paths


def is_path_frozen(path: str, frozen_paths: list[str]) -> bool:
    """Check if a file path matches any frozen path pattern.

    Uses substring/prefix matching to handle both exact files and directories
    (e.g., "tests/" matches "tests/test_foo.py").
    """
    for frozen in frozen_paths:
        # Directory pattern: "tests/" matches any path starting with "tests/"
        if frozen.endswith("/") and path.startswith(frozen):
            return True
        # Exact match
        if path == frozen:
            return True
        # Path is inside a frozen directory (handles "tests" without trailing slash)
        if path.startswith(frozen + "/"):
            return True
    return False
