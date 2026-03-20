#!/usr/bin/env python3
"""实时数据面板后端服务。"""

import json
import math
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
MAX_POOL_SIZE = 80
MIN_POOL_SCORE = 3.2

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "data"
HTML_PATH = SCRIPT_DIR / "dashboard.html"
ALT_DATA_DIR = Path.home() / ".openclaw" / "workspace-execute" / "data"

SOURCE_WEIGHTS = {
    "funding_positive": 1.0,
    "funding_negative": 1.0,
    "ls_ratio_increase": 1.2,
    "ls_ratio_decrease": 1.2,
    "price_1440m_increase": 1.0,
    "price_1440m_decrease": 1.0,
    "oi_1440m_increase": 1.0,
    "oi_1440m_decrease": 1.0,
    "oi_1m_hot": 2.0,
    "oi_1m_long_bias": 1.5,
    "oi_1m_short_bias": 1.5,
}

MIN_SIGNAL_THRESHOLD = {
    "funding_positive": 0.01,   # 资金费率绝对值(%)最小阈值
    "funding_negative": 0.01,
    "ls_ratio_increase": 1.5,   # 多空比变化(%)最小阈值
    "ls_ratio_decrease": 1.5,
    "price_1440m_increase": 2.0,  # 周期涨跌幅(%)最小阈值
    "price_1440m_decrease": 2.0,
    "oi_1440m_increase": 2.0,
    "oi_1440m_decrease": 2.0,
    "oi_1m_hot": 3.5,           # 1m 强度阈值
    "oi_1m_long_bias": 3.5,
    "oi_1m_short_bias": 3.5,
}


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


def resolve_oi_1m_db() -> Path:
    """
    1m OI 信号库路径兼容：
    - 优先 data/oi_1m_signals.db
    - 其次 ~/.openclaw/workspace-execute/data/oi_1m_signals.db
    """
    primary = DATA_DIR / "oi_1m_signals.db"
    if primary.exists():
        return primary
    fallback = ALT_DATA_DIR / "oi_1m_signals.db"
    return fallback


def get_recent_oi_1m_candidates(top_n: int = TOP_N, lookback_minutes: int = 30) -> Tuple[Dict, Dict]:
    """
    从 1m OI 信号库提取近期候选标的：
    - hot: 最近窗口内强异动
    - long_bias: oi_change > 0 且 price_change > 0
    - short_bias: oi_change > 0 且 price_change < 0
    """
    db_path = resolve_oi_1m_db()
    if not db_path.exists():
        return {"hot": [], "long_bias": [], "short_bias": []}, get_db_meta(db_path, "oi_1m_signals")

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cutoff = int(time.time()) - lookback_minutes * 60
    cur.execute(
        """
        SELECT t.symbol, t.ts, t.oi_change, t.price_change, t.buy_ratio, t.volume_usdt
        FROM oi_1m_signals t
        INNER JOIN (
            SELECT symbol, MAX(ts) AS max_ts
            FROM oi_1m_signals
            WHERE ts >= ?
            GROUP BY symbol
        ) latest
        ON t.symbol = latest.symbol AND t.ts = latest.max_ts
        ORDER BY t.ts DESC;
        """,
        (cutoff,),
    )
    rows = cur.fetchall()
    conn.close()

    latest_by_symbol: Dict[str, Dict] = {}
    for symbol, ts, oi_change, price_change, buy_ratio, volume_usdt in rows:
        oi_change = float(oi_change or 0.0)
        price_change = float(price_change or 0.0)
        buy_ratio = float(buy_ratio or 0.0)
        volume_usdt = float(volume_usdt or 0.0)
        # 强度打分：OI变化主导 + 价格变化 + 成交偏置 + 体量
        strength = abs(oi_change) * 100 + abs(price_change) * 2 + abs(buy_ratio - 1.0) * 10 + math.log10(max(volume_usdt, 1.0))
        latest_by_symbol[symbol] = {
            "symbol": symbol,
            "ts": int(ts),
            "oi_change": round(oi_change, 4),
            "price_change": round(price_change, 4),
            "buy_ratio": round(buy_ratio, 4),
            "volume_usdt": round(volume_usdt, 2),
            "strength": round(strength, 4),
        }

    all_rows = list(latest_by_symbol.values())
    all_rows.sort(key=lambda x: x["strength"], reverse=True)
    hot = all_rows[:top_n]

    long_bias = [x for x in all_rows if x["oi_change"] > 0 and x["price_change"] > 0][:top_n]
    short_bias = [x for x in all_rows if x["oi_change"] > 0 and x["price_change"] < 0][:top_n]

    meta = {"updated_at": None, "data_age_sec": None}
    if all_rows:
        latest_ts = max(x["ts"] for x in all_rows)
        meta = {"updated_at": ts_to_str(latest_ts), "data_age_sec": max(0, int(time.time()) - latest_ts)}

    return {"hot": hot, "long_bias": long_bias, "short_bias": short_bias}, meta


