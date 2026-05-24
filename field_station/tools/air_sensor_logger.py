#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import time


def atomic_write(path, text):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.0.149")
    parser.add_argument("--user", default="pi")
    parser.add_argument("--key", default=os.path.expanduser("~/.ssh/id_ed25519"))
    parser.add_argument("--remote-log", default="/home/pi/air/data/air_samples.jsonl")
    parser.add_argument("--state", default="/tmp/air_state.json")
    parser.add_argument("--log", default="/tmp/air_sensor.log")
    parser.add_argument("--period", type=float, default=5.0)
    args = parser.parse_args()

    target = f"{args.user}@{args.host}"
    ssh_cmd = [
        "ssh",
        "-i",
        args.key,
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=5",
        target,
        f"tail -1 {args.remote_log}",
    ]

    latest = {
        "host": args.host,
        "status": "starting",
        "updated_at": time.time(),
    }
    atomic_write(args.state, json.dumps(latest))

    while True:
        now = time.time()
        try:
            result = subprocess.run(
                ssh_cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=8,
            )
            line = result.stdout.strip().splitlines()[-1]
            sample = json.loads(line)
            sample.update(
                {
                    "host": args.host,
                    "status": "ok",
                    "updated_at": now,
                    "local_time": time.strftime("%H:%M:%S"),
                }
            )
            atomic_write(args.state, json.dumps(sample, separators=(",", ":")))
            with open(args.log, "a", encoding="utf-8", buffering=1) as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
        except Exception as exc:
            latest.update(
                {
                    "host": args.host,
                    "status": "error",
                    "error": str(exc),
                    "updated_at": now,
                    "local_time": time.strftime("%H:%M:%S"),
                }
            )
            atomic_write(args.state, json.dumps(latest, separators=(",", ":")))

        time.sleep(args.period)


if __name__ == "__main__":
    main()
