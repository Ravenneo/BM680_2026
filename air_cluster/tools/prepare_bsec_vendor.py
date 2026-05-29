#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_VENDOR_DIR = SCRIPT_DIR / "vendor" / "bsec"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def interesting(path: Path) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    return (
        suffix in (".a", ".so", ".h", ".c", ".cpp", ".txt", ".pdf", ".config", ".json")
        or "bsec" in name
        or "bme69" in name
        or "bme68" in name
        or "raspberry" in name
        or "linux" in name
        or "arm" in name
    )


def classify(path: Path) -> str:
    lowered = str(path).lower()
    if path.suffix.lower() in (".a", ".so"):
        return "library"
    if path.suffix.lower() in (".h", ".hpp"):
        return "header"
    if "config" in lowered:
        return "config"
    if "example" in lowered:
        return "example"
    if path.suffix.lower() == ".pdf":
        return "document"
    return "other"


def score_platform(path: Path) -> list[str]:
    lowered = str(path).lower()
    hits: list[str] = []
    for token in ("raspberry", "linux", "arm-linux", "aarch64", "armv8", "armv7", "armv6", "gnueabihf"):
        if token in lowered:
            hits.append(token)
    return hits


def inventory(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if not interesting(path):
            continue
        rel = path.relative_to(root)
        files.append(
            {
                "path": str(rel),
                "kind": classify(path),
                "size_bytes": path.stat().st_size,
                "platform_hints": score_platform(rel),
            }
        )

    libraries = [item for item in files if item["kind"] == "library"]
    headers = [item for item in files if item["kind"] == "header"]
    likely_pi = [item for item in libraries if item["platform_hints"]]
    return {
        "schema_version": "air_cluster.bsec_vendor_inventory.v1",
        "timestamp": now_iso(),
        "root": str(root),
        "file_count": len(files),
        "libraries": libraries,
        "headers": headers,
        "likely_raspberry_pi_libraries": likely_pi,
        "configs": [item for item in files if item["kind"] == "config"],
        "documents": [item for item in files if item["kind"] == "document"],
        "examples": [item for item in files if item["kind"] == "example"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip_path", help="official Bosch BSEC ZIP accepted/downloaded by the user")
    parser.add_argument("--vendor-dir", default=str(DEFAULT_VENDOR_DIR))
    parser.add_argument("--clean", action="store_true", help="remove previous extracted package first")
    args = parser.parse_args()

    zip_path = Path(args.zip_path).expanduser().resolve()
    vendor_dir = Path(args.vendor_dir).expanduser().resolve()
    if not zip_path.exists():
        raise SystemExit(f"ZIP not found: {zip_path}")
    if not zipfile.is_zipfile(zip_path):
        raise SystemExit(f"not a ZIP file: {zip_path}")

    extract_dir = vendor_dir / "bosch_package"
    if args.clean and extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_dir)

    report = inventory(extract_dir)
    report["source_zip_name"] = zip_path.name
    report["source_zip_size_bytes"] = zip_path.stat().st_size

    out_path = vendor_dir / "INVENTORY.json"
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["likely_raspberry_pi_libraries"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
