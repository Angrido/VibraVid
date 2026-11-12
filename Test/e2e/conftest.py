# 12.11.26
# ruff: noqa: F403

import importlib.util

if importlib.util.find_spec("playwright") is None:
    collect_ignore_glob = ["*.py"]
else:
    from e2e_app import *
