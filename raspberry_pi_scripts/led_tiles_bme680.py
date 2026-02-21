#!/usr/bin/env python3
import time, math, statistics, random
from collections import deque

import bme680
from rgbmatrix5x5 import RGBMatrix5x5

# ====== Sampling / Warmup ======
SAMPLE_EVERY = 2.0
WARMUP_MIN = 10
WINDOW_1M = int(60 / SAMPLE_EVERY)

# ====== Baseline ======
BASELINE_ALPHA = 0.01
MAX_BASELINE_DRIFT = 0.35

# ====== LED Look (tunable) ======
BRIGHTNESS = 0.28        # <- sube/baja aquí (0.22-0.38 suele ser sweet spot)
GAMMA = 2.0              # un poco menos gamma = más intensidad perceptual

# “cuadro dentro de otro”
RING_STRENGTH = 1.00     # borde exterior
INNER_STRENGTH = 0.55    # relleno interior
INNER_SIZE_MIN = 2
INNER_SIZE_MAX = 4

# movimiento interior suave
INNER_DRIFT_SPEED = 0.18 # cuanto más, más movimiento

# geometrías suaves
SHAPE_PERIOD = 10.0      # cambia figura cada N segundos
SHAPE_FADE_SPEED = 0.35  # velocidad de fade entre figuras (sin blink)
SHAPE_INTENSITY = 0.55   # fuerza de la geometría sobre el patrón base

# score thresholds
GOOD_SCORE = 70
OK_SCORE = 40

def clamp(x, a, b): return max(a, min(b, x))
def lerp(a, b, t): return a + (b - a) * t

def gamma_u8(v):
    v = clamp(v / 255.0, 0.0, 1.0)
    v = v ** GAMMA
    return int(clamp(v * 255.0, 0, 255))

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
    if score >= GOOD_SCORE: return "GOOD"
    if score >= OK_SCORE: return "OK"
    return "BAD"

def base_rgb(state, score, t):
    # warmup: azul suave
    if state == "WARMUP":
        breathe = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * 0.55))
        r = 0
        g = int(lerp(18,  70, breathe))
        b = int(lerp(55, 230, breathe))
        return r, g, b

    if score is None:
        return 0, 110, 0

    s = clamp(score / 100.0, 0.0, 1.0)
    q = 1.0 - s

    if q <= 0.5:
        t2 = q / 0.5
        r = int(lerp(0,   235, t2))
        g = int(lerp(150, 235, t2))
        b = 0
    else:
        t2 = (q - 0.5) / 0.5
        r = 235
        g = int(lerp(235, 0, t2))
        b = 0
    return r, g, b

