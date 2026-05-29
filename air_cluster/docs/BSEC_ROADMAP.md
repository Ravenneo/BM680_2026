# BSEC Roadmap

This document records the investigation and implementation plan for optional Bosch BSEC/BME690 support on Air-Station.

## Current Status

Air-Station is a Raspberry Pi Zero 2W running Debian 13 on `aarch64` / `arm64`. The BME690 is visible on I2C at `0x76`. The current logger works in raw mode with BME690 readings plus MICS6814 readings.

BSEC/Bosch BME690 software is not installed yet. The current Python virtual environment does not include `bme68x`, `bsecConstants`, or a BSEC wrapper. `bsec_probe.py` and [BSEC_SETUP.md](BSEC_SETUP.md) are prepared so Air-Station can be tested separately before changing the working logger.

## Current Stable Mode

The current stable mode uses the local raw BME690 backend and the MICS6814 backend:

- BME690 raw backend:
  - temperature
  - humidity
  - pressure
  - gas_resistance
  - local rolling baselines
  - local `air_quality_state`
- MICS6814 backend:
  - reducing
  - oxidising
  - nh3
  - relative `gas_signature`
- LED:
  - BME690 controls base air-quality context.
  - MICS6814 controls accent patterns.
  - Calm random intensity and organic flicker are preserved.

This mode is stable and should remain the default fallback.

## Future Optional BSEC Mode

BSEC may provide higher-level Bosch-derived outputs:

- `iaq`
- `iaq_accuracy`
- `static_iaq`
- `static_iaq_accuracy`
- `breath_voc_equivalent` or TVOC-equivalent, depending on BSEC version and wrapper
- `co2_equivalent`
- `raw_gas`
- `raw_temperature`
- `raw_humidity`
- `raw_pressure`

These values should be written under a separate `bsec` object in `latest_state.json` and JSONL samples. Raw BME690 readings and MICS6814 readings should continue to be logged.

## Why BSEC Is Useful

BSEC adds Bosch's sensor-fusion and compensation layer on top of the raw BME690 measurements. That gives us IAQ, static IAQ, equivalent VOC/TVOC-style outputs, and CO2-equivalent outputs that are more useful for long-running air-quality displays than raw gas resistance alone.

These outputs are still estimates and indices. Do not describe VOC equivalent values or CO2-equivalent as lab-grade measurements. CO2-equivalent is not a direct NDIR CO2 measurement. VOC equivalent values are Bosch-derived estimates or indices, not calibrated chromatography results.

## Timing And Licensing Cautions

BSEC timing matters:

- LP mode expects approximately 3 second samples.
- ULP mode expects approximately 300 second samples.
- The current logger interval is 10 seconds, so BSEC requires either changing the logger interval or selecting a compatible BSEC mode.

BSEC distribution also matters:

- BSEC download requires accepting Bosch license terms.
- Do not commit Bosch closed-source binaries into the public repo unless the license explicitly allows it.
- Keep BSEC files outside git, or in a clearly gitignored vendor directory, if required by license.

## Why BME690 Is Better Than The Old BME680 Setup

In raw mode, the improvement over the old BME680 setup is limited unless we use better baselines and better event modelling. The current Air-Station model already improves this by separating BME690 air-quality context from MICS6814 gas-signature accents.

With BSEC/BME690 software, we can access IAQ, equivalent VOC/TVOC-style outputs, and CO2-equivalent outputs. BME690/BSEC also opens the door to more advanced gas-scan and gas-fingerprint workflows.

The MICS6814 adds a second independent qualitative gas signature layer. That makes this setup stronger than the old BME680-only system because the BME690 can provide the base air-quality context while the MICS6814 provides an independent reducing/oxidising/NH3 signature.

## Implementation Plan

### Phase 1: Documentation Only

- Keep the current raw logger stable.
- Add documentation only.
- Add TODOs in `README.md`.

### Phase 2: Isolated BSEC Probe

- Download the official Bosch BSEC ZIP manually.
- Store it outside the repo or in a clearly gitignored vendor directory.
- Build and install the Python wrapper in a separate test virtual environment.
- Run `air_cluster/bsec_probe.py`.
- Test the BME690 at `0x76` without touching `station_logger.py`.

### Phase 3: Optional Backend

- Create either `station_logger_bsec.py` or a backend abstraction.
- Add config keys:

```yaml
bme690_backend: raw|bsec
bsec_enabled: false
bsec_sample_interval_seconds: 3
```

- Write BSEC outputs to `latest_state.json` under a separate `bsec` object.
- Keep raw readings and MICS6814 readings.

### Phase 4: Safe Integration

- Only after stable tests, allow `station_logger.py` to load the BSEC backend if enabled.
- If BSEC fails to import, initialize, or produce valid samples, automatically fall back to raw mode.
- Raw mode must remain the default and must not require Bosch binaries.

## Expected JSON Shape

When enabled and healthy, BSEC data should be additive:

```json
{
  "bme690": {
    "temperature_c": 23.1,
    "humidity_pct": 40.2,
    "pressure_hpa": 1012.5,
    "gas_ohms": 123456.0
  },
  "bsec": {
    "iaq": 52.0,
    "iaq_accuracy": 1,
    "static_iaq": 50.0,
    "static_iaq_accuracy": 1,
    "breath_voc_equivalent": 0.5,
    "co2_equivalent": 600.0,
    "raw_gas": 123.4,
    "raw_temperature": 23.1,
    "raw_humidity": 40.2,
    "raw_pressure": 101250.0
  },
  "mics6814": {
    "reducing": 250000.0,
    "oxidising": 34000.0,
    "nh3": 170000.0
  }
}
```

Field units depend on the wrapper. Confirm units in `bsec_probe.py` output before committing logger field names or unit conversions.
