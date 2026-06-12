"""PyInstaller entry shim -> codefuel GUI."""
import sys

from codefuel.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
