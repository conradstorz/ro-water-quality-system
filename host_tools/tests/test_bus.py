"""Two simulated nodes sharing one bus, polled through the real client."""

import pytest

from ro_tools.client import CommsError, SensorNodeClient
from ro_tools.generated import registers as reg
from ro_tools.sim.bus import Bus
from ro_tools.sim.presets import RO_SKID_PROFILE, TANK_PROFILE, apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer


@pytest.fixture()
def bus_and_server():
    bus = Bus()
    ro = Responder(RegisterBank(), unit_id=1)
    tank = Responder(RegisterBank(), unit_id=2)
    bus.add(ro)
    bus.add(tank)
    apply_preset(ro, "healthy", RO_SKID_PROFILE)
    apply_preset(tank, "healthy", TANK_PROFILE)
    with TcpSimServer(bus) as server:
        yield bus, server


def read(server, unit_id):
    with SensorNodeClient.tcp(*server.address, timeout=0.3, unit_id=unit_id) as client:
        return client.read_snapshot()


def test_each_unit_answers_with_its_own_identity(bus_and_server):
    _, server = bus_and_server
    assert read(server, 1).node_type == int(reg.NodeType.RO_SKID)
    assert read(server, 2).node_type == int(reg.NodeType.TANK)


def test_unknown_unit_gets_no_answer(bus_and_server):
    _, server = bus_and_server
    with pytest.raises(CommsError):
        read(server, 3)


def test_silent_node_does_not_affect_the_other(bus_and_server):
    bus, server = bus_and_server
    bus.node(2).drop_responses = True
    assert read(server, 1).node_type == int(reg.NodeType.RO_SKID)
    with pytest.raises(CommsError):
        read(server, 2)


def test_nodes_keep_independent_sequences(bus_and_server):
    bus, server = bus_and_server
    bus.node(1).bank.commit()
    assert read(server, 1).snapshot_sequence == 2
    assert read(server, 2).snapshot_sequence == 1


def test_duplicate_unit_id_rejected():
    bus = Bus()
    bus.add(Responder(RegisterBank(), unit_id=1))
    with pytest.raises(ValueError, match="already on the bus"):
        bus.add(Responder(RegisterBank(), unit_id=1))


@pytest.mark.parametrize("unit_id", [0, 16, 247])
def test_out_of_range_unit_id_rejected(unit_id):
    with pytest.raises(ValueError, match="outside 1..15"):
        Bus().add(Responder(RegisterBank(), unit_id=unit_id))


def test_unit_ids_sorted():
    bus = Bus()
    bus.add(Responder(RegisterBank(), unit_id=5))
    bus.add(Responder(RegisterBank(), unit_id=2))
    assert bus.unit_ids == (2, 5)
