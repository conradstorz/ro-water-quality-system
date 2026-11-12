from pathlib import Path
import yaml


def test_register_addresses_unique_by_table():
    path = Path(__file__).resolve().parents[2] / "protocol" / "register_map.yaml"
    mapping = yaml.safe_load(path.read_text(encoding="utf-8"))
    for table in ("input_registers", "holding_registers"):
        occupied = set()
        for field in mapping[table]:
            addresses = set(range(field["address"], field["address"] + field.get("words", 1)))
            assert not occupied.intersection(addresses), field["name"]
            occupied.update(addresses)
