# 12.11.26
# ruff: noqa: F403

import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve().parent

if importlib.util.find_spec("playwright") is None:
    collect_ignore_glob = ["*.py"]
else:
    from e2e_app import *


def pytest_ignore_collect(collection_path, config):
    """Collect the browser suite only when it is asked for by path (`pytest Test/e2e`, as CI does).

    Playwright's sync API keeps an event loop running in the process for the whole session: the Textual tests that
    a full run puts after it in the same process then fail with "Cannot run the event loop while another loop is running".
    """
    for arg in config.args:
        target = Path(arg.split("::", 1)[0]).resolve()
        if target == _HERE or _HERE in target.parents:
            return None
    return True
