#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import logging
import math
import os
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.yaml"
SCHEMA_VERSION = "air_cluster.sample.v1"
LOGGER_VERSION = "2026.05.29"
BASELINE_STATE_VERSION = "air_cluster.baseline_state.v1"
MIN_PRESSURE_HPA = 300.0
MAX_PRESSURE_HPA = 1200.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            yaml = importlib.import_module("yaml")
        except ModuleNotFoundError as exc:
            raise SystemExit(
                f"{path} is not JSON-compatible and PyYAML is not installed."
            ) from exc
        return yaml.safe_load(text)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def rel_delta_pct(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline in (None, 0):
        return None
    return ((float(value) - float(baseline)) / float(baseline)) * 100.0


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class RollingBaseline:
    def __init__(self, alpha: float, min_samples: int, max_update_delta_pct: float):
        self.alpha = alpha
        self.min_samples = min_samples
        self.max_update_delta_pct = abs(max_update_delta_pct)
        self.count = 0
        self.value: float | None = None
        self.seed_values: list[float] = []

    def update(self, observed: float | None) -> float | None:
        if observed is None or not math.isfinite(float(observed)):
            return self.value

        observed = float(observed)
        self.count += 1

        if self.value is None:
            self.seed_values.append(observed)
            if len(self.seed_values) >= self.min_samples:
                self.value = float(statistics.median(self.seed_values))
                self.seed_values.clear()
            return self.value

        delta = rel_delta_pct(observed, self.value)
        if delta is None or abs(delta) <= self.max_update_delta_pct:
            self.value = ((1.0 - self.alpha) * self.value) + (self.alpha * observed)
        return self.value

    def restore(self, state: dict[str, Any]) -> None:
        value = state.get("value")
        if value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = None
        if value is not None and math.isfinite(value):
            self.value = value
            try:
                count = int(state.get("count", self.min_samples))
            except (TypeError, ValueError):
                count = self.min_samples
            self.count = max(count, self.min_samples)

        seed_values = state.get("seed_values", [])
        if isinstance(seed_values, list):
            self.seed_values = [
                float(item)
                for item in seed_values[-self.min_samples :]
                if isinstance(item, (int, float)) and math.isfinite(float(item))
            ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "count": self.count,
            "ready": self.ready,
            "seed_values": self.seed_values,
        }

    @property
    def ready(self) -> bool:
        return self.value is not None and self.count >= self.min_samples


def load_baseline_state(path: Path, baselines: dict[str, RollingBaseline]) -> None:
    if not path.exists():
        return
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logging.warning("failed to load baseline state from %s: %s", path, exc)
        return
    if state.get("schema_version") != BASELINE_STATE_VERSION:
        logging.warning("ignoring unsupported baseline state version in %s", path)
        return

    saved = state.get("baselines", {})
    if not isinstance(saved, dict):
        return
    restored = 0
    for key, baseline in baselines.items():
        item = saved.get(key)
        if isinstance(item, dict):
            before = baseline.value
            baseline.restore(item)
            if baseline.value is not None and baseline.value != before:
                restored += 1
    if restored:
        logging.info("restored %s rolling baselines from %s", restored, path)


def save_baseline_state(path: Path, baselines: dict[str, RollingBaseline]) -> None:
    payload = {
        "schema_version": BASELINE_STATE_VERSION,
        "timestamp": now_iso(),
        "baselines": {key: baseline.as_dict() for key, baseline in baselines.items()},
    }
    atomic_write_json(path, payload)


class BME690Adapter:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.sensor = None
        self.module = None
        self.error: str | None = None
        self._connect()

    def _connect(self) -> None:
        try:
            try:
                module = importlib.import_module("bme690")
                sensor_class = getattr(module, "BME690")
            except ModuleNotFoundError:
                module = importlib.import_module("bme680")
                sensor_class = getattr(module, "BME680")
            self.module = module
            try:
                sensor = sensor_class(module.I2C_ADDR_PRIMARY)
            except Exception:
                sensor = sensor_class(module.I2C_ADDR_SECONDARY)

            sensor.set_humidity_oversample(module.OS_2X)
            sensor.set_pressure_oversample(module.OS_4X)
            sensor.set_temperature_oversample(module.OS_8X)
            sensor.set_filter(module.FILTER_SIZE_3)
            sensor.set_gas_status(module.ENABLE_GAS_MEAS)
            sensor.set_gas_heater_temperature(
                int(self.config.get("heater_temperature_c", 320))
            )
            sensor.set_gas_heater_duration(
                int(self.config.get("heater_duration_ms", 150))
            )
            sensor.select_gas_heater_profile(0)
            self.sensor = sensor
            self.error = None
        except Exception as exc:
            self.sensor = None
            self.error = str(exc)

    def read(self) -> tuple[dict[str, Any], str | None]:
        if self.sensor is None:
            self._connect()
        if self.sensor is None:
            return {}, self.error or "BME690 unavailable"

        try:
            if not self.sensor.get_sensor_data():
                return {"heat_stable": False}, "BME690 returned no data"
            data = self.sensor.data
            heat_stable = bool(getattr(data, "heat_stable", False))
            pressure_hpa = float(data.pressure)
            pressure_error = None
            if not MIN_PRESSURE_HPA <= pressure_hpa <= MAX_PRESSURE_HPA:
                pressure_error = f"BME690 pressure out of range: {pressure_hpa:.2f} hPa"
                heat_stable = False
            gas = float(data.gas_resistance) if heat_stable else None
            return (
                {
                    "temperature_c": float(data.temperature),
                    "humidity_pct": float(data.humidity),
                    "pressure_hpa": pressure_hpa,
                    "gas_ohms": gas,
                    "heat_stable": heat_stable,
                },
                pressure_error,
            )
        except Exception as exc:
            self.error = str(exc)
            return {}, self.error


class MICS6814Adapter:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.sensor = None
        self.error: str | None = None
        self._connect()

    def _connect(self) -> None:
        try:
            module = importlib.import_module("mics6814")
            klass = getattr(module, "MICS6814", None)
            self.sensor = klass() if klass else module
            self._set_onboard_led()
            self.error = None
        except Exception as exc:
            self.sensor = None
            self.error = str(exc)

    def _set_onboard_led(self) -> None:
        brightness = float(self.config.get("onboard_led_brightness", 0.0))
        set_brightness = getattr(self.sensor, "set_brightness", None)
        set_led = getattr(self.sensor, "set_led", None)
        if callable(set_brightness):
            set_brightness(max(0.0, min(1.0, brightness)))
        if callable(set_led):
            set_led(0, 0, 0)

    def _call_first(self, names: list[str]) -> Any:
        for name in names:
            method = getattr(self.sensor, name, None)
            if callable(method):
                return method()
        raise AttributeError(f"none of {names!r} found")

    def read(self) -> tuple[dict[str, Any], str | None]:
        if self.sensor is None:
            self._connect()
        if self.sensor is None:
            return {}, self.error or "MICS6814 unavailable"

        try:
            read_all = getattr(self.sensor, "read_all", None)
            if callable(read_all):
                values = read_all()
                if isinstance(values, dict):
                    return (
                        {
                            "reducing": _first_value(values, ["reducing", "red"]),
                            "oxidising": _first_value(values, ["oxidising", "oxidizing", "ox"]),
                            "nh3": _first_value(values, ["nh3", "ammonia"]),
                        },
                        None,
                    )
                if isinstance(values, (list, tuple)) and len(values) >= 3:
                    return (
                        {
                            "reducing": float(values[0]),
                            "oxidising": float(values[1]),
                            "nh3": float(values[2]),
                        },
                        None,
                    )

            return (
                {
                    "reducing": float(
                        self._call_first(["read_reducing", "get_reducing", "reducing"])
                    ),
                    "oxidising": float(
                        self._call_first(
                            ["read_oxidising", "read_oxidizing", "get_oxidising", "get_oxidizing", "oxidising"]
                        )
                    ),
                    "nh3": float(self._call_first(["read_nh3", "get_nh3", "nh3"])),
                },
                None,
            )
        except Exception as exc:
            self.error = str(exc)
            return {}, self.error


def _first_value(values: dict[str, Any], names: list[str]) -> float | None:
    lowered = {str(k).lower(): v for k, v in values.items()}
    for name in names:
        if name in lowered and lowered[name] is not None:
            return float(lowered[name])
    return None


@dataclass
class RunningStats:
    count: int = 0
    total: float = 0.0
    min_value: float | None = None
    max_value: float | None = None

    def add(self, value: float | None) -> None:
        if value is None:
            return
        value = float(value)
        if not math.isfinite(value):
            return
        self.count += 1
        self.total += value
        self.min_value = value if self.min_value is None else min(self.min_value, value)
        self.max_value = value if self.max_value is None else max(self.max_value, value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "avg": self.total / self.count if self.count else None,
            "min": self.min_value,
            "max": self.max_value,
        }


@dataclass
class BatchAccumulator:
    start_ts: str = field(default_factory=now_iso)
    event_counts: dict[str, int] = field(default_factory=dict)
    stats: dict[str, RunningStats] = field(default_factory=dict)
    samples: int = 0
    valid_samples: int = 0

    def add_sample(self, sample: dict[str, Any]) -> None:
        self.samples += 1
        if sample.get("validity", {}).get("status") == "OK":
            self.valid_samples += 1
        event = sample.get("event_signature", "UNKNOWN")
        self.event_counts[event] = self.event_counts.get(event, 0) + 1

        bme = sample.get("bme690", {})
        mics = sample.get("mics6814", {})
        for name, value in {
            "temperature_c": bme.get("temperature_c"),
            "humidity_pct": bme.get("humidity_pct"),
            "pressure_hpa": bme.get("pressure_hpa"),
            "gas_ohms": bme.get("gas_ohms"),
            "gas_delta_pct": bme.get("gas_delta_pct"),
            "voc_score": bme.get("voc_score"),
            "mics_reducing": mics.get("reducing"),
            "mics_oxidising": mics.get("oxidising"),
            "mics_nh3": mics.get("nh3"),
        }.items():
            self.stats.setdefault(name, RunningStats()).add(value)

    def as_record(self, node: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "air_cluster.hourly_batch.v1",
            "timestamp": now_iso(),
            "node": node["name"],
            "hardware_generation": node["hardware_generation"],
            "start_ts": self.start_ts,
            "end_ts": now_iso(),
            "samples": self.samples,
            "valid_samples": self.valid_samples,
            "event_counts": self.event_counts,
            "stats": {name: stats.as_dict() for name, stats in self.stats.items()},
        }


def make_daily_summary(hourly_records: list[dict[str, Any]], node: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    total_samples = 0
    valid_samples = 0
    for record in hourly_records:
        total_samples += int(record.get("samples", 0))
        valid_samples += int(record.get("valid_samples", 0))
        for event, count in record.get("event_counts", {}).items():
            counts[event] = counts.get(event, 0) + int(count)

    return {
        "schema_version": "air_cluster.daily_summary.v1",
        "timestamp": now_iso(),
        "node": node["name"],
        "hardware_generation": node["hardware_generation"],
        "date_utc": datetime.now(timezone.utc).date().isoformat(),
        "hourly_batches": len(hourly_records),
        "samples": total_samples,
        "valid_samples": valid_samples,
        "event_counts": counts,
    }


def voc_score_from_delta(delta: float | None, warmup: bool) -> float | None:
    if warmup or delta is None:
        return None
    quality = (15.0 - delta) / 35.0
    return clamp(100.0 * (1.0 - clamp(quality, 0.0, 1.0)), 0.0, 100.0)


def classify_event(
    warmup: bool,
    errors: list[str],
    deltas: dict[str, float | None],
    thresholds: dict[str, Any],
) -> str:
    if errors and len(errors) >= 2:
        return "SENSOR_ERROR"
    if warmup:
        return "SENSOR_WARMUP"

    events: list[str] = []
    voc_delta = deltas.get("bme690_gas_pct")
    if voc_delta is not None and voc_delta <= float(thresholds.get("voc_delta_pct", -15.0)):
        events.append("VOC_EVENT")
    if _above_abs(deltas.get("mics_reducing_pct"), thresholds.get("mics_reducing_delta_pct", 20.0)):
        events.append("REDUCING_EVENT")
    if _above_abs(deltas.get("mics_oxidising_pct"), thresholds.get("mics_oxidising_delta_pct", 20.0)):
        events.append("OXIDISING_EVENT")
    if _above_abs(deltas.get("mics_nh3_pct"), thresholds.get("mics_nh3_delta_pct", 20.0)):
        events.append("NH3_EVENT")

    if len(events) >= int(thresholds.get("mixed_event_count", 2)):
        return "MIXED_EVENT"
    return events[0] if events else "CLEAN"


def _has_sensor_error(errors: list[str], sensor_name: str) -> bool:
    prefix = f"{sensor_name}:"
    return any(error.startswith(prefix) for error in errors)


def classify_bme690_event(
    warmup: bool,
    errors: list[str],
    deltas: dict[str, float | None],
    thresholds: dict[str, Any],
) -> str:
    if _has_sensor_error(errors, "bme690"):
        return "SENSOR_ERROR"
    if warmup:
        return "SENSOR_WARMUP"
    voc_delta = deltas.get("bme690_gas_pct")
    if voc_delta is not None and voc_delta <= float(thresholds.get("voc_delta_pct", -15.0)):
        return "VOC_EVENT"
    return "CLEAN"


def classify_air_quality_state(
    warmup: bool,
    bme690_event: str,
    deltas: dict[str, float | None],
) -> str:
    if warmup or bme690_event in ("SENSOR_WARMUP", "SENSOR_ERROR"):
        return "UNKNOWN"

    gas_delta = deltas.get("bme690_gas_pct")
    if gas_delta is None:
        return "UNKNOWN"
    if gas_delta <= -30.0:
        return "BAD"
    if gas_delta <= -15.0:
        return "VENTILATE"
    if gas_delta <= -5.0:
        return "OK"
    return "GOOD"


def classify_gas_signature(
    errors: list[str],
    deltas: dict[str, float | None],
    thresholds: dict[str, Any],
) -> str:
    if _has_sensor_error(errors, "mics6814"):
        return "SENSOR_ERROR"

    events: list[str] = []
    if _above_abs(deltas.get("mics_reducing_pct"), thresholds.get("mics_reducing_delta_pct", 20.0)):
        events.append("REDUCING_EVENT")
    if _above_abs(deltas.get("mics_oxidising_pct"), thresholds.get("mics_oxidising_delta_pct", 20.0)):
        events.append("OXIDISING_EVENT")
    if _above_abs(deltas.get("mics_nh3_pct"), thresholds.get("mics_nh3_delta_pct", 20.0)):
        events.append("NH3_EVENT")

    if len(events) >= int(thresholds.get("mixed_event_count", 2)):
        return "MIXED_EVENT"
    return events[0] if events else "CLEAN"


def _above_abs(value: float | None, threshold: Any) -> bool:
    return value is not None and abs(float(value)) >= abs(float(threshold))


def confidence(
    errors: list[str],
    warmup: bool,
    baseline_ready_count: int,
    baseline_required_count: int,
) -> float:
    if len(errors) >= 2:
        return 0.0
    score = 1.0
    if errors:
        score -= 0.35
    if warmup:
        score -= 0.35
    if baseline_ready_count < baseline_required_count:
        score -= 0.1 * (baseline_required_count - baseline_ready_count)
    return clamp(score, 0.0, 1.0)


def resolve_path(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def build_sample(
    cfg: dict[str, Any],
    started_at: float,
    baselines: dict[str, RollingBaseline],
    bme_reading: dict[str, Any],
    mics_reading: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    node = cfg["node"]
    baseline_cfg = cfg.get("baselines", {})
    warmup = (time.time() - started_at) < float(cfg["sampling"].get("warmup_seconds", 600))

    observed = {
        "bme690_gas_ohms": bme_reading.get("gas_ohms"),
        "mics_reducing": mics_reading.get("reducing"),
        "mics_oxidising": mics_reading.get("oxidising"),
        "mics_nh3": mics_reading.get("nh3"),
    }
    baseline_reference = {key: baselines[key].value for key in observed}
    baseline_values: dict[str, float | None] = {}
    for key, value in observed.items():
        baseline_values[key] = baselines[key].update(value)

    deltas = {
        "bme690_gas_pct": rel_delta_pct(observed["bme690_gas_ohms"], baseline_reference["bme690_gas_ohms"]),
        "mics_reducing_pct": rel_delta_pct(observed["mics_reducing"], baseline_reference["mics_reducing"]),
        "mics_oxidising_pct": rel_delta_pct(observed["mics_oxidising"], baseline_reference["mics_oxidising"]),
        "mics_nh3_pct": rel_delta_pct(observed["mics_nh3"], baseline_reference["mics_nh3"]),
    }
    required_keys = [
        key
        for key, value in observed.items()
        if value is not None or baselines[key].count > 0 or baselines[key].value is not None
    ]
    baseline_ready_count = sum(1 for key in required_keys if baselines[key].ready)
    baseline_required_count = len(required_keys)
    if baseline_required_count == 0 or baseline_ready_count < baseline_required_count:
        warmup = True

    thresholds = cfg.get("thresholds", {})
    bme690_event = classify_bme690_event(warmup, errors, deltas, thresholds)
    air_quality_state = classify_air_quality_state(warmup, bme690_event, deltas)
    gas_signature = classify_gas_signature(errors, deltas, thresholds)
    if bme690_event == "SENSOR_ERROR" and gas_signature == "SENSOR_ERROR":
        event = "SENSOR_ERROR"
    elif warmup:
        event = "SENSOR_WARMUP"
    elif bme690_event == "VOC_EVENT":
        event = "VOC_EVENT"
    else:
        event = gas_signature
    conf = confidence(errors, warmup, baseline_ready_count, baseline_required_count)
    status = "SENSOR_ERROR" if len(errors) >= 2 else "WARMUP" if warmup else "PARTIAL" if errors else "OK"
    led_base_state = "SENSOR_WARMUP" if warmup else air_quality_state

    return {
        "schema_version": SCHEMA_VERSION,
        "logger_version": LOGGER_VERSION,
        "timestamp": now_iso(),
        "node": node["name"],
        "hardware_generation": node["hardware_generation"],
        "bme690": {
            "temperature_c": bme_reading.get("temperature_c"),
            "humidity_pct": bme_reading.get("humidity_pct"),
            "pressure_hpa": bme_reading.get("pressure_hpa"),
            "gas_ohms": bme_reading.get("gas_ohms"),
            "gas_baseline_ohms": baseline_values["bme690_gas_ohms"],
            "gas_delta_pct": deltas["bme690_gas_pct"],
            "gas_baseline_ready": baselines["bme690_gas_ohms"].ready,
            "voc_score": voc_score_from_delta(deltas["bme690_gas_pct"], warmup),
            "heat_stable": bme_reading.get("heat_stable"),
        },
        "mics6814": {
            "reducing": mics_reading.get("reducing"),
            "oxidising": mics_reading.get("oxidising"),
            "nh3": mics_reading.get("nh3"),
            "note": "Qualitative relative channels only; not calibrated ppm.",
        },
        "rolling_baselines": baseline_values,
        "delta_percentages": deltas,
        "event_signature": event,
        "air_quality_state": air_quality_state,
        "bme690_event": bme690_event,
        "gas_signature": gas_signature,
        "led_base_state": led_base_state,
        "led_accent_state": gas_signature,
        "validity": {
            "status": status,
            "confidence": conf,
            "warmup": warmup,
            "baseline_ready_count": baseline_ready_count,
            "baseline_required_count": baseline_required_count,
            "errors": errors,
            "baseline_policy": {
                "ema_alpha": baseline_cfg.get("ema_alpha"),
                "min_samples": baseline_cfg.get("min_samples"),
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    config_path = Path(args.config).resolve()
    cfg = load_config(config_path)
    base_dir = config_path.parent
    paths = cfg["paths"]
    data_dir = resolve_path(base_dir, paths["data_dir"])
    raw_path = resolve_path(base_dir, paths["raw_samples"])
    hourly_path = resolve_path(base_dir, paths["hourly_batches"])
    daily_path = resolve_path(base_dir, paths["daily_summary"])
    latest_path = resolve_path(base_dir, paths["latest_state"])
    baseline_state_path = resolve_path(base_dir, paths.get("baseline_state", "data/baseline_state.json"))
    data_dir.mkdir(parents=True, exist_ok=True)

    bme = BME690Adapter(cfg.get("sensors", {}).get("bme690", {}))
    mics = MICS6814Adapter(cfg.get("sensors", {}).get("mics6814", {}))

    baseline_cfg = cfg.get("baselines", {})
    baselines = {
        key: RollingBaseline(
            alpha=float(baseline_cfg.get("ema_alpha", 0.01)),
            min_samples=int(baseline_cfg.get("min_samples", 60)),
            max_update_delta_pct=float(baseline_cfg.get("max_update_delta_pct", 35.0)),
        )
        for key in ("bme690_gas_ohms", "mics_reducing", "mics_oxidising", "mics_nh3")
    }
    load_baseline_state(baseline_state_path, baselines)

    interval = float(cfg["sampling"].get("sample_interval_seconds", 10))
    batch_seconds = float(cfg["sampling"].get("hourly_batch_seconds", 3600))
    baseline_save_interval = max(1.0, float(baseline_cfg.get("persist_interval_seconds", 60)))
    last_baseline_save_at = 0.0
    started_at = time.time()
    batch_started_at = time.time()
    batch = BatchAccumulator()
    hourly_today: list[dict[str, Any]] = []
    current_day = datetime.now(timezone.utc).date()

    logging.info("Air-Station logger started; writing to %s", data_dir)
    while True:
        loop_started = time.time()
        errors: list[str] = []

        bme_reading, bme_error = bme.read()
        if bme_error:
            errors.append(f"bme690: {bme_error}")

        mics_reading, mics_error = mics.read()
        if mics_error:
            errors.append(f"mics6814: {mics_error}")

        try:
            sample = build_sample(cfg, started_at, baselines, bme_reading, mics_reading, errors)
            append_jsonl(raw_path, sample)
            atomic_write_json(latest_path, sample)
            if time.time() - last_baseline_save_at >= baseline_save_interval:
                save_baseline_state(baseline_state_path, baselines)
                last_baseline_save_at = time.time()
            batch.add_sample(sample)

            if time.time() - batch_started_at >= batch_seconds:
                hourly = batch.as_record(cfg["node"])
                append_jsonl(hourly_path, hourly)
                hourly_today.append(hourly)
                batch = BatchAccumulator()
                batch_started_at = time.time()

            today = datetime.now(timezone.utc).date()
            if today != current_day:
                if hourly_today:
                    append_jsonl(daily_path, make_daily_summary(hourly_today, cfg["node"]))
                hourly_today = []
                current_day = today
        except Exception:
            logging.exception("failed to write sample")

        sleep_for = max(0.5, interval - (time.time() - loop_started))
        time.sleep(sleep_for)


if __name__ == "__main__":
    raise SystemExit(main())
