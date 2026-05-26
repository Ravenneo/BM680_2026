# Air Cluster

Two-node Raspberry Pi mini-cluster for BM680_2026.

- Air-Station: Raspberry Pi Zero 2W active measurement node.
- Air-Sensor: Raspberry Pi Zero W legacy archive node and backup receiver.

This folder is separate from the legacy BME680 scripts. New v2 data is written under `air_cluster/data/` on Air-Station and archived to `/home/pi/air_archive/air_station/` on Air-Sensor. Do not append BME690/MICS6814 data to legacy BME680 files.

## Archive Layout

On Air-Sensor:

```text
/home/pi/air_archive/
├── legacy_bme680/
└── air_station/
    ├── raw_samples.jsonl
    ├── hourly_batches.jsonl
    ├── daily_summary.jsonl
    └── latest_state.json
```

`legacy_bme680/` is reserved for old BME680 history. Keep it separate from `air_station/`.

On Air-Station:

```text
air_cluster/data/
├── raw_samples.jsonl
├── hourly_batches.jsonl
├── daily_summary.jsonl
├── latest_state.json
├── archive_status.json
└── archive_push.log
```

JSONL files are append-only. `latest_state.json` and `archive_status.json` are atomically replaced.

## First-Time Setup

On Air-Station:

```bash
cd /home/pi
git clone https://github.com/Ravenneo/BM680_2026.git
cd /home/pi/BM680_2026/air_cluster
mkdir -p data
```

On Air-Sensor, create the archive directories without moving or deleting old data:

```bash
mkdir -p /home/pi/air_archive/legacy_bme680
mkdir -p /home/pi/air_archive/air_station
```

If old BME680 data already lives in `/home/pi/air/data`, leave it there until it has been inspected and backed up. Only copy it into `legacy_bme680/` when you are ready:

```bash
rsync -av --ignore-existing /home/pi/air/data/ /home/pi/air_archive/legacy_bme680/
```

Do not use `--delete` for archive operations.

## I2C Validation

Run on Air-Station:

```bash
hostname
i2cdetect -y 1
```

Expected useful signs:

- BME690/BME68x commonly appears at `0x76` or `0x77`.
- Pimoroni Breakout Garden devices should appear on the I2C bus.
- If the matrix or sensors do not appear, check I2C enablement with `sudo raspi-config`.

Run on Air-Sensor too, before disabling old loops, so you know what is still attached:

```bash
hostname
i2cdetect -y 1
```

## Dependencies

