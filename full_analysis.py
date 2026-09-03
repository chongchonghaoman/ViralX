"""Compatibility entry point for the legacy batch-analysis command."""

import sys
from viralx import full_analysis as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
