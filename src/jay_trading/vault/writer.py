"""Atomic markdown writer for the Obsidian vault.

Why atomic: the vault is synced via OneDrive; partial writes routinely produce
``filename (conflicted).md`` files. We write to a sibling ``.tmp`` and ``rename``
so readers never see a half-written note.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from jay_trading.config import get_settings


def write_vault_file(relative_path: str | Path, content: str) -> Path:
    """Write ``content`` to ``<vault_root>/<relative_path>`` atomically.

    Parents are created on demand. Returns the absolute path written.
    """
    root = get_settings().vault_trading_root
    target = (root / Path(relative_path)).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    # Write to a tmp file in the same directory so rename is on the same
    # filesystem (otherwise rename would degrade to copy+delete).
    fd, tmp_name = tempfile.mkstemp(
        prefix=".tmp_",
        suffix=target.suffix or ".md",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    except Exception:
        # Best-effort cleanup of the temp file on failure.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target
