#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.yaml"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def archive_paths(config_path: Path, cfg: dict[str, Any]) -> dict[str, Path]:
    base = config_path.parent
    paths = cfg["paths"]
    return {
        "raw_samples": resolve_path(base, paths["raw_samples"]),
        "hourly_batches": resolve_path(base, paths["hourly_batches"]),
        "daily_summary": resolve_path(base, paths["daily_summary"]),
        "latest_state": resolve_path(base, paths["latest_state"]),
        "baseline_state": resolve_path(base, paths.get("baseline_state", "data/baseline_state.json")),
        "archive_status": resolve_path(base, paths["archive_status"]),
        "archive_log": resolve_path(base, paths["archive_log"]),
    }


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
        "ConnectTimeout=10",
    ]
    key = archive.get("ssh_key")
    if key:
        key_path = os.path.expanduser(str(key))
        if Path(key_path).exists():
            options.extend(["-i", key_path])
    return options


def ssh_transport(archive: dict[str, Any]) -> str:
    return "ssh " + " ".join(ssh_options(archive))


def run_command(cmd: list[str], timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def run_command_with_retries(
    cmd: list[str],
    *,
    timeout: float,
    attempts: int = 3,
    backoff_seconds: float = 5.0,
) -> subprocess.CompletedProcess[str]:
    last_result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            result = run_command(cmd, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
            result = subprocess.CompletedProcess(
                cmd,
                124,
                stdout=(stdout or ""),
                stderr=(stderr or f"timed out after {timeout:.0f}s"),
            )
        last_result = result
        if result.returncode == 0:
            return result
        if attempt < attempts:
            error = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            logging.warning(
                "command failed on attempt %s/%s; retrying in %.1fs: %s",
                attempt,
                attempts,
                backoff_seconds,
                error,
            )
            time.sleep(backoff_seconds)
    assert last_result is not None
    return last_result


def ensure_remote_dir(archive: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    remote_dir = archive["remote_dir"]
    cmd = [
        "ssh",
        *ssh_options(archive),
        ssh_target(archive),
        f"mkdir -p {remote_dir}",
    ]
    return run_command_with_retries(cmd, timeout=30, attempts=3, backoff_seconds=5)


def rsync_file(
    archive: dict[str, Any],
    local_path: Path,
    append_mode: bool,
) -> subprocess.CompletedProcess[str] | None:
    if not local_path.exists():
        logging.info("skip missing %s", local_path)
        return None

    remote = f"{ssh_target(archive)}:{archive['remote_dir'].rstrip('/')}/{local_path.name}"
    cmd = [
        "rsync",
        "-az",
        "--partial",
        "--no-owner",
        "--no-group",
        "-e",
        ssh_transport(archive),
    ]
    if append_mode:
        cmd.append("--append-verify")
    cmd.extend([str(local_path), remote])
    return run_command_with_retries(cmd, timeout=180, attempts=3, backoff_seconds=5)


def write_status(
    path: Path,
    ok: bool,
    started_at: str,
    archive: dict[str, Any],
    file_results: list[dict[str, Any]],
    error: str | None = None,
) -> None:
    status = {
        "schema_version": "air_cluster.archive_status.v1",
        "ok": ok,
        "started_at": started_at,
        "finished_at": now_iso(),
        "target": f"{ssh_target(archive)}:{archive['remote_dir'].rstrip('/')}/",
        "file_results": file_results,
        "error": error,
    }
    atomic_write_json(path, status)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    cfg = load_config(config_path)
    paths = archive_paths(config_path, cfg)
    paths["archive_log"].parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(paths["archive_log"], encoding="utf-8"),
        ],
    )

    archive = cfg.get("archive", {})
    started_at = now_iso()
    if not archive.get("enabled", True):
        logging.info("archive push disabled in config")
        write_status(paths["archive_status"], True, started_at, archive, [], "disabled")
        return 0

    logging.info("archive push target: %s:%s", ssh_target(archive), archive["remote_dir"])
    file_results: list[dict[str, Any]] = []

    try:
        mkdir_result = ensure_remote_dir(archive)
        if mkdir_result.returncode != 0:
            error = mkdir_result.stderr.strip() or mkdir_result.stdout.strip()
            logging.error("remote directory setup failed: %s", error)
            write_status(paths["archive_status"], False, started_at, archive, file_results, error)
            return 1

        for name, local_path, append_mode in [
            ("raw_samples", paths["raw_samples"], True),
            ("hourly_batches", paths["hourly_batches"], True),
            ("daily_summary", paths["daily_summary"], True),
            ("latest_state", paths["latest_state"], False),
            ("baseline_state", paths["baseline_state"], False),
        ]:
            before = time.time()
            result = rsync_file(archive, local_path, append_mode)
            if result is None:
                file_results.append(
                    {"name": name, "path": str(local_path), "ok": True, "skipped": True}
                )
                continue

            ok = result.returncode == 0
            duration = round(time.time() - before, 3)
            file_results.append(
                {
                    "name": name,
                    "path": str(local_path),
                    "ok": ok,
                    "append_mode": append_mode,
                    "returncode": result.returncode,
                    "duration_seconds": duration,
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                }
            )
            if ok:
                logging.info("synced %s in %.3fs", local_path.name, duration)
            else:
                logging.error("failed syncing %s: %s", local_path.name, result.stderr.strip())

        ok = all(item.get("ok") for item in file_results)
        write_status(paths["archive_status"], ok, started_at, archive, file_results)
        return 0 if ok else 1
    except Exception as exc:
        logging.exception("archive push failed")
        write_status(paths["archive_status"], False, started_at, archive, file_results, str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
