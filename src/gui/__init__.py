"""Driftgram desktop GUI (PySide6).

Sits on top of src.app.supervisor, which owns the sync engine on its own
thread. Nothing in this package is imported by the CLI, so the command-line
tool keeps working with no Qt installed.
"""
