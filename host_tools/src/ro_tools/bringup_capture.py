"""Capture and parse the sensor-node bring-up probe output (``firmware/bringup``).

Two modes:

* **pre-erase**: run a fixed set of *read-only* ``esptool`` / ``espefuse`` commands
  against the board (still holding its factory firmware) and save their output. A
  hard allowlist refuses every write, erase, burn or RAM-load command.
* **capture**: read the probe's serial output until ``PROBE report.end`` (or a
  timeout), save the raw log and a JSON file of the parsed ``PROBE`` key/values.

The parser records raw evidence only; it draws no conclusion about the board.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

#: Repository ``logs/`` directory (anchored to the repo, not the working directory).
DEFAULT_LOG_DIR: Path = Path(__file__).resolve().parents[3] / "logs"
#: Probe console baud rate (UART0, CH343 "COM" port).
BAUD = 115200
#: Key whose appearance ends a capture.
END_KEY = "report.end"

#: Read-only esptool v5 sub-commands. Nothing else may be run.
ESPTOOL_ALLOWED: frozenset[str] = frozenset(
    {
        "chip-id",
        "read-mac",
        "flash-id",
        "get-security-info",
        "read-flash-sfdp",
        "read-flash-status",
        "version",
    }
)
#: Read-only espefuse v5 sub-commands. Nothing else may be run.
ESPEFUSE_ALLOWED: frozenset[str] = frozenset({"summary", "dump", "check-error"})
_ALLOWED: dict[str, frozenset[str]] = {"esptool": ESPTOOL_ALLOWED, "espefuse": ESPEFUSE_ALLOWED}
#: Substrings that are refused anywhere in an argument list (defence in depth).
_FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    "write",
    "erase",
    "burn",
    "load-ram",
    "load_ram",
    "do-not-confirm",
    "do_not_confirm",
)

#: The fixed pre-erase plan: (tool, sub-command, extra arguments).
PRE_ERASE_PLAN: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("esptool", "version", ()),
    ("esptool", "chip-id", ()),
    ("esptool", "read-mac", ()),
    ("esptool", "flash-id", ()),
    ("esptool", "read-flash-status", ()),
    ("esptool", "get-security-info", ()),
    # esptool v5 reads 1-4 SFDP bytes per call: SFDP header (0x00-0x07) and
    # the first parameter header (0x08-0x0F).
    ("esptool", "read-flash-sfdp", ("0", "4")),
    ("esptool", "read-flash-sfdp", ("4", "4")),
    ("esptool", "read-flash-sfdp", ("8", "4")),
    ("esptool", "read-flash-sfdp", ("12", "4")),
    ("espefuse", "summary", ()),
)

_PROBE_RE = re.compile(
    r"(?:^|[\s>])PROBE (?P<key>[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)=(?P<value>.*)$"
)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class ForbiddenCommandError(ValueError):
    """Raised when a command is not on the read-only allowlist."""


def normalize_subcommand(name: str) -> str:
    """Normalize an esptool/espefuse sub-command name (v4 underscores to v5 hyphens).

    :param name: Sub-command as typed.
    :returns: Lower-case, hyphenated name.
    """
    return name.strip().lower().replace("_", "-")


def check_command(tool: str, subcommand: str, args: Sequence[str] = ()) -> None:
    """Refuse anything that is not an allowlisted read-only command.

    :param tool: ``"esptool"`` or ``"espefuse"``.
    :param subcommand: Sub-command name (either spelling).
    :param args: Extra arguments after the sub-command.
    :raises ForbiddenCommandError: If the tool, sub-command or any argument is not allowed.
    """
    allowed = _ALLOWED.get(tool)
    if allowed is None:
        raise ForbiddenCommandError(f"tool not allowed: {tool!r}")
    sub = normalize_subcommand(subcommand)
    if sub not in allowed:
        raise ForbiddenCommandError(f"{tool} {subcommand!r} is not a permitted read-only command")
    for token in (subcommand, *args):
        low = token.lower()
        for frag in _FORBIDDEN_FRAGMENTS:
            if frag in low:
                raise ForbiddenCommandError(f"argument {token!r} contains forbidden {frag!r}")


def build_command(
    tool: str, port: str, subcommand: str, args: Sequence[str] = (), executable: str | None = None
) -> list[str]:
    """Build an argument vector for an allowlisted command.

    :param tool: ``"esptool"`` or ``"espefuse"``.
    :param port: Serial port, e.g. ``COM5``.
    :param subcommand: Sub-command name.
    :param args: Extra arguments.
    :param executable: Executable path; defaults to ``tool``.
    :returns: Argument vector for :func:`subprocess.run`.
    :raises ForbiddenCommandError: If the command is not allowlisted.
    """
    check_command(tool, subcommand, args)
    sub = normalize_subcommand(subcommand)
    exe = executable or tool
    if sub == "version":
        return [exe, sub]
    return [exe, "--chip", "esp32s3", "--port", port, sub, *args]


Runner = Callable[[list[str]], tuple[int, str]]


def _subprocess_runner(argv: list[str]) -> tuple[int, str]:
    """Run a command and return its exit status and combined output.

    :param argv: Argument vector.
    :returns: ``(returncode, stdout+stderr)``.
    """
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
    return proc.returncode, proc.stdout + proc.stderr


def timestamp() -> str:
    """Return a filename-safe local timestamp (no ``:``, which Windows forbids).

    :returns: ``YYYYmmdd-HHMMSS``.
    """
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def run_pre_erase(
    port: str,
    log_dir: Path = DEFAULT_LOG_DIR,
    runner: Runner | None = None,
    executables: dict[str, str] | None = None,
) -> Path:
    """Run the read-only pre-erase plan and save every command's output.

    :param port: Serial port of the board's "COM" (CH343) USB port.
    :param log_dir: Output directory.
    :param runner: Command runner (injected by tests); defaults to :mod:`subprocess`.
    :param executables: Optional ``{"esptool": path, "espefuse": path}`` overrides.
    :returns: Path of the written log.
    """
    run = runner or _subprocess_runner
    exes = executables or {}
    log_dir.mkdir(parents=True, exist_ok=True)
    out = log_dir / f"bringup-preerase-{timestamp()}.log"
    chunks: list[str] = []
    for tool, sub, args in PRE_ERASE_PLAN:
        exe = exes.get(tool) or shutil.which(tool) or tool
        argv = build_command(tool, port, sub, args, executable=exe)
        logger.info("running: {}", " ".join(argv))
        try:
            code, text = run(argv)
        except (OSError, subprocess.SubprocessError) as exc:
            code, text = -1, f"failed to run: {exc}\n"
        chunks.append(f"$ {' '.join(argv)}\n# exit {code}\n{text}\n")
        if code != 0:
            logger.warning("{} {} exited {}", tool, sub, code)
    out.write_text("".join(chunks), encoding="utf-8")
    logger.info("wrote {}", out)
    return out


@dataclass
class ProbeLog:
    """Parsed ``PROBE`` lines.

    Repeated keys (``report`` reruns, button events, walk events) keep every value in
    order; :meth:`last` gives the most recent one.
    """

    values: dict[str, list[str]] = field(default_factory=dict)

    def add(self, key: str, value: str) -> None:
        """Append one value.

        :param key: ``section.key``.
        :param value: Raw value text.
        """
        self.values.setdefault(key, []).append(value)

    def last(self, key: str) -> str | None:
        """Return the most recent value of a key.

        :param key: ``section.key``.
        :returns: Value, or ``None`` if never seen.
        """
        vals = self.values.get(key)
        return vals[-1] if vals else None

    @property
    def complete(self) -> bool:
        """True once at least one ``PROBE report.end`` was seen."""
        return END_KEY in self.values

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable summary.

        :returns: ``{"complete", "facts" (last value per key), "repeated" (keys seen
            more than once, all values)}``.
        """
        return {
            "complete": self.complete,
            "facts": {k: v[-1] for k, v in self.values.items()},
            "repeated": {k: v for k, v in self.values.items() if len(v) > 1},
        }


