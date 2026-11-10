from collections.abc import Iterator

import pytest
from sqlalchemy import Engine

from tests.isolation.world import World, build_world


@pytest.fixture
def world(migrated_engine: Engine) -> Iterator[World]:
    yield build_world(migrated_engine)
