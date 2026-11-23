"""Controller name-table push policy (spec section 5): pure decision logic."""

from __future__ import annotations

import dataclasses

import pytest

from ro_tools.onewire_names import NamePushPolicy, NodeObservation

OBS = NodeObservation(unit_id=1, boot_counter=7, scan_generation=3, revision=0xBEEF)


def _pushed(obs: NodeObservation = OBS) -> NamePushPolicy:
    policy = NamePushPolicy()
    assert policy.should_push(obs)
    policy.record_pushed(obs)
    return policy


def test_first_contact_pushes() -> None:
    policy = NamePushPolicy()
    assert policy.should_push(OBS)
    assert policy.supported(OBS.unit_id)


def test_identical_observation_skips() -> None:
    policy = _pushed()
    assert not policy.should_push(OBS)
    assert not policy.should_push(dataclasses.replace(OBS))


@pytest.mark.parametrize(
    "change",
    [{"boot_counter": 8}, {"scan_generation": 4}, {"revision": 0xBEF0}],
    ids=["boot_counter", "scan_generation", "revision"],
)
def test_each_trigger_pushes_once(change: dict[str, int]) -> None:
    policy = _pushed()
    changed = dataclasses.replace(OBS, **change)
    assert policy.should_push(changed)
    policy.record_pushed(changed)
    assert not policy.should_push(changed)


def test_scan_generation_wrap_still_pushes() -> None:
    policy = _pushed(dataclasses.replace(OBS, scan_generation=0xFFFF))
    assert policy.should_push(dataclasses.replace(OBS, scan_generation=0))


def test_nodes_are_independent() -> None:
    policy = _pushed()
    other = dataclasses.replace(OBS, unit_id=2)
    assert policy.should_push(other)
    policy.record_unsupported(other)
    assert not policy.should_push(OBS)
    assert policy.supported(1)
    assert not policy.supported(2)


def test_unpushed_failure_is_retried() -> None:
    """A write that failed (comms, mismatch, rejection) is not recorded, so it is retried."""
    policy = NamePushPolicy()
    assert policy.should_push(OBS)
    assert policy.should_push(OBS)
    policy = _pushed()
    changed = dataclasses.replace(OBS, revision=1)
    assert policy.should_push(changed)
    assert policy.should_push(changed)


@pytest.mark.parametrize("first_contact", [True, False])
def test_unsupported_skips_until_boot_counter_changes(first_contact: bool) -> None:
    policy = NamePushPolicy() if first_contact else _pushed()
    policy.record_unsupported(OBS)
    assert not policy.supported(OBS.unit_id)
    assert not policy.should_push(OBS)
    assert not policy.should_push(dataclasses.replace(OBS, scan_generation=99))
    assert not policy.should_push(dataclasses.replace(OBS, revision=1))
    assert not policy.should_push(dataclasses.replace(OBS, scan_generation=99, revision=1))
    rebooted = dataclasses.replace(OBS, boot_counter=8)
    assert policy.should_push(rebooted)


def test_recovery_after_reboot_into_supporting_firmware() -> None:
    policy = NamePushPolicy()
    policy.record_unsupported(OBS)
    rebooted = dataclasses.replace(OBS, boot_counter=8)
    assert policy.should_push(rebooted)
    policy.record_pushed(rebooted)
    assert policy.supported(OBS.unit_id)
    assert not policy.should_push(rebooted)
    assert policy.should_push(dataclasses.replace(rebooted, scan_generation=4))


def test_still_unsupported_after_reboot() -> None:
    policy = NamePushPolicy()
    policy.record_unsupported(OBS)
    rebooted = dataclasses.replace(OBS, boot_counter=8)
    assert policy.should_push(rebooted)
    policy.record_unsupported(rebooted)
    assert not policy.should_push(rebooted)
    assert not policy.should_push(dataclasses.replace(rebooted, revision=1))
    assert policy.should_push(dataclasses.replace(rebooted, boot_counter=9))
