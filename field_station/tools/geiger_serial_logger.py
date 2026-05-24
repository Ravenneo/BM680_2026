#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import termios
import time


def baud_constant(baud):
    name = f"B{baud}"
    if not hasattr(termios, name):
        raise SystemExit(f"Unsupported baud rate: {baud}")
    return getattr(termios, name)


def configure_serial(fd, baud):
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] = termios.CLOCAL | termios.CREAD | termios.CS8
    attrs[3] = 0
    attrs[4] = baud_constant(baud)
    attrs[5] = baud_constant(baud)
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 10
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def parse_line(line):
    line = line.strip()
    csv_match = re.match(r"^(\d+),(\d+),(\d+),([0-9.]+),(\d+)$", line)
    if csv_match:
        return {
            "source": "csv",
            "ms": int(csv_match.group(1)),
            "cps": int(csv_match.group(2)),
            "cpm": int(csv_match.group(3)),
            "usv_h": float(csv_match.group(4)),
            "total": int(csv_match.group(5)),
            "raw": line,
        }

    cpm_match = re.search(r"CPM\s*=?\s*(\d+)", line, re.IGNORECASE)
    usv_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*uSv/?h", line, re.IGNORECASE)
    if cpm_match or usv_match:
        parsed = {"source": "text", "raw": line}
        if cpm_match:
            parsed["cpm"] = int(cpm_match.group(1))
        if usv_match:
            parsed["usv_h"] = float(usv_match.group(1))
        return parsed

    return {"source": "raw", "raw": line}


def atomic_write(path, text):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--state", default="/tmp/geiger_state.json")
    parser.add_argument("--log", default="/tmp/geiger_serial.log")
    args = parser.parse_args()

    latest = {
        "port": args.port,
        "baud": args.baud,
        "status": "opening",
        "updated_at": time.time(),
    }
    atomic_write(args.state, json.dumps(latest))

    with open(args.port, "rb", buffering=0) as serial_file, open(
        args.log, "a", encoding="utf-8", buffering=1
    ) as log_file:
        configure_serial(serial_file.fileno(), args.baud)
        latest["status"] = "listening"
        latest["updated_at"] = time.time()
        atomic_write(args.state, json.dumps(latest))

        buffer = b""
        while True:
            chunk = serial_file.read(128)
            if not chunk:
                latest["status"] = "waiting"
                latest["age"] = round(time.time() - latest.get("updated_at", time.time()), 1)
                atomic_write(args.state, json.dumps(latest))
                continue

            buffer += chunk
            while b"\n" in buffer:
                raw_line, buffer = buffer.split(b"\n", 1)
                line = raw_line.decode("utf-8", errors="replace").strip("\r")
                if not line:
                    continue

                now = time.time()
                parsed = parse_line(line)
                latest.update(parsed)
                latest.update(
                    {
                        "port": args.port,
                        "baud": args.baud,
                        "status": "ok",
                        "updated_at": now,
                        "time": time.strftime("%H:%M:%S"),
                    }
                )
                log_file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
                atomic_write(args.state, json.dumps(latest))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
