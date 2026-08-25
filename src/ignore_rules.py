"""Driftgram Sync Tool: gitignore-style ignore matching per sync root."""
from __future__ import annotations

from typing import List

import pathspec

from .config import DEFAULT_IGNORES, RootConfig, SyncSettings


class IgnoreMatcher:
    def __init__(self, root: RootConfig, global_ignore: List[str], settings: SyncSettings):
        patterns: List[str] = []
        if settings.use_default_ignores:
            patterns.extend(DEFAULT_IGNORES)
        patterns.extend(global_ignore)
        patterns.extend(root.ignore)
        self._spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    def is_ignored(self, rel_path: str) -> bool:
        # pathspec expects forward slashes regardless of OS
        normalized = rel_path.replace("\\", "/")
        return self._spec.match_file(normalized)
