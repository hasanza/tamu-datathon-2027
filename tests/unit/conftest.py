import pytest

from control_tower.data.loader import load_world
from control_tower.graph.ontology import build_graph
from control_tower.world.twin import Twin


@pytest.fixture(scope="session")
def world():
    return load_world()


@pytest.fixture(scope="session")
def graph(world):
    return build_graph(world)


@pytest.fixture(scope="session")
def twin():
    return Twin()
