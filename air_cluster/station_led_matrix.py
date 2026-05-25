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


def base_rgb(event: str, state: dict[str, Any], t: float) -> tuple[int, int, int]:
    palette = {
        "CLEAN": (24, 118, 118),
        "VOC_EVENT": (190, 102, 24),
        "REDUCING_EVENT": (24, 118, 108),
        "OXIDISING_EVENT": (24, 105, 126),
        "NH3_EVENT": (42, 124, 80),
        "MIXED_EVENT": (34, 112, 106),
        "SENSOR_WARMUP": (0, 72, 150),
        "SENSOR_ERROR": (96, 18, 16),
        "STALE": (32, 50, 60),
    }
    r, g, b = palette.get(event, palette["STALE"])

    bme = state.get("bme690", {}) if isinstance(state.get("bme690"), dict) else {}
    voc_score = bme.get("voc_score")
    try:
        score_factor = 1.0 - clamp(float(voc_score) / 100.0, 0.0, 1.0)
    except (TypeError, ValueError):
        score_factor = 0.25

    deltas = state.get("delta_percentages", {}) if isinstance(state.get("delta_percentages"), dict) else {}
    try:
        bme_gas_delta = float(deltas.get("bme690_gas_pct"))
    except (TypeError, ValueError):
        bme_gas_delta = 0.0
    mics_only = event in ("REDUCING_EVENT", "OXIDISING_EVENT", "NH3_EVENT", "MIXED_EVENT") and bme_gas_delta > -15.0

    if event == "CLEAN" or mics_only:
        blue_drift = 0.35 + 0.25 * (0.5 + 0.5 * math.sin(t * 0.09))
        return int(r * (1.0 - blue_drift)), int(g), int(b * (1.0 + blue_drift))
    if event == "VOC_EVENT":
        return int(r * (1.0 + 0.12 * score_factor)), int(g * 0.9), int(b * 0.6)
    return r, g, b


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

    def event_density(self, event: str) -> float:
        return {
            "CLEAN": 0.055,
            "VOC_EVENT": 0.070,
            "REDUCING_EVENT": 0.065,
            "OXIDISING_EVENT": 0.065,
            "NH3_EVENT": 0.065,
            "MIXED_EVENT": 0.115,
            "SENSOR_WARMUP": 0.050,
            "SENSOR_ERROR": 0.035,
        "STALE": 0.040,
        }.get(event, 0.045)

    def update_energy(self, event: str) -> None:
        density = self.event_density(event)
        if event == "MIXED_EVENT":
            ignition_high = 0.42
        elif event == "SENSOR_ERROR":
            ignition_high = 0.22
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
        event: str,
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
            reducing = abs(float(deltas.get("mics_reducing_pct") or 0.0))
            oxidising = abs(float(deltas.get("mics_oxidising_pct") or 0.0))
            nh3 = abs(float(deltas.get("mics_nh3_pct") or 0.0))
        except (TypeError, ValueError):
            reducing = oxidising = nh3 = 0.0

        pulse = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * 0.21))
        central = abs(x - w // 2) + abs(y - h // 2) <= 1
        corner_or_diag = (x in (0, w - 1) and y in (0, h - 1)) or x == y or x == w - 1 - y
        lower_edge = y == h - 1 or (y == h - 2 and x in (1, w - 2))

        if event in ("REDUCING_EVENT", "MIXED_EVENT") and central:
            strength = clamp((reducing / 60.0) + 0.18, 0.12, 0.42) * pulse
            return (175, 36, 28), strength
        if event in ("OXIDISING_EVENT", "MIXED_EVENT") and corner_or_diag:
            strength = clamp((oxidising / 60.0) + 0.14, 0.10, 0.36) * pulse
            return (80, 70, 185), strength
        if event in ("NH3_EVENT", "MIXED_EVENT") and lower_edge:
            strength = clamp((nh3 / 60.0) + 0.14, 0.10, 0.34) * pulse
            return (165, 150, 38), strength
        return None, 0.0

    def draw(self, event: str, state: dict[str, Any], t: float) -> None:
        self.update_energy(event)
        base = base_rgb(event, state, t)
        validity = state.get("validity", {}) if isinstance(state.get("validity"), dict) else {}
        confidence = clamp(float(validity.get("confidence", 0.35) or 0.35), 0.0, 1.0)
        w, h = self.matrix.width, self.matrix.height

        for y in range(h):
            for x in range(w):
                organic = 0.80 + self.wobble * math.sin(t * 0.31 + x * 1.17 + y * 0.73)
                ember = clamp(self.energy[y][x] * organic, 0.0, 1.0)

                if event == "SENSOR_WARMUP":
                    breathe = 0.50 + 0.50 * (0.5 + 0.5 * math.sin(t * 0.24))
                    ember = max(ember, 0.18 + 0.45 * breathe)
                elif event == "SENSOR_ERROR":
                    pulse = 0.20 + 0.80 * (0.5 + 0.5 * math.sin(t * 0.11))
                    ember = max(ember * 0.7, 0.06 + 0.20 * pulse)
                elif event == "STALE":
                    ember = max(ember * 0.65, 0.045)

                intensity = lerp(
                    self.min_brightness,
                    self.max_brightness,
                    clamp(ember * lerp(0.62, 1.0, confidence), 0.0, 1.0),
                )
                if event == "SENSOR_WARMUP":
                    intensity = max(intensity, 0.18 + 0.22 * (0.5 + 0.5 * math.sin(t * 0.24)))
                pixel_color = base
                accent, amount = self.accent_for_pixel(event, state, x, y, t)
                if accent is not None:
                    pixel_color = blend_color(pixel_color, accent, amount)

                self.matrix.set_pixel(
                    x,
                    y,
                    int(clamp(pixel_color[0], 0, 255)),
                    int(clamp(pixel_color[1], 0, 255)),
                    int(clamp(pixel_color[2], 0, 255)),
                    brightness=clamp(intensity, 0.0, 1.0),
                )
        self.matrix.show()


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

    matrix: Matrix | None = None
    engine: PatternEngine | None = None

    while True:
        if matrix is None:
            try:
                matrix = Matrix(float(led_cfg.get("brightness", 0.45)))
                engine = PatternEngine(matrix, led_cfg)
                logging.info("RGB Matrix 5x5 initialized")
            except Exception as exc:
                logging.warning("RGB Matrix unavailable: %s", exc)
                time.sleep(10)
                continue

        state = read_latest(latest_path)
        age = state_age_seconds(state)
        stale = not state or age is None or age > stale_after
        event = "STALE" if stale else str(state.get("event_signature") or "SENSOR_WARMUP")
        try:
            assert engine is not None
            engine.draw(event, state, time.time())
        except Exception as exc:
            logging.warning("LED draw failed: %s", exc)
            matrix = None
            engine = None
        time.sleep(max(0.05, frame_interval))


if __name__ == "__main__":
    raise SystemExit(main())
