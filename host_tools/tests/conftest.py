"""Build the host sensor node once per session and run instances of it."""

import contextlib
import os
import queue
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path

import pytest

SENSOR_NODE_DIR = Path(__file__).resolve().parents[2] / "firmware" / "sensor_node"
_STARTUP_TIMEOUT_S = 10.0


@pytest.fixture(scope="session")
def node_program(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the PlatformIO ``native`` environment into a temporary directory.

    A missing toolchain fails the tests: skipping would hide every node check.

    :returns: Path of the built program.
    """
    pio = shutil.which("pio")
    if pio is None:
        pytest.fail("PlatformIO ('pio') is not on PATH; it is needed to build the sensor node")
    build_dir = tmp_path_factory.mktemp("node_build")
    env = dict(os.environ, PLATFORMIO_BUILD_DIR=str(build_dir))
    result = subprocess.run(
        [pio, "run", "--project-dir", str(SENSOR_NODE_DIR), "--environment", "native"],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    if result.returncode != 0:
        pytest.fail(f"sensor node build failed:\n{result.stdout}\n{result.stderr}")
    program = build_dir / "native" / ("program.exe" if os.name == "nt" else "program")
    assert program.is_file(), f"build produced no {program}"
    return program


def _first_line(proc: subprocess.Popen[str]) -> str:
    """Read the program's first output line without hanging on a silent program."""
    lines: queue.Queue[str] = queue.Queue()
    assert proc.stdout is not None
    threading.Thread(target=lambda: lines.put(proc.stdout.readline()), daemon=True).start()
    try:
        return lines.get(timeout=_STARTUP_TIMEOUT_S)
    except queue.Empty:
        return ""


NodeRunner = Callable[..., AbstractContextManager[int]]


@pytest.fixture(scope="session")
def run_node(node_program: Path) -> NodeRunner:
    """Return a context manager that runs one node and yields its TCP port.

    Positional arguments are passed to the host program.
    """

    @contextlib.contextmanager
    def run(*args: str) -> Iterator[int]:
        proc = subprocess.Popen([str(node_program), *args], stdout=subprocess.PIPE, text=True)
        try:
            line = _first_line(proc)
            assert line.startswith("PORT "), f"node did not start: {line!r}, exit {proc.poll()}"
            yield int(line.split()[1])
        finally:
            proc.kill()
            proc.wait(timeout=10)
            if proc.stdout is not None:
                proc.stdout.close()

    return run
