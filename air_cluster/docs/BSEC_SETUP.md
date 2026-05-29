# BSEC Setup For Air-Station

This project keeps BSEC optional. The raw BME690 logger must keep working without
Bosch closed-source binaries.

## What BSEC Adds

BSEC is Bosch Sensortec Environmental Cluster software. It runs outside the
BME690 sensor and fuses raw temperature, humidity, pressure, and gas-resistance
signals into higher-level outputs:

- IAQ and static IAQ indexes.
- bVOC or breath-VOC equivalent, depending on the BSEC package/wrapper.
- CO2 equivalent.
- Humidity compensation, baseline handling, and long-term drift correction.
- Gas scan outputs when the selected BSEC mode/config supports them.

These are Bosch-derived estimates and indexes. CO2 equivalent is not direct NDIR
CO2. VOC equivalent is not a lab-grade VOC concentration.

## Current Project State

`station_logger.py` still uses the stable raw backend by default. BSEC config is
present but disabled:

```json
"backend": "raw",
"bsec": {
  "enabled": false,
  "sample_interval_seconds": 3,
  "state_file": "data/bsec_state.bin",
  "config_file": "",
  "vendor_dir": "vendor/bsec"
}
```

Do not set `backend` to `bsec` until `bsec_probe.py` reports a working wrapper on
Air-Station.

## Files Prepared In This Repo

- `bsec_probe.py`: checks platform, I2C visibility, Python modules, vendor paths,
  and can attempt one `bme68x` raw read.
- `vendor/bsec/`: reserved for Bosch BSEC packages and wrappers. It is ignored by
  git.
- `data/bsec_state.bin`: reserved for BSEC runtime state. It is ignored by git.

## Bosch Package

Download the BME688/BME690 BSEC package manually from Bosch Sensortec after
accepting Bosch license terms. Do not commit the Bosch ZIP, extracted binaries,
or generated binary state/config files into this public repo.

Expected current upstream package family:

- BSEC for BME688/BME690.
- BME69x/BME68x Sensor API.
- BSEC examples and implementation guide inside the release package.

As of May 29, 2026, Bosch's BME688/BME690 software page lists BSEC v3.3.0.0
(March 2026), but the public HTML does not expose a usable direct ZIP URL. If the
browser download link does not work, use Bosch Sensortec support/community to get
the official package, then place the ZIP on Air-Station manually.

## Raspberry Pi Install Plan

Run on Air-Station:

```bash
cd /home/pi/BM680_2026/air_cluster
mkdir -p vendor/bsec
python3 bsec_probe.py --config config.yaml
```

Before BSEC install, the probe should normally report:

- BME690 visible on I2C, usually at `0x76`.
- `bme68x`, `bsec`, or `bsecConstants` missing.
- BSEC not ready.

Then install a Python wrapper that can link against Bosch BSEC. The practical
Raspberry Pi route is usually a `bme68x` Python wrapper built locally against the
downloaded Bosch BSEC package. Keep that checkout and Bosch package under
`vendor/bsec/` or another local, gitignored path.

After copying the official Bosch ZIP to Air-Station:

```bash
cd /home/pi/BM680_2026/air_cluster
python3 tools/prepare_bsec_vendor.py /path/to/BSEC.zip --clean
cat vendor/bsec/INVENTORY.json
```

The inventory must show Raspberry Pi or Linux ARM library files before we attempt
Python integration.

The optional helper below tries the community `bme68x` Python wrapper route for
BSEC 2.6.1.0:

```bash
cd /home/pi/BM680_2026/air_cluster
cd vendor/bsec/bme68x-python-library-bsec2.6.1.0
unzip /path/to/bsec2-6-1-0_generic_release.zip
cd /home/pi/BM680_2026/air_cluster
PYTHON_BIN=.venv/bin/python tools/install_bsec_wrapper.sh
```

On the current Air-Station OS (`aarch64`), the helper auto-selects `BSEC2=64`,
which maps to Bosch's `PiFour_Armv8` library path in BSEC 2.6.1.0. That library
is expected to work for 64-bit Raspberry Pi OS on Pi 4/5 class targets; if Bosch
does not include a compatible Linux ARM64 binary, installation must stop and raw
mode remains the fallback.

After installing the wrapper into the Air-Station virtual environment, run:

```bash
cd /home/pi/BM680_2026/air_cluster
python3 bsec_probe.py --config config.yaml --read
```

Only continue when the probe shows:

- `bme68x` import works.
- BSEC-related Python module/symbols are present.
- A raw read works from the configured BME690 address.

## Timing

BSEC timing must match the selected mode. Bosch documents typical IAQ modes for
BME690 as:

- LP mode: about 3 second update interval.
- ULP mode: about 300 second update interval.

The current raw logger interval is 10 seconds, so BSEC integration must either:

- run a dedicated BSEC sample loop at 3 seconds, or
- change the logger interval when `backend=bsec`, or
- use an explicitly compatible ULP mode.

Do not feed BSEC irregular 10 second samples and assume IAQ accuracy.

## Integration Criteria

Before changing `station_logger.py` to consume BSEC outputs:

1. `bsec_probe.py --read` works on Air-Station.
2. BSEC sample timing is confirmed.
3. Output names and units are confirmed from real probe output.
4. BSEC state save/restore works across service restart.
5. Raw mode still works with no BSEC files installed.

When integrated, BSEC fields should be additive:

```json
"bsec": {
  "iaq": 52.0,
  "iaq_accuracy": 1,
  "static_iaq": 50.0,
  "static_iaq_accuracy": 1,
  "breath_voc_equivalent": 0.5,
  "co2_equivalent": 600.0
}
```

Keep raw BME690 fields and MICS6814 fields in the same sample.
