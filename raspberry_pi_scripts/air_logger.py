import os, time, math, json, statistics
from collections import deque
from datetime import datetime, timezone
import bme680

DATA_DIR = "/home/pi/air/data"
SAMPLES_PATH = os.path.join(DATA_DIR, "air_samples.jsonl")
BATCHES_PATH = os.path.join(DATA_DIR, "air_batches_15m.jsonl")

SAMPLE_EVERY = 2.0
WARMUP_MIN = 10
WINDOW_1M = int(60 / SAMPLE_EVERY)
WINDOW_15M = int((15*60) / SAMPLE_EVERY)

BASELINE_ALPHA = 0.01
MAX_BASELINE_DRIFT = 0.35

def clamp(x,a,b): return max(a, min(b, x))

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def make_sensor():
    try:
        return bme680.BME680(bme680.I2C_ADDR_PRIMARY)
    except Exception:
        return bme680.BME680(bme680.I2C_ADDR_SECONDARY)

def setup_sensor(sensor):
    sensor.set_humidity_oversample(bme680.OS_2X)
    sensor.set_pressure_oversample(bme680.OS_4X)
    sensor.set_temperature_oversample(bme680.OS_8X)
    sensor.set_filter(bme680.FILTER_SIZE_3)
    sensor.set_gas_status(bme680.ENABLE_GAS_MEAS)
    sensor.set_gas_heater_temperature(320)
    sensor.set_gas_heater_duration(150)
    sensor.select_gas_heater_profile(0)

def score_from(gas_med, baseline):
    drel = (gas_med - baseline) / baseline
    quality = (0.15 - drel) / (0.15 + 0.20)
    quality = clamp(quality, 0.0, 1.0)
    score = 100.0 * (1.0 - quality)
    return float(score), float(drel)

def classify(score, warmup, hs_ratio):
    if warmup or hs_ratio < 0.6:
        return "WARMUP"
    if score >= 70: return "GOOD"
    if score >= 40: return "OK"
    return "BAD"

def align_to_next_15m_epoch():
    t = time.time()
    next_mark = math.ceil(t / (15*60)) * (15*60)
    time.sleep(max(0.5, next_mark - t))

def append_jsonl(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")

def mean_or_none(x):
    return float(statistics.mean(x)) if x else None

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    sensor = make_sensor()
    setup_sensor(sensor)

    start_ts = time.time()
    baseline = None

    gas_1m = deque(maxlen=WINDOW_1M)
    stable_1m = deque(maxlen=WINDOW_1M)

    gas_15 = deque(maxlen=WINDOW_15M)
    temp_15 = deque(maxlen=WINDOW_15M)
    hum_15  = deque(maxlen=WINDOW_15M)
    pres_15 = deque(maxlen=WINDOW_15M)
    stable_15 = deque(maxlen=WINDOW_15M)
    state_15 = []

    print("air_logger running. Writing:")
    print("  samples:", SAMPLES_PATH)
    print("  batches:", BATCHES_PATH)

    align_to_next_15m_epoch()
    batch_start_iso = now_iso()
    batch_start_t = time.time()

    while True:
        warmup = (time.time() - start_ts) < (WARMUP_MIN * 60)

        temp = hum = pres = gas = None
        heat_stable = False

        if sensor.get_sensor_data():
            d = sensor.data
            temp = float(d.temperature)
            hum  = float(d.humidity)
            pres = float(d.pressure)
            heat_stable = bool(d.heat_stable)
            if heat_stable:
                gas = float(d.gas_resistance)

        if heat_stable and gas is not None:
            gas_1m.append(gas)
            stable_1m.append(1.0)
        else:
            stable_1m.append(0.0)

        hs_ratio_1m = (sum(stable_1m)/len(stable_1m)) if stable_1m else 0.0
        gas_med_1m = statistics.median(gas_1m) if gas_1m else None

        if (not warmup) and gas_med_1m is not None and hs_ratio_1m >= 0.6:
            if baseline is None:
                baseline = gas_med_1m
            else:
                drel_tmp = (gas_med_1m - baseline) / baseline
                if abs(drel_tmp) < MAX_BASELINE_DRIFT:
                    baseline = (1-BASELINE_ALPHA)*baseline + BASELINE_ALPHA*gas_med_1m

        if warmup or baseline is None or gas_med_1m is None or hs_ratio_1m < 0.6:
            score = None
            drel = None
            state = "WARMUP"
        else:
            score, drel = score_from(gas_med_1m, baseline)
            state = classify(score, warmup, hs_ratio_1m)

        sample = {
            "ts": now_iso(),
            "temp": temp,
            "hum": hum,
            "pres": pres,
            "gas": gas,
            "gas_med_1m": gas_med_1m,
            "baseline": baseline,
            "deviation": drel,
            "air_score": score,
            "state": state,
            "heat_stable": heat_stable,
            "heat_stable_ratio_1m": hs_ratio_1m,
        }
        append_jsonl(SAMPLES_PATH, sample)

        if gas is not None: gas_15.append(gas)
        if temp is not None: temp_15.append(temp)
        if hum is not None: hum_15.append(hum)
        if pres is not None: pres_15.append(pres)
        stable_15.append(1.0 if heat_stable else 0.0)
        state_15.append(state)

        if time.time() - batch_start_t >= 15*60:
            ts_end = now_iso()
            hs_ratio_15 = (sum(stable_15)/len(stable_15)) if stable_15 else 0.0
            per_min = int(60 / SAMPLE_EVERY)

            def minutes_in(label):
                return int(round(state_15.count(label) / per_min))

            gas_med_15 = float(statistics.median(gas_15)) if gas_15 else None
            batch = {
                "node": "air-sensor",
                "ts_start": batch_start_iso,
                "ts_end": ts_end,
                "temp_avg": mean_or_none(temp_15),
                "hum_avg": mean_or_none(hum_15),
                "pres_avg": mean_or_none(pres_15),
                "gas_median": gas_med_15,
                "gas_min": float(min(gas_15)) if gas_15 else None,
                "gas_max": float(max(gas_15)) if gas_15 else None,
                "baseline_gas_end": baseline,
                "air_score_last": score,
                "heat_stable_ratio": float(hs_ratio_15),
                "minutes_good": minutes_in("GOOD"),
                "minutes_ok": minutes_in("OK"),
                "minutes_bad": minutes_in("BAD"),
                "air_state_last": state,
            }
            append_jsonl(BATCHES_PATH, batch)

            gas_15.clear(); temp_15.clear(); hum_15.clear(); pres_15.clear()
            stable_15.clear(); state_15.clear()
            batch_start_iso = ts_end
            batch_start_t = time.time()

        time.sleep(SAMPLE_EVERY)

if __name__ == "__main__":
    main()
