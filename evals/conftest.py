from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def _load_scenarios() -> list[dict]:
    path = Path(__file__).parent / "golden_scenarios.yaml"
    with path.open() as fh:
        return yaml.safe_load(fh)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "scenario" in metafunc.fixturenames:
        scenarios = _load_scenarios()
        metafunc.parametrize(
            "scenario",
            scenarios,
            ids=[s["id"] for s in scenarios],
        )
