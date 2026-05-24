#!/usr/bin/env python3
import curses
import json
import math
import time


STATE = "/tmp/air_state.json"


def read_state():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        return {"status": "sin datos", "error": str(exc)}


def put(stdscr, row, col, text, attr=0):
    height, width = stdscr.getmaxyx()
    if row >= height or col >= width:
        return
    stdscr.addstr(row, col, text[: max(0, width - col - 1)], attr)


def gauge(value, low, high, width=28, reverse=False):
    if value is None:
        return "?" * width
    ratio = (float(value) - low) / (high - low)
    ratio = max(0.0, min(1.0, ratio))
    if reverse:
        ratio = 1.0 - ratio
    filled = int(round(ratio * width))
    return "#" * filled + "-" * (width - filled)


def fmt(value, digits=1, suffix=""):
    if value is None:
        return "--"
    return f"{float(value):.{digits}f}{suffix}"


def draw_panel(stdscr, state):
    temp = state.get("temp")
    hum = state.get("hum")
    score = state.get("air_score")
    gas = state.get("gas_med_1m") or state.get("gas")
    air_state = state.get("state", "?")
    age = time.time() - float(state.get("updated_at", 0) or 0)

    temp_bar = gauge(temp, 15, 40, 26)
    hum_bar = gauge(hum, 20, 80, 26)
    air_bar = gauge(score, 0, 100, 26)

    art = [
        "             AIR SENSOR NODE",
        "        .-----------------------.",
        "       /  BME680 ENVIRONMENT     \\",
        "      |   .----.   .----.   .-.   |",
        "      |   |TMP |   |HUM |  (AQ)   |",
        "      |   '----'   '----'   '-'   |",
        "      |      ))  ))  ))  ))       |",
        "       \\_________________________/",
        "             |  192.168.0.149",
        "",
        f" Air     {fmt(score, 1):>6}  {air_state:<7} [{air_bar}]",
        f" Temp    {fmt(temp, 1, ' C'):>8}       [{temp_bar}]",
        f" Hum     {fmt(hum, 1, ' %'):>8}       [{hum_bar}]",
        f" Gas  {fmt(gas / 1000 if gas else None, 0, ' kOhm'):>10}",
        "",
        f" Sample  {state.get('ts', '--')}",
        f" Local   {state.get('local_time', '--:--:--')}  age {age:.1f}s",
        f" Status  {state.get('status', '?')}",
    ]

    if state.get("error"):
        art.append(f" Error   {state['error']}")

    for row, line in enumerate(art):
        attr = curses.A_BOLD if row in (0, 10) else 0
        put(stdscr, row, 0, line, attr)


def draw(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    while True:
        if stdscr.getch() in (ord("q"), ord("Q")):
            break

        state = read_state()
        stdscr.erase()
        height, width = stdscr.getmaxyx()

        if width < 55 or height < 12:
            put(
                stdscr,
                0,
                0,
                f"AIR {fmt(state.get('air_score'), 1)} {state.get('state', '?')} "
                f"T {fmt(state.get('temp'), 1)}C H {fmt(state.get('hum'), 1)}%",
            )
            put(stdscr, 1, 0, f"{state.get('local_time', '--:--:--')} {state.get('status', '?')}")
        else:
            draw_panel(stdscr, state)

        stdscr.refresh()
        time.sleep(0.5)


if __name__ == "__main__":
    curses.wrapper(draw)
