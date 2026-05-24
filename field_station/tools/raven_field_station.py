#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

try:
    from rich import box
    from rich.align import Align
    from rich.console import Console, Group
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ModuleNotFoundError:
    print("Rich is required for RAVEN FIELD STATION.")
    print("Install it with:")
    print("  python3 -m pip install rich")
    raise SystemExit(1)


BASE_DIR = Path(__file__).resolve().parents[1]
GEIGER_STATE = Path("/tmp/geiger_state.json")
AIR_STATE = Path("/tmp/air_state.json")
GEIGER_LOG = Path("/tmp/geiger_serial.log")
AIR_LOG = Path("/tmp/air_sensor.log")
REFRESH_SECONDS = 0.5
HISTORY_SIZE = 42


def now_ts() -> float:
    return time.time()


def fmt(value, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "-"


def fmt_int(value, suffix: str = "") -> str:
    if value is None:
        return "-"
    try:
        return f"{int(value)}{suffix}"
    except (TypeError, ValueError):
        return "-"


def safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value):
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def read_json(path: Path) -> tuple[dict, str]:
    if not path.exists():
        return {}, "WAITING"
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return {}, "WAITING"
    if not raw:
        return {}, "WAITING"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}, "BAD JSON"
    if not isinstance(data, dict):
        return {}, "BAD JSON"
    return data, "OK"


def tail_lines(path: Path, count: int) -> list[str]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []
    return [line.strip() for line in lines[-count:] if line.strip()]


def age_from_state(state: dict) -> float | None:
    updated = safe_float(state.get("updated_at"))
    if updated is not None:
        return max(0.0, now_ts() - updated)
    return None


def status_by_age(age: float | None, online: float = 12.0, stale: float = 60.0) -> str:
    if age is None:
        return "WAITING"
    if age <= online:
        return "ONLINE"
    if age <= stale:
        return "STALE"
    return "OFFLINE"


def geiger_status(state: dict, age: float | None) -> str:
    if age is None or age > 15:
        return "STALE"
    dose = safe_float(state.get("usv_h")) or 0.0
    cpm = safe_int(state.get("cpm")) or 0
    if dose >= 1.0 or cpm >= 180:
        return "ALERT"
    if dose >= 0.3 or cpm >= 60:
        return "WATCH"
    return "NORMAL"


def status_style(status: str) -> str:
    return {
        "ONLINE": "bold green",
        "NORMAL": "bold green",
        "GOOD": "bold green",
        "OK": "bold yellow",
        "WATCH": "bold yellow",
        "STALE": "bold orange3",
        "WAITING": "bold cyan",
        "BAD JSON": "bold red",
        "OFFLINE": "bold red",
        "ALERT": "bold red",
        "BAD": "bold red",
        "WARMUP": "bold cyan",
    }.get(status, "bold white")


def bar(value, low: float, high: float, width: int = 24, style: str = "green") -> Text:
    text = Text()
    numeric = safe_float(value)
    if numeric is None or high <= low:
        text.append("?" * width, style="dim")
        return text
    ratio = max(0.0, min(1.0, (numeric - low) / (high - low)))
    filled = int(round(ratio * width))
    text.append("█" * filled, style=style)
    text.append("░" * (width - filled), style="grey35")
    return text


def sparkline(values: deque, width: int = 28) -> str:
    clean = [safe_float(v) for v in values]
    clean = [v for v in clean if v is not None and math.isfinite(v)]
    if not clean:
        return "·" * width
    clean = clean[-width:]
    low = min(clean)
    high = max(clean)
    glyphs = "▁▂▃▄▅▆▇█"
    if high == low:
        return glyphs[3] * len(clean)
    return "".join(glyphs[int((v - low) / (high - low) * (len(glyphs) - 1))] for v in clean)


def append_history(history: dict[str, deque], key: str, value, marker) -> None:
    numeric = safe_float(value)
    if numeric is None:
        return
    marker_key = f"_{key}_marker"
    if history.get(marker_key) == marker:
        return
    history[key].append(numeric)
    history[marker_key] = marker


def make_header() -> Panel:
    stamp = datetime.now().strftime("%H:%M:%S")
    title = Text()
    title.append(" RAVEN FIELD STATION ", style="bold bright_cyan")
    title.append("| Environmental + Radiation Telemetry ", style="bright_white")
    title.append("| NODE JACK ONLINE ", style="bold green")
    title.append(f"| {stamp}", style="dim")
    return Panel(Align.center(title), box=box.DOUBLE, border_style="bright_cyan", padding=(0, 1))


