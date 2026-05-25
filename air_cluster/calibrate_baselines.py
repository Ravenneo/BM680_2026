#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.yaml"


def load_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        yaml = importlib.import_module("yaml")
        return yaml.safe_load(text)


def resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                print(f"warning: skipped invalid JSONL line {line_no}", file=sys.stderr)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = int(round((len(values) - 1) * pct))
    return values[index]


def collect(samples: list[dict[str, Any]], key_path: list[str]) -> list[float]:
    values: list[float] = []
    for sample in samples:
        current: Any = sample
        for key in key_path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if current is None:
            continue
        try:
            values.append(float(current))
        except (TypeError, ValueError):
            continue
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--last", type=int, default=2000, help="number of latest samples to inspect")
    parser.add_argument("--min-valid", type=int, default=120)
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    cfg = load_config(config_path)
    raw_path = resolve_path(config_path.parent, cfg["paths"]["raw_samples"])
    if not raw_path.exists():
        print(f"raw sample file not found: {raw_path}", file=sys.stderr)
        return 1

    samples = list(iter_jsonl(raw_path))[-args.last :]
    valid = [
        sample
        for sample in samples
        if sample.get("validity", {}).get("status") in ("OK", "PARTIAL")
        and sample.get("event_signature") in ("CLEAN", "SENSOR_WARMUP")
    ]
    if len(valid) < args.min_valid:
        print(
            f"not enough valid calm samples: {len(valid)} found, {args.min_valid} required",
            file=sys.stderr,
        )
        return 2

    channels = {
        "bme690_gas_ohms": ["bme690", "gas_ohms"],
        "mics_reducing": ["mics6814", "reducing"],
        "mics_oxidising": ["mics6814", "oxidising"],
        "mics_nh3": ["mics6814", "nh3"],
    }
    report: dict[str, Any] = {
        "schema_version": "air_cluster.baseline_calibration.v1",
        "source": str(raw_path),
        "sample_count": len(samples),
        "valid_calm_sample_count": len(valid),
        "baselines": {},
    }
    for name, path in channels.items():
        values = collect(valid, path)
        report["baselines"][name] = {
            "count": len(values),
            "median": statistics.median(values) if values else None,
            "p10": percentile(values, 0.10),
            "p90": percentile(values, 0.90),
        }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
