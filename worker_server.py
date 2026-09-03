"""Compatibility entry point for existing Worker launchers and WSGI imports."""

import sys
from viralx import worker_server as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