def metric_row(label: str, value: str, state: str, visual: Text | str) -> Text:
    line = Text()
    line.append(f"{label:<11} ")
    line.append(f"{value:>10}  ", style="bold bright_white")
    if state:
        line.append(f"{state:<7} ", style=status_style(state))
    else:
        line.append("        ")
    if isinstance(visual, Text):
        line.append_text(visual)
    else:
        line.append(str(visual))
    return line


def make_air_panel(state: dict, json_status: str, history: dict[str, deque]) -> Panel:
    age = age_from_state(state)
    link_status = status_by_age(age)
    score = safe_float(state.get("air_score"))
    temp = safe_float(state.get("temp"))
    hum = safe_float(state.get("hum"))
    gas = safe_float(state.get("gas_med_1m") or state.get("gas"))
    air_state = str(state.get("state", "-"))
    marker = state.get("ts") or state.get("updated_at")

    append_history(history, "air_score", score, marker)
    append_history(history, "temp", temp, marker)
    append_history(history, "hum", hum, marker)

    status_line = Text()
    status_line.append("BME680 ENVIRONMENT", style="bold bright_white")
    status_line.append("   Status: ")
    status_line.append(link_status, style=status_style(link_status))
    status_line.append(f"   JSON: {json_status}", style=status_style(json_status))
    status_line.append(f"   Sample age: {fmt(age, 1, 's')}")

    rows = Table.grid(expand=True)
    rows.add_row(status_line)
    rows.add_row("")
    rows.add_row(metric_row("Air Score", fmt(score, 1), air_state, bar(score, 0, 100, style="green")))
    rows.add_row(metric_row("Temp", fmt(temp, 1, " C"), "", bar(temp, 15, 40, style="orange3")))
    rows.add_row(metric_row("Humidity", fmt(hum, 1, " %"), "", bar(hum, 20, 80, style="cyan")))
    rows.add_row(metric_row("Gas", fmt(gas / 1000 if gas else None, 0, " kOhm"), "", bar(gas, 1000000, 3500000, style="magenta")))
    rows.add_row("")
    rows.add_row(f"Air trend   [green]{sparkline(history['air_score'])}[/]")
    rows.add_row(f"Temp trend  [orange3]{sparkline(history['temp'])}[/]")
    rows.add_row(f"Hum trend   [cyan]{sparkline(history['hum'])}[/]")
    rows.add_row("")
    rows.add_row(f"Sample      {state.get('ts', '-')}")

    return Panel(rows, title="AIR SENSOR NODE", box=box.ROUNDED, border_style="green")


def geiger_gauge(cpm: int | None, width: int = 31) -> Text:
    max_cpm = max(120, int(math.ceil(max(cpm or 0, 1) / 60.0) * 60))
    ratio = max(0.0, min(1.0, (cpm or 0) / max_cpm))
    pos = min(width - 1, int(ratio * (width - 1)))
    text = Text()
    for idx in range(width):
        text.append("▲" if idx == pos else "─", style="bold bright_yellow" if idx == pos else "grey50")
    text.append(f" 0-{max_cpm} CPM", style="dim")
    return text


def make_geiger_panel(state: dict, json_status: str, history: dict[str, deque], pulse_frame: int) -> Panel:
    age = age_from_state(state)
    status = geiger_status(state, age)
    cps = safe_int(state.get("cps"))
    cpm = safe_int(state.get("cpm"))
    dose = safe_float(state.get("usv_h"))
    total = safe_int(state.get("total"))
    ms = safe_int(state.get("ms"))
    marker = state.get("ms") or state.get("updated_at")

    append_history(history, "cpm", cpm, marker)

    pulse = "☢ PULSE" if (cps or 0) > 0 and pulse_frame % 2 == 0 else "idle"
    pulse_style = "bold bright_yellow" if "PULSE" in pulse else "dim"

    rows = Table.grid(expand=True)
    status_line = Text()
    status_line.append("Status: ")
    status_line.append(status, style=status_style(status))
    status_line.append("   Serial: ")
    status_line.append(state.get("port", "/dev/ttyUSB0"), style="bright_white")
    status_line.append(f"   JSON: {json_status}", style=status_style(json_status))
    status_line.append(f"   Age: {fmt(age, 1, 's')}")
    rows.add_row(status_line)
    rows.add_row("")

    metrics = Table.grid(expand=True)
    metrics.add_column(ratio=1)
    metrics.add_column(ratio=1)
    metrics.add_column(ratio=1)
    metrics.add_row(f"CPM: [bold bright_yellow]{fmt_int(cpm)}[/]", f"CPS: [bold]{fmt_int(cps)}[/]", f"Total: [bold]{fmt_int(total)}[/]")
    metrics.add_row(f"Dose: [bold cyan]{fmt(dose, 2, ' uSv/h')}[/]", f"ms: [dim]{fmt_int(ms)}[/]", f"Pulse: [{pulse_style}]{pulse}[/]")
    rows.add_row(metrics)
    rows.add_row("")
    rows.add_row(Text.assemble(("Activity  "), bar(cpm, 0, 120, style="bright_yellow")))
    rows.add_row(Text.assemble(("Needle    "), geiger_gauge(cpm)))
    rows.add_row(f"CPM trend [bright_yellow]{sparkline(history['cpm'], 34)}[/]")

    return Panel(rows, title="GEIGER-MÜLLER COUNTER", box=box.ROUNDED, border_style="bright_yellow")


