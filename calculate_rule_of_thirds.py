#!/usr/bin/env python3
"""Ford (F) Rule of Thirds dashboard generator.

Intraday candles are built from Yahoo Finance 1-minute regular-session data
so we can support a true 3-minute timeframe. The 15m, 30m, and 1h candles
are aggregated from the same 1-minute source for consistent session alignment.
Daily candles come from Yahoo's 1-day data.

Rule of Thirds for each candle:
    range      = high - low
    one_third  = range / 3
    1st        = low + one_third
    2nd        = low + 2 * one_third
    3rd        = low + 3 * one_third == high
"""

from __future__ import annotations

import csv
import html
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SYMBOL = "F"
COMPANY = "Ford Motor Company"
CANDLE_COUNT = 20
ET = ZoneInfo("America/New_York")
RESULTS_DIR = Path("results")
INDEX_FILE = Path("index.html")

SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)
INTRADAY_TIMEFRAMES = {
    "3m": 3,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}
TIMEFRAME_ORDER = ["3m", "15m", "30m", "1h", "1d"]


@dataclass
class Candle:
    start: datetime
    open: float
    high: float
    low: float
    close: float

    def rule(self) -> dict[str, float]:
        price_range = self.high - self.low
        one_third = price_range / 3.0
        first = self.low + one_third
        second = self.low + (2.0 * one_third)
        third = self.low + (3.0 * one_third)
        return {
            "range": price_range,
            "one_third": one_third,
            "first": first,
            "second": second,
            "third": third,
        }


def fetch_yahoo_chart(interval: str, range_: str) -> list[Candle]:
    params = urlencode(
        {
            "interval": interval,
            "range": range_,
            "includePrePost": "false",
            "events": "div,splits",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}?{params}"
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/131 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
        },
    )

    try:
        with urlopen(req, timeout=30) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Yahoo Finance request failed for {interval}/{range_}: {exc}") from exc

    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(f"Yahoo Finance error: {chart['error']}")

    results = chart.get("result") or []
    if not results:
        raise RuntimeError(f"No Yahoo Finance data returned for {SYMBOL} {interval}/{range_}")

    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators", {}).get("quote") or []
    if not indicators:
        raise RuntimeError("Yahoo Finance response did not include quote data")

    quote = indicators[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []

    candles: list[Candle] = []
    for i, ts in enumerate(timestamps):
        try:
            values = (opens[i], highs[i], lows[i], closes[i])
        except IndexError:
            continue
        if any(v is None for v in values):
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET)
        candles.append(
            Candle(
                start=dt,
                open=float(values[0]),
                high=float(values[1]),
                low=float(values[2]),
                close=float(values[3]),
            )
        )
    return candles


def is_regular_session_minute(dt: datetime) -> bool:
    if dt.weekday() >= 5:
        return False
    local_t = dt.timetz().replace(tzinfo=None)
    return SESSION_OPEN <= local_t < SESSION_CLOSE


