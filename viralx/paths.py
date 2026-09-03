"""Stable project paths shared by the packaged application.

Moving Python modules must not relocate existing configuration, caches, web
assets or the bundled TK Note skill. No directories are created on import.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
