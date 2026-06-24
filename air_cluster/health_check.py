#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
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


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def parse_iso(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def age_from_iso(value: Any) -> float | None:
    ts = parse_iso(value)
    return time.time() - ts if ts is not None else None


def ssh_target(archive: dict[str, Any]) -> str:
    return f"{archive.get('user', 'pi')}@{archive['host']}"


def ssh_options(archive: dict[str, Any]) -> list[str]:
    options = [
        "-p",
        str(int(archive.get("port", 22))),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=8",
    ]
    key = archive.get("ssh_key")
    if key:
        key_path = os.path.expanduser(str(key))
        if Path(key_path).exists():
            options.extend(["-i", key_path])
    return options


def run_ssh(archive: dict[str, Any], remote_command: str, timeout: float = 15.0) -> dict[str, Any]:
    cmd = ["ssh", *ssh_options(archive), ssh_target(archive), remote_command]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except Exception as exc:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(exc)}


def disk_report(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    used_pct = (usage.used / usage.total) * 100.0 if usage.total else 0.0
    return {
        "path": str(path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_percent": round(used_pct, 2),
    }


def file_report(name: str, path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        "name": name,
        "path": str(path),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else 0,
        "modified_age_seconds": round(time.time() - path.stat().st_mtime, 3) if exists else None,
    }


def archive_status_report(path: Path, max_age: float) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return {"exists": False, "path": str(path), "ok": False, "error": "missing archive status"}, False
    try:
        status = read_json(path)
        age = age_from_iso(status.get("finished_at"))
        ok = bool(status.get("ok")) and age is not None and age <= max_age
        return {
            "exists": True,
            "path": str(path),
            "ok": ok,
            "last_ok": bool(status.get("ok")),
            "age_seconds": age,
            "target": status.get("target"),
            "started_at": status.get("started_at"),
            "finished_at": status.get("finished_at"),
            "error": status.get("error"),
        }, ok
    except Exception as exc:
        return {"exists": True, "path": str(path), "ok": False, "error": str(exc)}, False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--max-age-seconds", type=float, default=120.0)
    parser.add_argument("--archive-max-age-seconds", type=float, default=7200.0)
    parser.add_argument("--max-disk-used-percent", type=float, default=90.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--jsonl", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    cfg = load_config(config_path)
    base = config_path.parent
    paths = {
        name: resolve_path(base, value)
        for name, value in cfg["paths"].items()
        if name != "data_dir"
    }
    data_dir = resolve_path(base, cfg["paths"]["data_dir"])
    archive = cfg.get("archive", {})

    ok = True
    checks: list[dict[str, Any]] = []

    file_checks = [
        file_report("raw_samples", paths["raw_samples"]),
        file_report("hourly_batches", paths["hourly_batches"]),
        file_report("daily_summary", paths["daily_summary"]),
        file_report("latest_state", paths["latest_state"]),
        file_report("baseline_state", paths["baseline_state"]),
        file_report("archive_status", paths["archive_status"]),
        file_report("archive_log", paths["archive_log"]),
    ]
    for item in file_checks:
        if item["name"] in ("raw_samples", "latest_state") and not item["exists"]:
            ok = False
            item["ok"] = False
        else:
            item["ok"] = True

    latest: dict[str, Any] = {}
    latest_age = None
    latest_ok = False
    raw_age = None
    raw_ok = False
    if paths["latest_state"].exists():
        try:
            latest = read_json(paths["latest_state"])
            latest_age = age_from_iso(latest.get("timestamp"))
            latest_ok = latest_age is not None and latest_age <= args.max_age_seconds
            if latest.get("event_signature") == "SENSOR_ERROR":
                latest_ok = False
            validity = latest.get("validity", {}) if isinstance(latest.get("validity"), dict) else {}
            if validity.get("status") == "SENSOR_ERROR":
                latest_ok = False
        except Exception as exc:
            latest = {"error": str(exc)}
    if paths["raw_samples"].exists():
        raw_age = time.time() - paths["raw_samples"].stat().st_mtime
        raw_ok = raw_age <= args.max_age_seconds
    if not latest_ok or not raw_ok:
        ok = False

    data_dir.mkdir(parents=True, exist_ok=True)
    local_disk = disk_report(data_dir)
    local_disk_ok = local_disk["used_percent"] <= args.max_disk_used_percent
    if not local_disk_ok:
        ok = False

    ssh_check = {"ok": False, "skipped": not archive.get("enabled", True)}
    remote_disk = {"ok": False, "skipped": True}
    if archive.get("enabled", True):
        ssh_check = run_ssh(archive, "echo air-sensor-archive-ok", timeout=15)
        if not ssh_check["ok"]:
            ok = False
        else:
            remote_disk = run_ssh(
                archive,
                f"df -P {archive['remote_dir'].rsplit('/', 1)[0]} 2>/dev/null || df -P /home/pi",
                timeout=15,
            )
            remote_disk["skipped"] = False
            if not remote_disk["ok"]:
                ok = False

    archive_status, archive_ok = archive_status_report(
        paths["archive_status"], args.archive_max_age_seconds
    )
    if archive.get("enabled", True) and not archive_ok:
        ok = False

    result = {
        "ok": ok,
        "node": cfg.get("node", {}).get("name"),
        "hardware_generation": cfg.get("node", {}).get("hardware_generation"),
        "local_data_freshness": {
            "ok": latest_ok and raw_ok,
            "latest_age_seconds": latest_age,
            "raw_samples_modified_age_seconds": raw_age,
            "max_age_seconds": args.max_age_seconds,
        },
        "latest_state": {
            "event_signature": latest.get("event_signature"),
            "validity": latest.get("validity"),
            "timestamp": latest.get("timestamp"),
        },
        "air_sensor_ssh": ssh_check,
        "archive_sync": archive_status,
        "disk_usage": {
            "local": {**local_disk, "ok": local_disk_ok},
            "air_sensor": remote_disk,
        },
        "files": file_checks,
        "checks": checks,
    }

    if args.jsonl:
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    elif args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"node: {result['node']}")
        print(f"generation: {result['hardware_generation']}")
        print(f"ok: {result['ok']}")
        print(
            "latest: "
            f"ok={latest_ok} age={latest_age} event={result['latest_state']['event_signature']} "
            f"validity={result['latest_state']['validity']}"
        )
        print(f"raw_samples: ok={raw_ok} modified_age={raw_age}")
        print(f"air_sensor_ssh: ok={ssh_check.get('ok')} stderr={ssh_check.get('stderr')}")
        print(
            "archive_sync: "
            f"ok={archive_status.get('ok')} age={archive_status.get('age_seconds')} "
            f"target={archive_status.get('target')} error={archive_status.get('error')}"
        )
        print(
            "local_disk: "
            f"used={local_disk['used_percent']}% free={local_disk['free_bytes']} path={local_disk['path']}"
        )
        print(f"air_sensor_disk: ok={remote_disk.get('ok')} output={remote_disk.get('stdout')}")
        for item in file_checks:
            print(
                f"{item['name']}: ok={item['ok']} exists={item['exists']} "
                f"size={item['size_bytes']} path={item['path']}"
            )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
