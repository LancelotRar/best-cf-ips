import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / 'best-cf-ipv4-collector.py'


@pytest.fixture(scope='session')
def collector():
    """Load the collector module via importlib (filename has hyphens)."""
    spec = importlib.util.spec_from_file_location('best_cf_ipv4_collector', SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