On Air-Station:

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv rsync i2c-tools
python3 -m pip install --user bme680 rgbmatrix5x5
```

Install the Pimoroni MICS6814 library that matches the attached breakout. If the library exposes different method names, adjust only `MICS6814Adapter` in `station_logger.py`.

On Air-Sensor:

```bash
sudo apt update
sudo apt install -y rsync openssh-server
```

## SSH Key Setup

From Air-Station:

```bash
ssh-keygen -t ed25519 -f /home/pi/.ssh/id_ed25519 -N ""
ssh-copy-id -i /home/pi/.ssh/id_ed25519.pub pi@192.168.0.149
ssh pi@192.168.0.149 'mkdir -p /home/pi/air_archive/legacy_bme680 /home/pi/air_archive/air_station'
```

Test rsync without deleting anything:

```bash
cd /home/pi/BM680_2026/air_cluster
python3 archive_push.py --config config.yaml
cat data/archive_status.json
```

Default target:

```text
pi@192.168.0.149:/home/pi/air_archive/air_station/
```

The push uses `rsync` over SSH. JSONL files use append verification where sensible. The workflow never passes `--delete`.

## Running Manually

Logger:

```bash
cd /home/pi/BM680_2026/air_cluster
python3 station_logger.py --config config.yaml
```

LED:

```bash
cd /home/pi/BM680_2026/air_cluster
python3 station_led_matrix.py --config config.yaml
```

Archive push:

```bash
cd /home/pi/BM680_2026/air_cluster
python3 archive_push.py --config config.yaml
```

Health check:

```bash
cd /home/pi/BM680_2026/air_cluster
python3 health_check.py --config config.yaml
python3 health_check.py --config config.yaml --json
```

The health check covers:

- Air-Station local data freshness.
- Air-Sensor SSH reachability.
- Last archive sync status from `data/archive_status.json`.
- Local disk usage and Air-Sensor disk command output.
- Latest sensor status from `data/latest_state.json`.

## systemd Install

Adjust unit paths if the repository is not at `/home/pi/BM680_2026`.

On Air-Station:

```bash
cd /home/pi/BM680_2026/air_cluster
sudo cp systemd/air-station-*.service /etc/systemd/system/
sudo cp systemd/air-station-archive.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now air-station-logger.service
sudo systemctl enable --now air-station-led.service
sudo systemctl enable --now air-station-archive.timer
```

The archive timer runs hourly:

```bash
systemctl list-timers air-station-archive.timer
systemctl status air-station-archive.timer
```

Check services:

```bash
systemctl status air-station-logger.service
systemctl status air-station-led.service
systemctl status air-station-archive.service
journalctl -u air-station-logger.service -f
```

## Safely Disabling Old Air-Sensor Loops

Do this only after old BME680 data has been inspected and copied/backed up.

First inventory what is running on Air-Sensor:

```bash
ps auxww | grep -Ei 'python|air|bme|matrix|sensor' | grep -v grep
crontab -l
systemctl list-units --type=service --all | grep -Ei 'air|bme|sensor|matrix|python'
systemctl list-unit-files | grep -Ei 'air|bme|sensor|matrix|python'
```

Back up legacy data without deleting the original:

```bash
mkdir -p /home/pi/air_archive/legacy_bme680
rsync -av --ignore-existing /home/pi/air/data/ /home/pi/air_archive/legacy_bme680/
```

If old loops are systemd services, stop and disable only the identified legacy service names:

```bash
sudo systemctl stop LEGACY_SERVICE_NAME.service
sudo systemctl disable LEGACY_SERVICE_NAME.service
```

If old loops are in cron, comment them out rather than deleting the whole crontab:

```bash
crontab -l > ~/crontab.before-air-archive.txt
crontab -e
```

Do not remove `/home/pi/air`, `/home/pi/air/data`, or any old `.jsonl` logs.

## Restore From Archive

To restore Air-Station v2 data from Air-Sensor to a fresh Air-Station checkout:

```bash
cd /home/pi/BM680_2026/air_cluster
mkdir -p data
rsync -av pi@192.168.0.149:/home/pi/air_archive/air_station/ data/
```

To inspect legacy BME680 data:

```bash
ssh pi@192.168.0.149
ls -lah /home/pi/air_archive/legacy_bme680
```

Keep restored legacy BME680 data separate from v2 BME690/MICS6814 data.

## Sensor Data Notes

Current stable mode is raw mode. It does not use Bosch BSEC yet.

Architecture:

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
  - BME690 controls the base air-quality context.
  - MICS6814 controls accent patterns.
  - Calm random intensity and organic ember-like flicker are preserved.

The raw BME690 gas signal is treated as a relative air-quality signal, not as a lab-grade IAQ value. The MICS6814 channels are qualitative relative measurements only. No MICS6814 ppm claims are made.

Future BSEC support is documented in [docs/BSEC_ROADMAP.md](docs/BSEC_ROADMAP.md). BSEC must stay optional and behind a config flag; do not make the working raw logger depend on Bosch closed-source binaries.

TODO:

- Add optional BSEC probe tooling without changing `station_logger.py`.
- Add a config-gated BSEC backend only after it is tested on Air-Station.
- Keep raw BME690 and MICS6814 logging available as the fallback path.

## Baseline Calibration

After calm data has accumulated:

```bash
cd /home/pi/BM680_2026/air_cluster
python3 calibrate_baselines.py --config config.yaml
```

This prints baseline suggestions. It does not rewrite config or mutate historical data.