# ---------- Shapes (0..1 mask per pixel) ----------
def shape_ring(w,h):
    m = [[0.0]*w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if x==0 or y==0 or x==w-1 or y==h-1:
                m[y][x]=1.0
    return m

def shape_inner_box(w,h, size=3):
    m = [[0.0]*w for _ in range(h)]
    cx, cy = w//2, h//2
    half = size//2
    for y in range(h):
        for x in range(w):
            if abs(x-cx)<=half and abs(y-cy)<=half:
                m[y][x]=1.0
    return m

def shape_diagonal(w,h, direction=1):
    m = [[0.0]*w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if (x==y and direction==1) or (x==w-1-y and direction==-1):
                m[y][x]=1.0
    return m

def shape_cross(w,h):
    m = [[0.0]*w for _ in range(h)]
    cx, cy = w//2, h//2
    for y in range(h):
        for x in range(w):
            if x==cx or y==cy:
                m[y][x]=1.0
    return m

def shape_corners(w,h):
    m = [[0.0]*w for _ in range(h)]
    m[0][0]=m[0][w-1]=m[h-1][0]=m[h-1][w-1]=1.0
    return m

def shape_random_points(w,h, n=5, seed=0):
    rnd = random.Random(seed)
    m = [[0.0]*w for _ in range(h)]
    pts=set()
    while len(pts)<n:
        pts.add((rnd.randrange(w), rnd.randrange(h)))
    for x,y in pts:
        m[y][x]=1.0
    return m

def pick_shape(w,h, seed):
    rnd = random.Random(seed)
    k = rnd.choice(["ring","inner","diag1","diag2","cross","corners","points"])
    if k=="ring":   return shape_ring(w,h)
    if k=="inner":  return shape_inner_box(w,h, size=rnd.randint(2,4))
    if k=="diag1":  return shape_diagonal(w,h, 1)
    if k=="diag2":  return shape_diagonal(w,h, -1)
    if k=="cross":  return shape_cross(w,h)
    if k=="corners":return shape_corners(w,h)
    return shape_random_points(w,h, n=rnd.randint(3,6), seed=seed+1337)

class PatternEngine:
    def __init__(self):
        self.m = RGBMatrix5x5()
        self.m.set_clear_on_exit()
        self.m.set_brightness(BRIGHTNESS)
        self.w = self.m.width
        self.h = self.m.height

        self.shape_a = pick_shape(self.w, self.h, seed=1)
        self.shape_b = pick_shape(self.w, self.h, seed=2)
        self.last_shape_t = time.time()
        self.shape_seed = 3

    def _inner_window(self, t):
        # size and position drift slowly
        size = int(round(lerp(INNER_SIZE_MIN, INNER_SIZE_MAX, 0.5 + 0.5*math.sin(t*0.07))))
        size = clamp(size, INNER_SIZE_MIN, INNER_SIZE_MAX)
        max_off = (self.w - size)
        # smooth drift in [0, max_off]
        ox = int(round((0.5 + 0.5*math.sin(t*INNER_DRIFT_SPEED + 0.7)) * max_off))
        oy = int(round((0.5 + 0.5*math.sin(t*INNER_DRIFT_SPEED + 1.9)) * max_off))
        return ox, oy, size

    def _shape_mix(self, t):
        # change target shape every SHAPE_PERIOD seconds with smooth crossfade
        dt = t - self.last_shape_t
        if dt >= SHAPE_PERIOD:
            self.last_shape_t = t
            self.shape_a = self.shape_b
            self.shape_b = pick_shape(self.w, self.h, seed=self.shape_seed)
            self.shape_seed += 1
            dt = 0.0

        # crossfade curve (ease)
        x = clamp(dt * SHAPE_FADE_SPEED, 0.0, 1.0)
        x = x*x*(3-2*x)  # smoothstep
        return x

    def draw(self, state, score, t):
        br, bg, bb = base_rgb(state, score, t)

        ox, oy, size = self._inner_window(t)
        mix = self._shape_mix(t)

        # subtle global breathe (reduces “static”)
        breathe = 0.85 + 0.15*(0.5 + 0.5*math.sin(t*0.35))

        for y in range(self.h):
            for x in range(self.w):
                # base “frame + inner window”
                is_border = (x==0 or y==0 or x==self.w-1 or y==self.h-1)
                in_inner = (ox <= x < ox+size and oy <= y < oy+size)

                base_gain = 1.0
                if is_border:
                    base_gain *= RING_STRENGTH
                else:
                    base_gain *= 0.65

                if in_inner:
                    # inner window is calmer
                    base_gain *= INNER_STRENGTH

                # shape overlay (soft, no blink): 0..1
                sa = self.shape_a[y][x]
                sb = self.shape_b[y][x]
                sm = lerp(sa, sb, mix)

                # shape increases brightness slightly, but moderated
                gain = base_gain * breathe * (1.0 + SHAPE_INTENSITY * sm)

                # tiny per-pixel variation (keeps “dreamy”)
                wob = 0.92 + 0.08*(0.5 + 0.5*math.sin(t*0.6 + x*1.1 + y*0.7))
                gain *= wob

                r = gamma_u8(int(clamp(br * gain, 0, 255)))
                g = gamma_u8(int(clamp(bg * gain, 0, 255)))
                b = gamma_u8(int(clamp(bb * gain, 0, 255)))

                self.m.set_pixel(x, y, r, g, b)

        self.m.show()

def main():
    sensor = make_sensor()
    setup_sensor(sensor)
    led = PatternEngine()

    start_ts = time.time()
    baseline = None
    gas_1m = deque(maxlen=WINDOW_1M)
    stable_1m = deque(maxlen=WINDOW_1M)

    print("LED air system running (frame+shapes)... Ctrl+C to stop")
    while True:
        t = time.time()
        warmup = (t - start_ts) < (WARMUP_MIN * 60)

        gas = None
        heat_stable = False
        if sensor.get_sensor_data():
            d = sensor.data
            heat_stable = bool(d.heat_stable)
            if heat_stable:
                gas = float(d.gas_resistance)

        if heat_stable and gas is not None:
            gas_1m.append(gas)
            stable_1m.append(1.0)
        else:
            stable_1m.append(0.0)

        hs_ratio = (sum(stable_1m)/len(stable_1m)) if stable_1m else 0.0
        gas_med = statistics.median(gas_1m) if gas_1m else None

        if (not warmup) and gas_med is not None and hs_ratio >= 0.6:
            if baseline is None:
                baseline = gas_med
            else:
                drel_tmp = (gas_med - baseline) / baseline
                if abs(drel_tmp) < MAX_BASELINE_DRIFT:
                    baseline = (1-BASELINE_ALPHA)*baseline + BASELINE_ALPHA*gas_med

        if warmup or baseline is None or gas_med is None or hs_ratio < 0.6:
            score = None
            state = "WARMUP"
        else:
            score, _ = score_from(gas_med, baseline)
            state = classify(score, warmup, hs_ratio)

        led.draw(state, score, t)
        time.sleep(SAMPLE_EVERY)

if __name__ == "__main__":
    main()