def parse_probe_line(line: str) -> tuple[str, str] | None:
    """Parse one ``PROBE <section>.<key>=<value>`` line.

    The value is everything after the first ``=``; ANSI codes and ``\\r`` are stripped.

    :param line: One line of console output.
    :returns: ``(key, value)`` or ``None`` if the line is not a probe line.
    """
    clean = _ANSI_RE.sub("", line).rstrip("\r\n")
    m = _PROBE_RE.search(clean)
    if m is None:
        return None
    return m.group("key"), m.group("value").rstrip()


def parse_probe_lines(lines: Iterable[str]) -> ProbeLog:
    """Parse many lines into a :class:`ProbeLog`.

    :param lines: Console output lines.
    :returns: Parsed log.
    """
    log = ProbeLog()
    for line in lines:
        parsed = parse_probe_line(line)
        if parsed is not None:
            log.add(*parsed)
    return log


def _reset_into_app(ser: Any) -> None:
    """Pulse EN through the CH343 auto-reset circuit with IO0 released.

    RTS asserted with DTR deasserted pulls EN low; DTR stays deasserted so GPIO0 is
    not held low and the chip boots the app, not the ROM download mode.

    Windows ``usbser.sys`` only sends an RTS change to the adapter when DTR is also
    written, so DTR is rewritten (still deasserted) after every RTS change, as
    esptool does.

    :param ser: Open :class:`serial.Serial`.
    """
    ser.dtr = False
    ser.rts = True
    ser.dtr = False
    time.sleep(0.1)
    ser.rts = False
    ser.dtr = False


