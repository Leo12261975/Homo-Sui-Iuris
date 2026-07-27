"""Shared pytest setup for the tests/ tree.

The project is a flat collection of scripts at the repo root (not an installed
package), and the tests import those modules directly (`import bootstrap_relay`,
etc.). `pythonpath = ["."]` in pyproject already puts the repo root on sys.path;
this belt-and-suspenders insert keeps the tests importable if they're ever run
with a runner that ignores that ini option.
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
