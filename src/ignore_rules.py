"""Driftgram Sync Tool: gitignore-style ignore matching per sync root."""
from __future__ import annotations

from typing import List

import pathspec

from .config import DEFAULT_IGNORES, INTERNAL_IGNORES, RootConfig, SyncSettings


class IgnoreMatcher:
    def __init__(self, root: RootConfig, global_ignore: List[str], settings: SyncSettings):
        # INTERNAL_IGNORES is applied unconditionally, before anything the user
        # controls: those patterns cover the tool's own scratch files, which
        # live inside a watched folder while a download is in flight. Leaving
        # them matchable would let a slow download's half-written .driftgram-tmp
        # be picked up by the watcher and uploaded as if it were a real file.
        patterns: List[str] = list(INTERNAL_IGNORES)
        if settings.use_default_ignores:
            patterns.extend(DEFAULT_IGNORES)
        patterns.extend(global_ignore)
        patterns.extend(root.ignore)
        self._spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    def is_ignored(self, rel_path: str) -> bool:
        # pathspec expects forward slashes regardless of OS
        normalized = rel_path.replace("\\", "/")
        return self._spec.match_file(normalized)
