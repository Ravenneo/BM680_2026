#!/usr/bin/env python3
import curses
import json
import math
import time


STATE = "/tmp/geiger_state.json"


def read_state():
    try:
        with open(STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"status": "sin datos"}


def put(stdscr, row, col, text, attr=0):
    height, width = stdscr.getmaxyx()
    if row >= height or col >= width:
        return
    stdscr.addstr(row, col, text[: max(0, width - col - 1)], attr)


def draw_geiger(stdscr, cpm, usv, total, age, state):
    height, width = stdscr.getmaxyx()
    scale_max = max(120, int(math.ceil(max(cpm, 1) / 60.0) * 60))
    meter_width = min(29, max(12, width - 34))
    needle_pos = min(meter_width - 1, int((cpm / scale_max) * (meter_width - 1)))
    scale = "." * needle_pos + "^" + "." * (meter_width - needle_pos - 1)

    status = "OK"
    if usv >= 1.0:
        status = "ALTO"
    elif usv >= 0.3:
        status = "ELEVADO"

    art = [
        "       GEIGER-MULLER COUNTER",
        "  .-------------------------------.",
        f" /  CPM {cpm:>5}  [{scale}]  \\",
        f"|   uSv/h {usv:>5.2f}    TOTAL {total:<6} |",
        "|   .----.      .----------.      |",
        "|   | () |------|  PROBE   |======|====",
        "|   '----'      '----------'      |",
        " '-------------------------------'",
    ]

    for row, line in enumerate(art):
        put(stdscr, row, 0, line, curses.A_BOLD if row == 0 else 0)

    if height > 9:
        bar_width = max(10, width - 10)
        filled = min(bar_width, int((cpm / scale_max) * bar_width))
        bar = "#" * filled + "-" * (bar_width - filled)
        put(stdscr, 9, 0, f"[{bar}]")

    info = f"{status}  {state.get('time', '--:--:--')}  {age:.1f}s  q=cerrar"
    put(stdscr, min(height - 1, 11), 0, info)


def draw(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    while True:
        if stdscr.getch() in (ord("q"), ord("Q")):
            break

        state = read_state()
        height, width = stdscr.getmaxyx()
        stdscr.erase()

        cpm = int(state.get("cpm", 0) or 0)
        usv = float(state.get("usv_h", 0.0) or 0.0)
        total = int(state.get("total", 0) or 0)
        age = time.time() - float(state.get("updated_at", 0) or 0)

        if width < 50 or height < 12:
            put(stdscr, 0, 0, f"CPM {cpm}  {usv:.2f} uSv/h  total {total}")
            put(stdscr, 1, 0, f"{state.get('time', '--:--:--')}  {age:.1f}s")
        else:
            draw_geiger(stdscr, cpm, usv, total, age, state)

        stdscr.refresh()
        time.sleep(0.25)


if __name__ == "__main__":
    curses.wrapper(draw)
