#!/usr/bin/env python3
"""Acquire debris and refresh the shared catalog."""
import sys
from acquire_data import main
if __name__ == "__main__":
    sys.argv += ["--only", "debris"]
    main()
