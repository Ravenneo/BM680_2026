#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import platform
import shutil
import subprocess
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


def module_report(name: str) -> dict[str, Any]:
    report: dict[str, Any] = {"name": name, "available": False}
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        report["error"] = str(exc)
        return report

    report["available"] = True
    report["file"] = getattr(module, "__file__", None)
    report["version"] = getattr(module, "__version__", None)
    names = dir(module)
    report["bsec_symbols"] = sorted(
        item for item in names if any(token in item.lower() for token in ("bsec", "iaq", "voc", "co2"))
    )[:80]
    return report


def run_i2cdetect(bus: int) -> dict[str, Any]:
    i2cdetect = shutil.which("i2cdetect") or "/usr/sbin/i2cdetect"
    if not Path(i2cdetect).exists():
        return {"available": False, "error": "i2cdetect not found"}
    result = subprocess.run(
        [i2cdetect, "-y", str(bus)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    return {
        "available": True,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def parse_i2c_addr(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    return int(str(value), 0)


def try_bme68x_raw_read(address: int, bus: int) -> dict[str, Any]:
    report: dict[str, Any] = {"attempted": True, "address": hex(address), "bus": bus}
    try:
        module = importlib.import_module("bme68x")
        klass = getattr(module, "BME68X")
    except Exception as exc:
        return {**report, "ok": False, "error": f"bme68x import failed: {exc}"}

    try:
        sensor = klass(address, bus)
        set_heatr_conf = getattr(sensor, "set_heatr_conf", None)
        if callable(set_heatr_conf):
            set_heatr_conf(1, 320, 100, 1)
        get_data = getattr(sensor, "get_data", None)
        if not callable(get_data):
            return {**report, "ok": False, "error": "BME68X.get_data not found"}
        data = get_data()
        return {**report, "ok": True, "data_type": type(data).__name__, "data": repr(data)[:2000]}
    except Exception as exc:
        return {**report, "ok": False, "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--bus", type=int, default=1)
    parser.add_argument("--read", action="store_true", help="attempt one bme68x raw read")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    cfg = load_config(config_path)
    bme_cfg = cfg.get("sensors", {}).get("bme690", {})
    bsec_cfg = bme_cfg.get("bsec", {})
    primary_addr = parse_i2c_addr(bme_cfg.get("i2c_primary"), 0x76)

    vendor_dir = resolve_path(config_path.parent, bsec_cfg.get("vendor_dir", "vendor/bsec"))
    state_file = resolve_path(config_path.parent, bsec_cfg.get("state_file", "data/bsec_state.bin"))
    config_file_value = str(bsec_cfg.get("config_file", "") or "")
    config_file = resolve_path(config_path.parent, config_file_value) if config_file_value else None

    report: dict[str, Any] = {
        "schema_version": "air_cluster.bsec_probe.v1",
        "python": sys.version,
        "platform": {
            "machine": platform.machine(),
            "system": platform.system(),
            "release": platform.release(),
        },
        "config": {
            "backend": bme_cfg.get("backend", "raw"),
            "bsec_enabled": bool(bsec_cfg.get("enabled", False)),
            "sample_interval_seconds": bsec_cfg.get("sample_interval_seconds"),
            "primary_i2c_address": hex(primary_addr),
            "vendor_dir": str(vendor_dir),
            "vendor_dir_exists": vendor_dir.exists(),
            "state_file": str(state_file),
            "state_file_exists": state_file.exists(),
            "config_file": str(config_file) if config_file else None,
            "config_file_exists": config_file.exists() if config_file else None,
        },
        "i2c": run_i2cdetect(args.bus),
        "modules": [
            module_report("bme68x"),
            module_report("bsec"),
            module_report("bsecConstants"),
            module_report("bme690"),
            module_report("bme680"),
        ],
    }

    if args.read:
        report["bme68x_raw_read"] = try_bme68x_raw_read(primary_addr, args.bus)

    print(json.dumps(report, indent=2, sort_keys=True))
    modules = {item["name"]: item for item in report["modules"]}
    ready = modules["bme68x"]["available"] and any(
        modules[name]["available"] for name in ("bsec", "bsecConstants")
    )
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
