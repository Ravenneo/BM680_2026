#!/usr/bin/env python3
import json
import os
import time


STATE = "/tmp/geiger_state.json"
LOG = "/tmp/geiger_serial.log"


def read_state():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        return {"status": f"sin estado: {exc}"}


def tail_lines(path, count=8):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [line.rstrip("\n") for line in lines[-count:]]
    except FileNotFoundError:
        return []


def main():
    while True:
        state = read_state()
        os.system("clear")
        print("MEDIDAS CONSTANTES")
        print("=" * 50)
        print(f"Estado : {state.get('status', '?')}")
        print(f"Puerto : {state.get('port', '?')} @ {state.get('baud', '?')}")
        print(f"Hora   : {state.get('time', '--:--:--')}")
        print(f"CPS    : {state.get('cps', '-')}")
        print(f"CPM    : {state.get('cpm', '-')}")
        print(f"uSv/h  : {state.get('usv_h', '-')}")
        print(f"Total  : {state.get('total', '-')}")
        print(f"Raw    : {state.get('raw', '-')}")
        print()
        print("Ultimas lineas serie")
        print("-" * 50)
        for line in tail_lines(LOG):
            print(line[-100:])
        time.sleep(1)


if __name__ == "__main__":
    main()
