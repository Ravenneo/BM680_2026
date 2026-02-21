#!/bin/bash
set -e

cd /home/pi/air
source /home/pi/air/.venv/bin/activate

exec python /home/pi/air/led_tiles_bme680.py