def capture(
    port: str,
    log_dir: Path = DEFAULT_LOG_DIR,
    timeout_s: float = 120.0,
    reset: bool = True,
    request_report: bool = False,
) -> tuple[Path, Path, ProbeLog]:
    """Read the probe's console until ``PROBE report.end`` or timeout and save it.

    :param port: Serial port of the "COM" (CH343) USB port.
    :param log_dir: Output directory.
    :param timeout_s: Give up after this many seconds.
    :param reset: Reset the board into the app on open (CH343 auto-reset lines).
    :param request_report: Send ``report`` after opening (use with ``reset=False``).
    :returns: ``(raw log path, JSON path, parsed log)``.
    """
    import serial  # local import: tests of the pure functions need no serial port

    log_dir.mkdir(parents=True, exist_ok=True)
    stem = f"bringup-{timestamp()}"
    raw_path = log_dir / f"{stem}.log"
    json_path = log_dir / f"{stem}.json"
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = BAUD
    ser.timeout = 0.2
    ser.dtr = False
    ser.rts = False
    ser.open()
    lines: list[str] = []
    try:
        if reset:
            _reset_into_app(ser)
        if request_report:
            ser.write(b"report\r\n")
        deadline = time.monotonic() + timeout_s
        buf = b""
        with raw_path.open("w", encoding="utf-8", newline="\n") as raw:
            while time.monotonic() < deadline:
                buf += ser.read(4096)
                while b"\n" in buf:
                    chunk, buf = buf.split(b"\n", 1)
                    text = chunk.decode("utf-8", errors="replace").rstrip("\r")
                    raw.write(text + "\n")
                    lines.append(text)
                    parsed = parse_probe_line(text)
                    if parsed and parsed[0] == END_KEY:
                        deadline = 0.0
                        break
            if buf:
                tail = buf.decode("utf-8", errors="replace")
                raw.write(tail)
                lines.append(tail)
    finally:
        ser.close()
    log = parse_probe_lines(lines)
    if not log.complete:
        logger.warning("no '{}' within {} s; saving partial capture", END_KEY, timeout_s)
    json_path.write_text(json.dumps(log.to_json_dict(), indent=2), encoding="utf-8")
    logger.info("wrote {} and {}", raw_path, json_path)
    return raw_path, json_path, log
