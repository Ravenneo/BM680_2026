#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import logging
import math
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = SCRIPT_DIR / "config.yaml"


class MatrixRecoveryExhausted(RuntimeError):
    pass


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


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def read_latest(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def parse_timestamp(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def state_age_seconds(state: dict[str, Any]) -> float | None:
    ts = parse_timestamp(state.get("timestamp"))
    if ts is None:
        return None
    return max(0.0, time.time() - ts)


def base_rgb(base_state: str, t: float) -> tuple[int, int, int]:
    palette = {
        "GOOD": (28, 145, 74),
        "OK": (34, 135, 82),
        "VENTILATE": (170, 132, 32),
        "BAD": (185, 62, 28),
        "SENSOR_ERROR": (138, 32, 24),
        "UNKNOWN": (36, 72, 86),
        "SENSOR_WARMUP": (128, 92, 34),
        "STALE": (32, 50, 60),
    }
    r, g, b = palette.get(base_state, palette["UNKNOWN"])
    if base_state == "SENSOR_ERROR":
        pulse = 0.72 + 0.28 * (0.5 + 0.5 * math.sin(t * 0.12))
        return int(r * pulse), int(g * pulse), int(b * pulse)
    if base_state == "UNKNOWN":
        blue_drift = 0.35 + 0.25 * (0.5 + 0.5 * math.sin(t * 0.09))
        return int(r * (1.0 - blue_drift * 0.45)), int(g), int(b * (1.0 + blue_drift * 0.38))
    if base_state == "SENSOR_WARMUP":
        heat = 0.74 + 0.26 * (0.5 + 0.5 * math.sin(t * 0.09))
        return int(r * heat), int(g * heat), int(b * (0.86 + 0.14 * heat))
    if base_state == "BAD":
        heat = 0.88 + 0.12 * (0.5 + 0.5 * math.sin(t * 0.07))
        return int(r * heat), int(g * heat), int(b * heat)
    return r, g, b


def derived_air_quality_state(state: dict[str, Any]) -> str:
    explicit = state.get("led_base_state") or state.get("air_quality_state")
    if explicit:
        return str(explicit)

    validity = state.get("validity", {}) if isinstance(state.get("validity"), dict) else {}
    if validity.get("warmup"):
        return "UNKNOWN"
    if validity.get("status") == "SENSOR_ERROR":
        return "SENSOR_ERROR"

    deltas = state.get("delta_percentages", {}) if isinstance(state.get("delta_percentages"), dict) else {}
    gas_delta = number(deltas.get("bme690_gas_pct"))
    if gas_delta is None:
        return "UNKNOWN"
    if gas_delta <= -30.0:
        return "BAD"
    if gas_delta <= -15.0:
        return "VENTILATE"
    if gas_delta <= -5.0:
        return "OK"
    return "GOOD"


def derived_gas_signature(state: dict[str, Any]) -> str:
    explicit = state.get("led_accent_state") or state.get("gas_signature")
    if explicit:
        return str(explicit)
    event = str(state.get("event_signature") or "CLEAN")
    if event in ("REDUCING_EVENT", "OXIDISING_EVENT", "NH3_EVENT", "MIXED_EVENT", "SENSOR_ERROR"):
        return event
    return "CLEAN"


def blend_color(
    base: tuple[int, int, int],
    accent: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    amount = clamp(amount, 0.0, 1.0)
    return (
        int(lerp(base[0], accent[0], amount)),
        int(lerp(base[1], accent[1], amount)),
        int(lerp(base[2], accent[2], amount)),
    )


class Matrix:
    def __init__(self, brightness: float):
        module = importlib.import_module("rgbmatrix5x5")
        klass = getattr(module, "RGBMatrix5x5")
        self.matrix = klass()
        self.matrix.set_clear_on_exit()
        self.matrix.set_brightness(brightness)
        self.width = self.matrix.width
        self.height = self.matrix.height

    def clear(self) -> None:
        self.matrix.clear()

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int, brightness: float = 1.0) -> None:
        self.matrix.set_pixel(x, y, r, g, b, brightness=brightness)

    def show(self) -> None:
        self.matrix.show()


class PatternEngine:
    def __init__(self, matrix: Matrix, cfg: dict[str, Any]):
        self.matrix = matrix
        self.min_brightness = float(cfg.get("min_brightness", 0.015))
        self.max_brightness = float(cfg.get("max_brightness", 0.18))
        self.random_decay = clamp(float(cfg.get("random_decay", 0.92)), 0.70, 0.995)
        self.wobble = float(cfg.get("organic_wobble", 0.08))
        self.rnd = random.Random()
        self.energy = [
            [self.rnd.uniform(0.0, 0.18) for _ in range(matrix.width)]
            for _ in range(matrix.height)
        ]
        self.target_energy = [
            [self.rnd.uniform(0.0, 0.12) for _ in range(matrix.width)]
            for _ in range(matrix.height)
        ]

    def event_density(self, accent_state: str) -> float:
        return {
            "CLEAN": 0.055,
            "REDUCING_EVENT": 0.065,
            "OXIDISING_EVENT": 0.065,
            "NH3_EVENT": 0.065,
            "MIXED_EVENT": 0.095,
            "SENSOR_ERROR": 0.025,
        }.get(accent_state, 0.045)

    def update_energy(self, accent_state: str, base_state: str) -> None:
        density = self.event_density(accent_state)
        if accent_state == "MIXED_EVENT":
            ignition_high = 0.36
        elif accent_state == "SENSOR_ERROR":
            ignition_high = 0.16
        elif base_state == "BAD":
            ignition_high = 0.30
        else:
            ignition_high = 0.34

        for y in range(self.matrix.height):
            for x in range(self.matrix.width):
                target = self.target_energy[y][x] * self.random_decay
                if self.rnd.random() < density:
                    target += self.rnd.uniform(0.05, ignition_high)
                if self.rnd.random() < 0.08:
                    target += self.rnd.uniform(0.0, 0.045)
                target = clamp(target, 0.0, 0.72)
                self.target_energy[y][x] = target
                self.energy[y][x] = lerp(self.energy[y][x], target, 0.18)

    def accent_for_pixel(
        self,
        accent_state: str,
        state: dict[str, Any],
        x: int,
        y: int,
        t: float,
    ) -> tuple[tuple[int, int, int] | None, float]:
        w, h = self.matrix.width, self.matrix.height
        deltas = (
            state.get("delta_percentages", {})
            if isinstance(state.get("delta_percentages"), dict)
            else {}
        )
        try:
            reducing_raw = deltas.get("mics_reducing_pct")
            oxidising_raw = deltas.get("mics_oxidising_pct")
            nh3_raw = deltas.get("mics_nh3_pct")
            reducing = abs(float(reducing_raw)) if reducing_raw is not None else None
            oxidising = abs(float(oxidising_raw)) if oxidising_raw is not None else None
            nh3 = abs(float(nh3_raw)) if nh3_raw is not None else None
        except (TypeError, ValueError):
            reducing = oxidising = nh3 = None

        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(t * 0.16))
        central = abs(x - w // 2) + abs(y - h // 2) <= 1
        corner_or_diag = (x in (0, w - 1) and y in (0, h - 1)) or x == y or x == w - 1 - y
        lower_edge = y == h - 1 or (y == h - 2 and x in (1, w - 2))

        def channel_amount(value: float | None, scale: float, maximum: float) -> float:
            if value is None:
                return 0.0
            return clamp(0.08 + (value / scale), 0.08, maximum) * pulse

        if accent_state == "SENSOR_ERROR" and corner_or_diag:
            slow_pulse = 0.20 + 0.35 * (0.5 + 0.5 * math.sin(t * 0.045))
            return (130, 32, 30), slow_pulse
        if central and reducing is not None:
            strength = channel_amount(reducing, 55.0, 0.62)
            if accent_state not in ("REDUCING_EVENT", "MIXED_EVENT"):
                strength *= 0.58
            return (190, 44, 34), strength
        if corner_or_diag and oxidising is not None:
            strength = channel_amount(oxidising, 70.0, 0.58)
            if accent_state not in ("OXIDISING_EVENT", "MIXED_EVENT"):
                strength *= 0.58
            return (215, 58, 205), strength
        if lower_edge and nh3 is not None:
            strength = channel_amount(nh3, 55.0, 0.56)
            if accent_state not in ("NH3_EVENT", "MIXED_EVENT"):
                strength *= 0.58
            return (165, 150, 38), strength
        return None, 0.0

    def draw(self, base_state: str, accent_state: str, state: dict[str, Any], t: float) -> None:
        self.update_energy(accent_state, base_state)
        base = base_rgb(base_state, t)
        validity = state.get("validity", {}) if isinstance(state.get("validity"), dict) else {}
        confidence = clamp(float(validity.get("confidence", 0.35) or 0.35), 0.0, 1.0)
        w, h = self.matrix.width, self.matrix.height

        for y in range(h):
            for x in range(w):
                organic = 0.80 + self.wobble * math.sin(t * 0.31 + x * 1.17 + y * 0.73)
                ember = clamp(self.energy[y][x] * organic, 0.0, 1.0)

                if base_state == "SENSOR_WARMUP":
                    breathe = 0.50 + 0.50 * (0.5 + 0.5 * math.sin(t * 0.24))
                    ember = max(ember, 0.18 + 0.45 * breathe)
                elif base_state == "BAD":
                    ember = max(ember, 0.12 + 0.16 * (0.5 + 0.5 * math.sin(t * 0.06)))
                elif base_state == "STALE":
                    ember = max(ember * 0.65, 0.045)

                intensity = lerp(
                    self.min_brightness,
                    self.max_brightness,
                    clamp(ember * lerp(0.62, 1.0, confidence), 0.0, 1.0),
                )
                if base_state == "SENSOR_WARMUP":
                    intensity = max(intensity, 0.18 + 0.22 * (0.5 + 0.5 * math.sin(t * 0.24)))
                pixel_color = base
                accent, amount = self.accent_for_pixel(accent_state, state, x, y, t)
                if accent is not None:
                    pixel_color = blend_color(pixel_color, accent, amount)
                    intensity = max(
                        intensity,
                        lerp(self.min_brightness, self.max_brightness, clamp(amount, 0.0, 1.0)),
                    )

                self.matrix.set_pixel(
                    x,
                    y,
                    int(clamp(pixel_color[0], 0, 255)),
                    int(clamp(pixel_color[1], 0, 255)),
                    int(clamp(pixel_color[2], 0, 255)),
                    brightness=clamp(intensity, 0.0, 1.0),
                )
        self.matrix.show()


def record_failure(
    failures: list[float],
    *,
    window_seconds: float,
    restart_after_failures: int,
    reason: str,
) -> None:
    now = time.time()
    failures[:] = [ts for ts in failures if now - ts <= window_seconds]
    failures.append(now)
    logging.warning(
        "RGB Matrix recovery failure %s/%s within %.0fs: %s",
        len(failures),
        restart_after_failures,
        window_seconds,
        reason,
    )
    if len(failures) >= restart_after_failures:
        raise MatrixRecoveryExhausted(
            f"RGB Matrix recovery exhausted after {len(failures)} failures in {window_seconds:.0f}s: {reason}"
        )


def quiesce_matrix(matrix: Matrix | None) -> None:
    if matrix is None:
        return
    try:
        matrix.clear()
        matrix.show()
    except Exception:
        logging.debug("failed to quiesce RGB Matrix", exc_info=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    config_path = Path(args.config).resolve()
    cfg = load_config(config_path)
    latest_path = resolve_path(config_path.parent, cfg["paths"]["latest_state"])
    led_cfg = cfg.get("led", {})
    frame_interval = float(led_cfg.get("frame_interval_seconds", 0.35))
    stale_after = float(led_cfg.get("stale_after_seconds", 120.0))
    reinit_interval = max(0.0, float(led_cfg.get("reinit_interval_seconds", 600.0)))
    init_backoff = max(0.2, float(led_cfg.get("init_backoff_seconds", 5.0)))
    post_init_settle = max(0.0, float(led_cfg.get("post_init_settle_seconds", 0.15)))
    failure_window = max(5.0, float(led_cfg.get("failure_window_seconds", 90.0)))
    restart_after_failures = max(1, int(led_cfg.get("restart_after_failures", 3)))

    matrix: Matrix | None = None
    engine: PatternEngine | None = None
    initialized_at = 0.0
    last_state: tuple[str, str, bool] | None = None
    recovery_failures: list[float] = []

    while True:
        if matrix is None:
            try:
                matrix = Matrix(float(led_cfg.get("brightness", 0.45)))
                engine = PatternEngine(matrix, led_cfg)
                initialized_at = time.time()
                last_state = None
                recovery_failures.clear()
                logging.info("RGB Matrix 5x5 initialized")
                if post_init_settle > 0.0:
                    time.sleep(post_init_settle)
            except Exception as exc:
                try:
                    record_failure(
                        recovery_failures,
                        window_seconds=failure_window,
                        restart_after_failures=restart_after_failures,
                        reason=f"init failed: {exc}",
                    )
                except MatrixRecoveryExhausted:
                    logging.exception("RGB Matrix recovery exhausted during initialization")
                    raise
                logging.warning("RGB Matrix unavailable: %s", exc)
                time.sleep(init_backoff)
                continue

        if reinit_interval and (time.time() - initialized_at) >= reinit_interval:
            logging.info(
                "Restarting RGB Matrix 5x5 process after %.0fs for clean controller rearm",
                time.time() - initialized_at,
            )
            quiesce_matrix(matrix)
            return 0

        state = read_latest(latest_path)
        age = state_age_seconds(state)
        stale = not state or age is None or age > stale_after
        base_state = "STALE" if stale else derived_air_quality_state(state)
        accent_state = "CLEAN" if stale else derived_gas_signature(state)
        current_state = (base_state, accent_state, stale)
        if current_state != last_state:
            logging.info(
                "LED state base=%s accent=%s stale=%s age=%.1fs",
                base_state,
                accent_state,
                stale,
                age if age is not None else -1.0,
            )
            last_state = current_state
        try:
            assert engine is not None
            engine.draw(base_state, accent_state, state, time.time())
        except Exception as exc:
            quiesce_matrix(matrix)
            matrix = None
            engine = None
            initialized_at = 0.0
            try:
                record_failure(
                    recovery_failures,
                    window_seconds=failure_window,
                    restart_after_failures=restart_after_failures,
                    reason=f"draw failed: {exc}",
                )
            except MatrixRecoveryExhausted:
                logging.exception("RGB Matrix recovery exhausted during drawing")
                raise
            logging.warning("LED draw failed: %s", exc)
            time.sleep(0.5)
            continue
        time.sleep(max(0.05, frame_interval))


if __name__ == "__main__":
    raise SystemExit(main())
