"""Compatibility entry point; implementation lives in viralx.web_app."""

import sys
from viralx import web_app as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    # Preserve module identity for existing WSGI users and integrations.
    sys.modules[__name__] = _implementation
