#!/usr/bin/env python3
"""Uruchamia wszystkie testy ASTRO (stdlib unittest, bez zewnętrznych zależności).

Kod wyjścia 0 = wszystkie zielone.
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PARENT = os.path.dirname(ROOT)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)


def main():
    suite = unittest.defaultTestLoader.discover(HERE, pattern="test_*.py",
                                                top_level_dir=PARENT)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    print(f"\nTESTY ASTRO: {total - failed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
