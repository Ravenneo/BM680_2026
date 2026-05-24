# RAVEN FIELD STATION

Terminal dashboard for the local BME680 air sensor and Geiger-Muller counter.

This is an optional field-station view that runs alongside the existing Air Guardian Streamlit dashboard. It reads local state files produced by lightweight loggers and renders a Rich-powered console suitable for tmux, SSH sessions, demos, and screenshots.

## What It Shows

- Air Sensor node from the Raspberry Pi BME680 logger:
  - air score
  - air state
  - temperature
  - humidity
  - gas resistance
  - sample age and trends
- Geiger-Muller counter:
  - CPS
  - CPM
  - dose in uSv/h
  - total pulses
  - activity gauge and CPM trend
- Session health and recent event stream.

## Runtime Files

The dashboard expects these files to exist locally:

```text
/tmp/geiger_state.json
/tmp/geiger_serial.log
/tmp/air_state.json
/tmp/air_sensor.log
```

The included loggers can create them:

```bash
python3 tools/geiger_serial_logger.py --port /dev/ttyUSB0 --baud 9600
python3 tools/air_sensor_logger.py --host 192.168.0.149 --user pi
```

The air logger assumes SSH key access to the Pi. Configure it once, for example:

```bash
ssh-copy-id pi@192.168.0.149
```

## Launch

Install the terminal UI dependency:

```bash
python3 -m pip install rich
```

Run the dashboard:

```bash
python3 field_station/tools/raven_field_station.py
```

Or from this folder:

```bash
tools/start_raven_field_station.sh
```

## tmux Example

```bash
tmux new-session -d -s geiger -n airlog 'cd /path/to/BM680_2026/field_station && python3 tools/air_sensor_logger.py'
tmux new-window -t geiger -n logger 'cd /path/to/BM680_2026/field_station && python3 tools/geiger_serial_logger.py --port /dev/ttyUSB0 --baud 9600'
tmux new-window -t geiger -n raven 'cd /path/to/BM680_2026 && python3 field_station/tools/raven_field_station.py'
tmux attach -t geiger
```

## Arduino

The corrected Geiger firmware lives in:

```text
field_station/arduino/GeigerUsbQuiet/GeigerUsbQuiet.ino
```

It uses an I2C 16x2 LCD at address `0x27`, inferred from the original firmware backup, and emits CSV telemetry over serial at 9600 baud.
