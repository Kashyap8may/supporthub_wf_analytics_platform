from datetime import date

import pytest

from data_generator.config import GeneratorConfig
from data_generator.master import build_master
from data_generator.simulate import generate
from data_generator.simulation import simulate

SMALL = GeneratorConfig(seed=7, start_date=date(2026, 7, 1), days=12).scaled(0.25)


@pytest.fixture(scope="session")
def small_cfg() -> GeneratorConfig:
    return SMALL


@pytest.fixture(scope="session")
def generated(tmp_path_factory):
    out = tmp_path_factory.mktemp("output")
    manifest = generate(SMALL, out)
    return out, manifest


@pytest.fixture(scope="session")
def simulated():
    md = build_master(SMALL)
    return md, simulate(SMALL, md)
