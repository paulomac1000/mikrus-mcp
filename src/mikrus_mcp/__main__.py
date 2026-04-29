"""Entry point for running the package as a module."""

import sys

from mikrus_mcp.server import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