def build_trading_pool(funding: Dict, ls_ratio: Dict, price: Dict, oi: Dict, oi_1m: Dict) -> Dict:
    """
    交易池准入逻辑（不是“所有前十都入池”）：
    1) 先做单源阈值过滤（各来源有最小有效信号阈值）
    2) 再做跨源打分聚合（source_weight + metric_bonus）
    3) 满足以下其一才入池：
       - source_count >= 2（多源共振）
       - pool_score >= MIN_POOL_SCORE（强单源）
       - 含 oi_1m_hot 且该源通过阈值（短线强异动）
    """
    sources: Dict[str, set] = {}
    metrics: Dict[str, List[float]] = {}

    def add_rows(tag: str, rows: List[Dict], metric_key: str) -> None:
        for row in rows:
            symbol = row.get("symbol")
            if not symbol:
                continue
            metric = float(row.get(metric_key, 0.0) or 0.0)
            threshold = MIN_SIGNAL_THRESHOLD.get(tag, 0.0)
            if abs(metric) < threshold:
                continue
            if symbol not in sources:
                sources[symbol] = set()
            sources[symbol].add(tag)
            metrics.setdefault(symbol, []).append(abs(metric))

    add_rows("funding_positive", funding.get("positive", []), "rate")
    add_rows("funding_negative", funding.get("negative", []), "rate")
    add_rows("ls_ratio_increase", ls_ratio.get("increase", []), "change_pct")
    add_rows("ls_ratio_decrease", ls_ratio.get("decrease", []), "change_pct")
    add_rows("price_1440m_increase", price.get("1440m", {}).get("increase", []), "change_pct")
    add_rows("price_1440m_decrease", price.get("1440m", {}).get("decrease", []), "change_pct")
    add_rows("oi_1440m_increase", oi.get("1440m", {}).get("increase", []), "change_pct")
    add_rows("oi_1440m_decrease", oi.get("1440m", {}).get("decrease", []), "change_pct")
    add_rows("oi_1m_hot", oi_1m.get("hot", []), "strength")
    add_rows("oi_1m_long_bias", oi_1m.get("long_bias", []), "strength")
    add_rows("oi_1m_short_bias", oi_1m.get("short_bias", []), "strength")

    pool = []
    for symbol, tags in sources.items():
        sorted_tags = sorted(list(tags))
        source_score = sum(SOURCE_WEIGHTS.get(tag, 1.0) for tag in sorted_tags)
        metric_bonus = min(2.5, (sum(metrics.get(symbol, [])) / max(len(metrics.get(symbol, [])), 1)) / 10.0)
        pool_score = round(source_score + metric_bonus, 4)
        is_stage2_fast = "oi_1m_hot" in tags
        if len(tags) < 2 and pool_score < MIN_POOL_SCORE and not is_stage2_fast:
            continue
        pool.append(
            {
                "symbol": symbol,
                "sources": sorted_tags,
                "source_count": len(tags),
                "pool_score": pool_score,
                "metric_avg_abs": round(sum(metrics.get(symbol, [])) / max(len(metrics.get(symbol, [])), 1), 4),
                "entry_mode": "multi_source" if len(tags) >= 2 else ("fast_track_1m" if is_stage2_fast else "score_gate"),
            }
        )

    pool.sort(key=lambda x: (-x["pool_score"], -x["source_count"], x["symbol"]))
    pool = pool[:MAX_POOL_SIZE]
    return {
        "symbols": pool,
        "total": len(pool),
        "coverage_note": "交易池基于多源阈值过滤+打分准入；非所有前十自动入池。",
        "pool_rules": {
            "min_pool_score": MIN_POOL_SCORE,
            "max_pool_size": MAX_POOL_SIZE,
            "source_weights": SOURCE_WEIGHTS,
            "min_signal_threshold": MIN_SIGNAL_THRESHOLD,
        },
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
    oi_1m, oi_1m_meta = get_recent_oi_1m_candidates()

    payload = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "funding": funding,
        "ls_ratio": ls_ratio,
        "price": price,
        "oi": oi,
        "oi_1m": oi_1m,
        "trading_pool": build_trading_pool(funding, ls_ratio, price, oi, oi_1m),
        "meta": {
            "funding": {"updated_at": funding["updated_at"], "data_age_sec": funding["data_age_sec"]},
            "ls_ratio": {"updated_at": ls_ratio["updated_at"], "data_age_sec": ls_ratio["data_age_sec"]},
            "price": price_meta,
            "oi": oi_meta,
            "oi_1m": oi_1m_meta,
            "periods": [f"{p}m" for p in PERIODS],
            "top_n": TOP_N,
        },
    }
    CACHE["data"] = payload
    CACHE["time"] = time.time()
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
