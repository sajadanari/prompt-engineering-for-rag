"""Workspace management: copy git-tracked templates into the gitignored workspace."""

from __future__ import annotations

import shutil

from .config import SUPPORTED_LANGUAGES, TEMPLATES_DIR, WORKSPACE_DIR, ConfigError


def init_workspace(languages: list[str], force: bool = False) -> list[str]:
    """Copy templates into workspace/. Returns list of copied items.

    Existing files are preserved unless force=True, so `init` is safe to
    re-run after new templates are added.
    """
    if not TEMPLATES_DIR.exists():
        raise ConfigError(f"Templates directory missing: {TEMPLATES_DIR}")

    copied: list[str] = []
    WORKSPACE_DIR.mkdir(exist_ok=True)

    # Top-level config.yaml
    src_config = TEMPLATES_DIR / "config.yaml"
    dst_config = WORKSPACE_DIR / "config.yaml"
    if src_config.exists() and (force or not dst_config.exists()):
        shutil.copy2(src_config, dst_config)
        copied.append("config.yaml")

    # Per-language prompt/context files
    for lang in languages:
        if lang not in SUPPORTED_LANGUAGES:
            raise ConfigError(
                f"Unknown language '{lang}'. Supported: {', '.join(SUPPORTED_LANGUAGES)}"
            )
        src_dir = TEMPLATES_DIR / lang
        dst_dir = WORKSPACE_DIR / lang
        dst_dir.mkdir(exist_ok=True)
        for src_file in sorted(src_dir.iterdir()):
            dst_file = dst_dir / src_file.name
            if force or not dst_file.exists():
                shutil.copy2(src_file, dst_file)
                copied.append(f"{lang}/{src_file.name}")

    return copied
