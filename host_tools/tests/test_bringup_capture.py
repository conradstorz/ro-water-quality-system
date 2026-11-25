"""Bring-up probe capture: PROBE-line parser, read-only esptool allowlist, CLI wiring."""

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ro_tools import bringup_capture as bc
from ro_tools import cli

REPO = Path(__file__).resolve().parents[2]
FIRMWARE = REPO / "firmware" / "bringup"


# ------------------------------------------------------------------ parser


def test_parse_simple_line():
    assert bc.parse_probe_line("PROBE chip.revision=v0.2") == ("chip.revision", "v0.2")


def test_value_split_on_first_equals_only():
    line = "PROBE pin.4=pu:1,pd:0,verdict:floating"
    assert bc.parse_probe_line(line) == ("pin.4", "pu:1,pd:0,verdict:floating")
    assert bc.parse_probe_line("PROBE x.y=a=b=c") == ("x.y", "a=b=c")


def test_strips_cr_and_ansi():
    assert bc.parse_probe_line("\x1b[0;32mPROBE temp.internal_c=31.5\x1b[0m\r\n") == (
        "temp.internal_c",
        "31.5",
    )


def test_prompt_prefix_tolerated():
    assert bc.parse_probe_line("bringup> PROBE arm.state=armed") == ("arm.state", "armed")


@pytest.mark.parametrize(
    "line",
    [
        "",
        "I (123) boot: ESP-IDF v5.5.3",
        "PROBE nodot=1",
        "PROBE chip.model",
        "XPROBE chip.model=9",
        "probe chip.model=9",
    ],
)
def test_non_probe_lines_ignored(line):
    assert bc.parse_probe_line(line) is None


def test_mac_value_kept_raw():
    assert bc.parse_probe_line("PROBE mac.base=7c:df:a1:00:11:22") == (
        "mac.base",
        "7c:df:a1:00:11:22",
    )


def test_repeated_keys_keep_all_values_last_wins():
    log = bc.parse_probe_lines(
        [
            "PROBE report.begin=1",
            "PROBE boot_button.event=press",
            "PROBE boot_button.event=release",
            "PROBE temp.internal_c=30.0",
            "PROBE report.end=1",
            "PROBE report.begin=2",
            "PROBE temp.internal_c=31.0",
        ]
    )
    assert log.values["boot_button.event"] == ["press", "release"]
    assert log.last("temp.internal_c") == "31.0"
    assert log.complete
    d = log.to_json_dict()
    assert d["facts"]["temp.internal_c"] == "31.0"
    assert d["repeated"]["temp.internal_c"] == ["30.0", "31.0"]
    assert "chip.model" not in d["facts"]
    json.dumps(d)


def test_incomplete_without_end():
    log = bc.parse_probe_lines(["PROBE report.begin=1"])
    assert not log.complete
    assert log.last("missing.key") is None


_SEG = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=1, max_size=12)
_VAL = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E), min_size=0, max_size=40
).map(str.rstrip)


@given(section=_SEG, key=_SEG, value=_VAL)
def test_roundtrip(section, key, value):
    assert bc.parse_probe_line(f"PROBE {section}.{key}={value}\r\n") == (f"{section}.{key}", value)


# --------------------------------------------------------------- allowlist


@pytest.mark.parametrize(
    "tool,sub",
    [
        ("esptool", "chip-id"),
        ("esptool", "chip_id"),
        ("esptool", "read-mac"),
        ("esptool", "flash-id"),
        ("esptool", "get-security-info"),
        ("esptool", "read-flash-sfdp"),
        ("esptool", "read-flash-status"),
        ("espefuse", "summary"),
        ("espefuse", "dump"),
    ],
)
def test_allowlist_accepts_read_only(tool, sub):
    bc.check_command(tool, sub)


@pytest.mark.parametrize(
    "tool,sub",
    [
        ("esptool", "write_flash"),
        ("esptool", "write-flash"),
        ("esptool", "erase_flash"),
        ("esptool", "erase-flash"),
        ("esptool", "erase-region"),
        ("esptool", "erase_region"),
        ("esptool", "write-mem"),
        ("esptool", "write_mem"),
        ("esptool", "write-flash-status"),
        ("esptool", "load-ram"),
        ("esptool", "load_ram"),
        ("esptool", "run"),
        ("esptool", "read-flash"),
        ("esptool", "merge-bin"),
        ("espefuse", "burn-efuse"),
        ("espefuse", "burn_efuse"),
        ("espefuse", "burn-key"),
        ("espefuse", "burn-bit"),
        ("espefuse", "write-protect-efuse"),
        ("espefuse", "read-protect-efuse"),
        ("esptool", "summary"),
        ("espefuse", "chip-id"),
        ("espsecure", "digest-sbv2-public-key"),
        ("sh", "chip-id"),
    ],
)
def test_allowlist_rejects(tool, sub):
    with pytest.raises(bc.ForbiddenCommandError):
        bc.check_command(tool, sub)