def bucket_start(dt: datetime, minutes: int) -> datetime:
    session_start = datetime.combine(dt.date(), SESSION_OPEN, tzinfo=ET)
    elapsed_minutes = int((dt - session_start).total_seconds() // 60)
    bucket_offset = (elapsed_minutes // minutes) * minutes
    return session_start + timedelta(minutes=bucket_offset)


def aggregate_intraday(one_minute: Iterable[Candle], minutes: int) -> list[Candle]:
    groups: dict[datetime, list[Candle]] = defaultdict(list)
    for c in one_minute:
        if not is_regular_session_minute(c.start):
            continue
        groups[bucket_start(c.start, minutes)].append(c)

    aggregated: list[Candle] = []
    for start in sorted(groups):
        parts = sorted(groups[start], key=lambda c: c.start)
        aggregated.append(
            Candle(
                start=start,
                open=parts[0].open,
                high=max(c.high for c in parts),
                low=min(c.low for c in parts),
                close=parts[-1].close,
            )
        )
    return aggregated


def intraday_candle_is_closed(candle: Candle, minutes: int, now_et: datetime) -> bool:
    session_close = datetime.combine(candle.start.date(), SESSION_CLOSE, tzinfo=ET)
    nominal_end = candle.start + timedelta(minutes=minutes)
    actual_end = min(nominal_end, session_close)
    return now_et >= actual_end


def closed_daily_candles(raw_daily: Iterable[Candle], now_et: datetime) -> list[Candle]:
    result: list[Candle] = []
    for c in raw_daily:
        d = c.start.date()
        if d < now_et.date():
            result.append(c)
        elif d == now_et.date() and now_et.timetz().replace(tzinfo=None) >= SESSION_CLOSE:
            result.append(c)
    return result


def fmt(value: float) -> str:
    return f"{value:,.3f}"


def candle_time_label(candle: Candle, timeframe: str) -> str:
    if timeframe == "1d":
        return candle.start.strftime("%Y-%m-%d")
    return candle.start.strftime("%Y-%m-%d %I:%M %p ET")


def build_data() -> dict[str, list[Candle]]:
    now_et = datetime.now(ET)

    # Yahoo does not provide a native 3-minute interval, so all intraday
    # timeframes are built from regular-session 1-minute bars.
    one_minute = fetch_yahoo_chart("1m", "7d")
    data: dict[str, list[Candle]] = {}

    for label, minutes in INTRADAY_TIMEFRAMES.items():
        agg = aggregate_intraday(one_minute, minutes)
        closed = [c for c in agg if intraday_candle_is_closed(c, minutes, now_et)]
        data[label] = closed[-CANDLE_COUNT:]

    daily = fetch_yahoo_chart("1d", "6mo")
    data["1d"] = closed_daily_candles(daily, now_et)[-CANDLE_COUNT:]

    missing = [tf for tf in TIMEFRAME_ORDER if not data.get(tf)]
    if missing:
        raise RuntimeError(f"No closed candle data available for: {', '.join(missing)}")
    return data


def write_history_csv(data: dict[str, list[Candle]]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "history.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "timeframe",
                "candle_time_et",
                "open",
                "close",
                "low",
                "high",
                "range",
                "one_third",
                "1st",
                "2nd",
                "3rd",
            ]
        )
        for tf in TIMEFRAME_ORDER:
            for c in reversed(data[tf]):
                r = c.rule()
                writer.writerow(
                    [
                        tf,
                        candle_time_label(c, tf),
                        f"{c.open:.6f}",
                        f"{c.close:.6f}",
                        f"{c.low:.6f}",
                        f"{c.high:.6f}",
                        f"{r['range']:.6f}",
                        f"{r['one_third']:.6f}",
                        f"{r['first']:.6f}",
                        f"{r['second']:.6f}",
                        f"{r['third']:.6f}",
                    ]
                )


def markdown_table(tf: str, candles: list[Candle]) -> str:
    lines = [
        f"## {tf}",
        "",
        "| Candle (ET) | Low | High | 1st | 2nd | 3rd |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for c in reversed(candles):
        r = c.rule()
        lines.append(
            f"| {candle_time_label(c, tf)} | {fmt(c.low)} | {fmt(c.high)} | "
            f"{fmt(r['first'])} | {fmt(r['second'])} | {fmt(r['third'])} |"
        )
    return "\n".join(lines)


def write_latest_markdown(data: dict[str, list[Candle]]) -> None:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    content = [
        f"# {COMPANY} ({SYMBOL}) Rule of Thirds",
        "",
        f"Generated: **{generated}**",
        "",
        "Formula: **1st = Low + 1/3 range**, **2nd = Low + 2/3 range**, **3rd = High**.",
        "",
    ]
    for tf in TIMEFRAME_ORDER:
        content.append(markdown_table(tf, data[tf]))
        content.append("")
    (RESULTS_DIR / "latest.md").write_text("\n".join(content), encoding="utf-8")


def html_table(tf: str, candles: list[Candle]) -> str:
    rows = []
    for c in reversed(candles):
        r = c.rule()
        rows.append(
            "<tr>"
            f"<td>{html.escape(candle_time_label(c, tf))}</td>"
            f"<td>{fmt(c.low)}</td>"
            f"<td>{fmt(c.high)}</td>"
            f"<td class='level first'>{fmt(r['first'])}</td>"
            f"<td class='level second'>{fmt(r['second'])}</td>"
            f"<td class='level third'>{fmt(r['third'])}</td>"
            "</tr>"
        )
    return (
        "<div class='table-wrap'><table>"
        "<thead><tr><th>Candle (ET)</th><th>Low</th><th>High</th>"
        "<th>1st</th><th>2nd</th><th>3rd</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def latest_card(tf: str, candle: Candle) -> str:
    r = candle.rule()
    return f"""
    <article class="card">
      <div class="tf">{html.escape(tf)}</div>
      <div class="when">{html.escape(candle_time_label(candle, tf))}</div>
      <div class="levels">
        <div><span>1st</span><strong>{fmt(r['first'])}</strong></div>
        <div><span>2nd</span><strong>{fmt(r['second'])}</strong></div>
        <div><span>3rd</span><strong>{fmt(r['third'])}</strong></div>
      </div>
      <div class="range">Low {fmt(candle.low)} · High {fmt(candle.high)}</div>
    </article>
    """


def write_index_html(data: dict[str, list[Candle]]) -> None:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cards = "".join(latest_card(tf, data[tf][-1]) for tf in TIMEFRAME_ORDER)
    sections = "".join(
        f"<section><h2>{html.escape(tf)} — Last {len(data[tf])} closed candles</h2>{html_table(tf, data[tf])}</section>"
        for tf in TIMEFRAME_ORDER
    )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ford (F) Rule of Thirds</title>
<style>
:root {{ color-scheme: dark; --bg:#0b0f14; --panel:#121923; --line:#263242; --text:#f4f7fb; --muted:#9aa8ba; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--text); }}
main {{ width:min(1220px,94vw); margin:0 auto; padding:34px 0 70px; }}
h1 {{ margin:0 0 8px; font-size:clamp(30px,5vw,52px); letter-spacing:-0.03em; }}
.sub {{ color:var(--muted); margin-bottom:24px; line-height:1.55; }}
.formula {{ background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:14px 16px; margin-bottom:22px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(205px,1fr)); gap:12px; margin-bottom:34px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:16px; padding:18px; }}
.tf {{ font-size:22px; font-weight:800; }} .when,.range {{ color:var(--muted); font-size:12px; margin-top:4px; }}
.levels {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin-top:16px; }}
.levels div {{ border:1px solid var(--line); border-radius:10px; padding:9px; }}
.levels span {{ color:var(--muted); font-size:11px; display:block; }}
.levels strong {{ display:block; margin-top:3px; font-size:17px; }}
section {{ margin-top:36px; }} h2 {{ font-size:22px; margin-bottom:12px; }}
.table-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:14px; }}
table {{ width:100%; border-collapse:collapse; min-width:720px; background:var(--panel); }}
th,td {{ padding:11px 13px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }}
th:first-child,td:first-child {{ text-align:left; }} th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.06em; }}
tbody tr:last-child td {{ border-bottom:0; }} .level {{ font-weight:700; }}
footer {{ color:var(--muted); margin-top:32px; font-size:12px; line-height:1.5; }}
</style>
</head>
<body>
<main>
  <h1>Ford (F) Rule of Thirds</h1>
  <div class="sub">3m · 15m · 30m · 1h · 1d &nbsp;|&nbsp; Last {CANDLE_COUNT} fully closed candles per timeframe</div>
  <div class="formula"><strong>Order:</strong> 1st = Low + ⅓ range &nbsp;→&nbsp; 2nd = Low + ⅔ range &nbsp;→&nbsp; 3rd = High</div>
  <div class="cards">{cards}</div>
  {sections}
  <footer>Generated {generated}. Intraday values use regular NYSE session data (9:30 AM–4:00 PM ET). The 3m, 15m, 30m and 1h candles are aggregated from Yahoo Finance 1-minute data; 1d uses Yahoo daily data. Informational only, not financial advice.</footer>
</main>
</body>
</html>
"""
    INDEX_FILE.write_text(page, encoding="utf-8")


def main() -> int:
    try:
        data = build_data()
        write_history_csv(data)
        write_latest_markdown(data)
        write_index_html(data)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Updated {INDEX_FILE}, {RESULTS_DIR / 'latest.md'}, and {RESULTS_DIR / 'history.csv'}")
    for tf in TIMEFRAME_ORDER:
        c = data[tf][-1]
        r = c.rule()
        print(
            f"{tf:>3} | {candle_time_label(c, tf)} | "
            f"1st {fmt(r['first'])} | 2nd {fmt(r['second'])} | 3rd {fmt(r['third'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