def make_health_panel(geiger_json: str, air_json: str, start: float) -> Panel:
    runtime = int(now_ts() - start)
    hours, rem = divmod(runtime, 3600)
    minutes, seconds = divmod(rem, 60)
    line = Text()
    line.append("Geiger JSON: ")
    line.append(geiger_json, style=status_style(geiger_json))
    line.append(" | Air JSON: ")
    line.append(air_json, style=status_style(air_json))
    line.append(f" | Last refresh: {datetime.now().strftime('%H:%M:%S')}")
    line.append(f" | Runtime: {hours:02d}:{minutes:02d}:{seconds:02d}")
    line.append(f" | Base: {BASE_DIR}", style="dim")
    return Panel(line, title="SESSION HEALTH", box=box.ROUNDED, border_style="bright_blue")


def clean_air_line(line: str) -> str:
    prefix, _, payload = line.partition(" ")
    _, _, json_part = line.partition("{")
    if not json_part:
        return line
    try:
        data = json.loads("{" + json_part)
    except json.JSONDecodeError:
        return line
    ts = data.get("ts", prefix)
    return (
        f"{ts} air_score={fmt(data.get('air_score'), 1)} "
        f"temp={fmt(data.get('temp'), 1)} hum={fmt(data.get('hum'), 1)} "
        f"state={data.get('state', '-')}"
    )


def make_event_stream() -> Panel:
    events: list[tuple[str, str]] = []
    for line in tail_lines(GEIGER_LOG, 5):
        events.append(("GEIGER", line))
    for line in tail_lines(AIR_LOG, 5):
        events.append(("AIR", clean_air_line(line)))

    events = events[-8:]
    table = Table.grid(expand=True)
    table.add_column(width=8)
    table.add_column(ratio=1)
    if not events:
        table.add_row("SYSTEM", "[dim]Waiting for log lines...[/]")
    for source, line in events:
        style = "bright_yellow" if source == "GEIGER" else "green"
        table.add_row(f"[bold {style}]{source}[/]", line)
    return Panel(table, title="EVENT STREAM", box=box.ROUNDED, border_style="magenta")


def build_dashboard(history: dict[str, deque], start: float, pulse_frame: int):
    geiger, geiger_json = read_json(GEIGER_STATE)
    air, air_json = read_json(AIR_STATE)

    main = Table.grid(expand=True)
    main.add_column(ratio=1)
    main.add_column(ratio=1)

    right = Table.grid(expand=True)
    right.add_row(make_geiger_panel(geiger, geiger_json, history, pulse_frame))
    right.add_row(make_health_panel(geiger_json, air_json, start))

    main.add_row(make_air_panel(air, air_json, history), right)

    return Group(
        make_header(),
        main,
        make_event_stream(),
    )


def make_history() -> dict[str, deque]:
    return {
        "air_score": deque(maxlen=HISTORY_SIZE),
        "temp": deque(maxlen=HISTORY_SIZE),
        "hum": deque(maxlen=HISTORY_SIZE),
        "cpm": deque(maxlen=HISTORY_SIZE),
    }


def main() -> int:
    console = Console()
    history = make_history()
    start = now_ts()
    pulse_frame = 0
    try:
        with Live(build_dashboard(history, start, pulse_frame), console=console, refresh_per_second=2, screen=True) as live:
            while True:
                pulse_frame += 1
                live.update(build_dashboard(history, start, pulse_frame))
                time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        console.clear()
        console.print("[bold cyan]RAVEN FIELD STATION[/] stopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