@pytest.mark.parametrize("arg", ["write-flash", "--do-not-confirm", "ERASE", "burn_efuse"])
def test_allowlist_rejects_forbidden_arguments(arg):
    with pytest.raises(bc.ForbiddenCommandError):
        bc.check_command("esptool", "read-mac", [arg])


def test_pre_erase_plan_is_all_allowlisted():
    for tool, sub, args in bc.PRE_ERASE_PLAN:
        bc.check_command(tool, sub, args)


def test_build_command_shape():
    argv = bc.build_command("esptool", "COM7", "read_flash_sfdp", ["0", "256"])
    assert argv == ["esptool", "--chip", "esp32s3", "--port", "COM7", "read-flash-sfdp", "0", "256"]
    with pytest.raises(bc.ForbiddenCommandError):
        bc.build_command("esptool", "COM7", "erase-flash")


def test_run_pre_erase_uses_only_plan(tmp_path):
    seen: list[list[str]] = []

    def runner(argv):
        seen.append(argv)
        return 0, f"ok {argv[-1]}\n"

    out = bc.run_pre_erase(
        "COM9", tmp_path, runner=runner, executables={"esptool": "E", "espefuse": "F"}
    )
    assert len(seen) == len(bc.PRE_ERASE_PLAN)
    for argv in seen:
        assert argv[0] in {"E", "F"}
        assert not any(f in " ".join(argv).lower() for f in ("write", "erase", "burn"))
    assert ":" not in out.name
    assert "# exit 0" in out.read_text(encoding="utf-8")


def test_default_log_dir_is_repo_logs():
    assert bc.DEFAULT_LOG_DIR == REPO / "logs"


# --------------------------------------------------------------------- CLI


def test_cli_bringup_parser():
    args = cli.build_parser().parse_args(["bringup", "--port", "COM5", "--pre-erase"])
    assert args.command == "bringup" and args.pre_erase and args.port == "COM5"


def test_cli_bringup_pre_erase_dispatch(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        bc, "run_pre_erase", lambda port, logs: calls.append((port, logs)) or tmp_path / "x"
    )
    assert cli.main(["bringup", "--port", "COM5", "--pre-erase", "--logs", str(tmp_path)]) == 0
    assert calls == [("COM5", tmp_path)]


# ------------------------------------------------------- firmware consistency


def test_firmware_not_covered_list_matches_readme():
    main_c = (FIRMWARE / "src" / "main.c").read_text(encoding="utf-8")
    readme = (FIRMWARE / "README.md").read_text(encoding="utf-8")
    block = main_c.split("#define NOT_COVERED", 1)[1].split("static int", 1)[0]
    items = "".join(part for part in block.split('"')[1::2]).split(",")
    assert len(items) >= 8
    for item in items:
        assert f"`{item}`" in readme, item


def test_firmware_gpio_calls_only_in_pin_policy():
    for path in (FIRMWARE / "src").glob("*.c"):
        if path.name == "pin_policy.c":
            continue
        text = path.read_text(encoding="utf-8")
        for name in (
            "gpio_config(",
            "gpio_set_direction(",
            "gpio_set_pull_mode(",
            "gpio_set_level(",
        ):
            assert name not in text, f"{path.name} calls {name}"


# ------------------------------------------------------------ CH343 reset


class _FakeSerial:
    """Records every DTR/RTS write in order."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, bool]] = []
        self._dtr = False
        self._rts = False

    @property
    def dtr(self) -> bool:
        return self._dtr

    @dtr.setter
    def dtr(self, value: bool) -> None:
        self._dtr = value
        self.writes.append(("dtr", value))

    @property
    def rts(self) -> bool:
        return self._rts

    @rts.setter
    def rts(self, value: bool) -> None:
        self._rts = value
        self.writes.append(("rts", value))


def test_reset_into_app_never_asserts_dtr(monkeypatch):
    monkeypatch.setattr(bc.time, "sleep", lambda _s: None)
    ser = _FakeSerial()
    bc._reset_into_app(ser)
    assert ("dtr", True) not in ser.writes
    assert ("rts", True) in ser.writes
    assert ser.rts is False and ser.dtr is False
    # usbser.sys workaround: every RTS write is followed by a DTR write
    for i, (line, _value) in enumerate(ser.writes):
        if line == "rts":
            assert ser.writes[i + 1][0] == "dtr"
