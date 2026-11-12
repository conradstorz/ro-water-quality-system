"""The YAML is normative; these tests fail when the markdown drifts from it."""

import re
from pathlib import Path

from ro_tools import schema

REPO = Path(__file__).resolve().parents[2]


def _table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if line.startswith("|") and not set(line) <= set("|-: "):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def test_fault_catalog_matches_yaml():
    m = schema.load()
    text = (REPO / "docs/specs/FAULT_CODE_CATALOG.md").read_text(encoding="utf-8")
    rows = [r for r in _table_rows(text) if r[0].isdigit()]
    doc = {}
    for code, source, severity, description in rows:
        state_dependent = severity.endswith("when required")
        doc[int(code)] = (source, severity.split()[0], description, state_dependent)
    yaml_codes = {
        f.code: (f.source, f.default_severity, f.description, f.state_dependent)
        for f in m.fault_codes
    }
    assert doc == yaml_codes


def test_status_extension_table_matches_yaml():
    m = schema.load()
    text = (REPO / "protocol/CONTROLLER_STATUS_EXTENSION.md").read_text(encoding="utf-8")
    doc = {int(r[0]): r[1] for r in _table_rows(text) if r[0].isdigit()}
    ext = {r.address: r.name for r in m.holding_registers if r.access == "write_multiple_only"}
    assert doc == ext


def test_ro_states_match_yaml():
    m = schema.load()
    text = (REPO / "protocol/CONTROLLER_STATUS_EXTENSION.md").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("RO states:"))
    sentence = line.split(".")[0]
    doc = {int(n): name for n, name in re.findall(r"(\d+)=(\w+)", sentence)}
    assert doc == m.enums["ro_state"]
