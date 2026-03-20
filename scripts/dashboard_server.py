#!/usr/bin/env python3
"""实时数据面板后端服务。"""

import json
import os
import sqlite3
import time
from bisect import bisect_right
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, List, Tuple

PORT = int(os.environ.get("DASHBOARD_PORT", "8888"))
PERIODS = [15, 60, 240, 1440]
TOP_N = 10

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "data"
HTML_PATH = SCRIPT_DIR / "dashboard.html"


def ts_to_str(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def mtime_to_meta(path: Path) -> Dict:
    if not path.exists():
        return {"updated_at": None, "data_age_sec": None}
    mtime = int(path.stat().st_mtime)
    return {"updated_at": ts_to_str(mtime), "data_age_sec": max(0, int(time.time()) - mtime)}


def get_db_latest_ts(db_path: Path, table: str) -> int:
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(f"SELECT MAX(ts) FROM {table};")
    row = cur.fetchone()
    conn.close()
    return int(row[0]) if row and row[0] is not None else 0


def get_db_meta(db_path: Path, table: str) -> Dict:
    latest = get_db_latest_ts(db_path, table)
    if latest <= 0:
        return {"updated_at": None, "data_age_sec": None}
    return {"updated_at": ts_to_str(latest), "data_age_sec": max(0, int(time.time()) - latest)}


def parse_funding_report() -> Dict:
    path = DATA_DIR / "funding_rate_report.txt"
    positive: List[Dict] = []
    negative: List[Dict] = []
    if not path.exists():
        return {"positive": positive, "negative": negative, **mtime_to_meta(path)}

    text = path.read_text(encoding="utf-8", errors="ignore")
    section = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if "正费率" in line:
            section = "positive"
            continue
        if "负费率" in line:
            section = "negative"
            continue
        if "|" not in line or "交易对" in line or "---" in line:
            continue

        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        symbol = parts[1]
        rate_text = parts[2].replace("%", "").replace("*", "").strip()
        try:
            rate = float(rate_text)
        except ValueError:
            continue

        row = {"symbol": symbol, "rate": round(rate, 4)}
        if section == "positive":
            positive.append(row)
        elif section == "negative":
            negative.append(row)

    return {
        "positive": positive[:TOP_N],
        "negative": negative[:TOP_N],
        **mtime_to_meta(path),
    }


def parse_ls_ratio() -> Dict:
    path = DATA_DIR / "ls_ratio_changes.json"
    if not path.exists():
        return {"increase": [], "decrease": [], **mtime_to_meta(path)}

    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        rows = []

    parsed = []
    for row in rows:
        try:
            parsed.append(
                {
                    "symbol": row["symbol"],
                    "cur_ratio": round(float(row["cur_ratio"]), 4),
                    "prev_ratio": round(float(row["prev_ratio"]), 4),
                    "change_pct": round(float(row["change_pct"]), 4),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue

    parsed.sort(key=lambda x: x["change_pct"], reverse=True)
    increase = parsed[:TOP_N]
    decrease = list(reversed(parsed[-TOP_N:]))
    return {"increase": increase, "decrease": decrease, **mtime_to_meta(path)}


def get_period_changes(db_path: Path, table: str, value_col: str) -> Tuple[Dict, Dict]:
    if not db_path.exists():
        return {f"{p}m": {"increase": [], "decrease": []} for p in PERIODS}, get_db_meta(db_path, table)

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    now = int(time.time())
    window_start = now - (max(PERIODS) + 120) * 60
    cur.execute(
        f"""
        SELECT symbol, ts, {value_col}
        FROM {table}
        WHERE ts >= ?
        ORDER BY symbol, ts;
        """,
        (window_start,),
    )
    rows = cur.fetchall()
    conn.close()

    series: Dict[str, List[Tuple[int, float]]] = {}
    for symbol, ts, value in rows:
        series.setdefault(symbol, []).append((int(ts), float(value)))
    indexed = {}
    for symbol, points in series.items():
        indexed[symbol] = {
            "points": points,
            "ts_list": [x[0] for x in points],
        }

    out = {}
    for period in PERIODS:
        past_target = now - period * 60
        rows = []
        for symbol, entry in indexed.items():
            points = entry["points"]
            if not points:
                continue
            current_ts, current_value = points[-1]
            if current_ts <= 0:
                continue
            ts_list = entry["ts_list"]
            idx = bisect_right(ts_list, past_target) - 1
            if idx < 0:
                continue
            old_value = points[idx][1]
            if old_value <= 0:
                continue
            change_pct = (current_value - old_value) / old_value * 100
            rows.append({"symbol": symbol, "change_pct": round(change_pct, 2)})

        rows.sort(key=lambda x: x["change_pct"], reverse=True)
        out[f"{period}m"] = {
            "increase": rows[:TOP_N],
            "decrease": list(reversed(rows[-TOP_N:])),
        }

    return out, get_db_meta(db_path, table)


def build_trading_pool(funding: Dict, ls_ratio: Dict, price: Dict, oi: Dict) -> Dict:
    sources: Dict[str, set] = {}

    def add_rows(tag: str, rows: List[Dict]) -> None:
        for row in rows:
            symbol = row.get("symbol")
            if not symbol:
                continue
            if symbol not in sources:
                sources[symbol] = set()
            sources[symbol].add(tag)

    add_rows("funding_positive", funding.get("positive", []))
    add_rows("funding_negative", funding.get("negative", []))
    add_rows("ls_ratio_increase", ls_ratio.get("increase", []))
    add_rows("ls_ratio_decrease", ls_ratio.get("decrease", []))
    add_rows("price_1440m_increase", price.get("1440m", {}).get("increase", []))
    add_rows("price_1440m_decrease", price.get("1440m", {}).get("decrease", []))
    add_rows("oi_1440m_increase", oi.get("1440m", {}).get("increase", []))
    add_rows("oi_1440m_decrease", oi.get("1440m", {}).get("decrease", []))

    pool = [
        {"symbol": symbol, "sources": sorted(list(tags)), "source_count": len(tags)}
        for symbol, tags in sources.items()
    ]
    pool.sort(key=lambda x: (-x["source_count"], x["symbol"]))
    return {
        "symbols": pool,
        "total": len(pool),
        "coverage_note": "24h交易池基于当前可得榜单快照与1440m周期并集构建。",
    }


CACHE = {"data": None, "time": 0}
CACHE_TTL = 30  # 30秒缓存

def build_payload() -> Dict:
    global CACHE
    if CACHE["data"] and time.time() - CACHE["time"] < CACHE_TTL:
        return CACHE["data"]
    
    funding = parse_funding_report()
    ls_ratio = parse_ls_ratio()

    price_db = DATA_DIR / "price_history.db"
    oi_db = DATA_DIR / "oi_history.db"
    price, price_meta = get_period_changes(price_db, "price_history", "price")
    oi, oi_meta = get_period_changes(oi_db, "oi_history", "oi")

    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "funding": funding,
        "ls_ratio": ls_ratio,
        "price": price,
        "oi": oi,
        "trading_pool": build_trading_pool(funding, ls_ratio, price, oi),
        "meta": {
            "funding": {"updated_at": funding["updated_at"], "data_age_sec": funding["data_age_sec"]},
            "ls_ratio": {"updated_at": ls_ratio["updated_at"], "data_age_sec": ls_ratio["data_age_sec"]},
            "price": price_meta,
            "oi": oi_meta,
            "periods": [f"{p}m" for p in PERIODS],
            "top_n": TOP_N,
        },
    }
    return payload


class Handler(BaseHTTPRequestHandler):
    def _write_json(self, status: int, data: Dict) -> None:
        self.send_response(status)
        self.send_header("Content-type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        if self.path in ["/", "/dashboard.html"]:
            if not HTML_PATH.exists():
                self._write_json(500, {"error": "dashboard.html not found"})
                return
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PATH.read_text(encoding="utf-8").encode("utf-8"))
            return

        if self.path.startswith("/api"):
            self._write_json(200, build_payload())
            return

        if self.path == "/health":
            self._write_json(200, {"status": "ok", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            return

        self._write_json(404, {"error": "not found"})


if __name__ == "__main__":
    print(f"启动: http://localhost:{PORT}")
    HTTPServer(("", PORT), Handler).serve_forever()
