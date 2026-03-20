# -*- coding: utf-8 -*-
"""
币安 USDT 永续合约持仓监控机器人（1m 闭合 K 版 + 智能解读 + SQLite 记录）
特性：
✅ 严格 1 分钟级别
✅ 只用【已闭合】的 1m K 线（上一根）
✅ OI 以“分钟收盘快照”的方式对齐
✅ 监控 OI 变化 + 价格变化 + 成交结构（taker 买/卖、买卖比）
✅ 超过阈值统一推送日志
✅ 智能分析：多空建仓/平仓 + 主动/被动
✅ 自动断线重连 & 异常日志
✅ 触发信号自动写入 SQLite（oi_1m.db），供交易脚本 / 前端读取
"""

import os
import time
import sqlite3
import logging
import traceback
import requests
import concurrent.futures
from datetime import datetime

# === Telegram 配置 (已禁用) ===
# TELEGRAM_BOT_TOKEN = "8242454526:AAH6ZV4ci9_rSQbuXm5q2W-exRdUeCAFEBc"
# TELEGRAM_CHAT_ID = "-4848612357"

# === 参数设置 ===
CHANGE_THRESHOLD = 0.01  # 持仓变化超过 1% 触发
BASE_URL = "https://fapi.binance.com"

# === 路径 & 日志配置 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(BASE_DIR, "1m.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# === 1m OI 信号数据库配置 (自定义路径) ===
DB_DIR = os.path.join(os.path.expanduser("~"), ".openclaw", "workspace-execute", "data")
os.makedirs(DB_DIR, exist_ok=True)
OI_DB_PATH = os.path.join(DB_DIR, "oi_1m_signals.db")

def init_oi_db():
    """初始化 1m OI 信号数据库 & 表结构"""
    conn = sqlite3.connect(OI_DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS oi_1m_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                oi_change REAL NOT NULL,
                price_change REAL,
                buy_ratio REAL,
                volume_change_base REAL,
                volume_change_quote REAL,
                volume_usdt REAL,
                taker_buy_usdt REAL,
                taker_sell_usdt REAL,
                analysis TEXT
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_oi_1m_symbol_ts ON oi_1m_signals(symbol, ts DESC);
            """
        )
        conn.commit()
        logging.info(f"oi_1m_signals.db 初始化完成，路径：{OI_DB_PATH}")
    except Exception as e:
        logging.error(f"初始化 oi_1m_signals.db 失败：{e}")
    finally:
        conn.close()

def insert_oi_signal(symbol, ts, oi_change, kdata, analysis):
    """写入一条 1m OI 信号记录"""
    try:
        conn = sqlite3.connect(OI_DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO oi_1m_signals (
                ts, symbol, oi_change, price_change, buy_ratio,
                volume_change_base, volume_change_quote, volume_usdt,
                taker_buy_usdt, taker_sell_usdt, analysis
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                int(ts), symbol, float(oi_change),
                float(kdata.get("price_change", 0.0)),
                float(kdata.get("buy_ratio", 0.0)),
                float(kdata.get("volume_change_base", 0.0)),
                float(kdata.get("volume_change_quote", 0.0)),
                float(kdata.get("volume_usdt", 0.0)),
                float(kdata.get("taker_buy_usdt", 0.0)),
                float(kdata.get("taker_sell_usdt", 0.0)),
                analysis or ""
            )
        )
        conn.commit()
    except Exception as e:
        logging.error(f"写入 oi_1m_signals 失败 {symbol}: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

def send_telegram_message(text: str):
    """Telegram 推送已禁用，仅记录日志"""
    logging.info(f"[模拟推送] {text}")
    pass

def get_usdt_symbols():
    """获取交易对列表（USDT 永续）"""
    try:
        data = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=10).json()
        symbols = [
            s["symbol"] for s in data["symbols"]
            if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL"
        ]
        return symbols
    except Exception as e:
        logging.warning(f"获取交易对失败：{e}")
        return []

def get_open_interest(symbol: str):
    """获取单个合约当前 OI（实时快照）"""
    try:
        data = requests.get(
            f"{BASE_URL}/fapi/v1/openInterest?symbol={symbol}",
            timeout=5
        ).json()
        return float(data["openInterest"])
    except Exception:
        return None

def fetch_all_open_interest(symbols):
    """批量多线程获取当前 OI 快照"""
    result = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(get_open_interest, s): s for s in symbols}
        for future in concurrent.futures.as_completed(futures):
            s = futures[future]
            try:
                oi = future.result()
                if oi is not None:
                    result[s] = oi
            except Exception:
                continue
    return result

def get_last_closed_1m(symbol: str):
    """获取上一根【已闭合】的 1m K 线数据"""
    try:
        url = f"{BASE_URL}/fapi/v1/klines?symbol={symbol}&interval=1m&limit=3"
        data = requests.get(url, timeout=5).json()
        if not data or len(data) < 3:
            return None
        prev_k = data[-3]  # 上上一根闭合 K
        last_k = data[-2]  # 上一根闭合 K

        def parse_k(k):
            open_price = float(k[1])
            high_price = float(k[2])
            low_price = float(k[3])
            close_price = float(k[4])
            volume_base = float(k[5])
            quote_volume = float(k[7])
            taker_buy_base = float(k[9])
            taker_buy_quote = float(k[10])
            taker_sell_quote = quote_volume - taker_buy_quote
            buy_ratio = (taker_buy_quote / taker_sell_quote) if taker_sell_quote > 0 else 0.0
            price_change_pct = (
                (close_price - open_price) / open_price * 100
                if open_price > 0 else 0.0
            )
            return {
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume_base": volume_base,
                "volume_usdt": quote_volume,
                "taker_buy_base": taker_buy_base,
                "taker_buy_usdt": taker_buy_quote,
                "taker_sell_usdt": taker_sell_quote,
                "buy_ratio": buy_ratio,
                "price_change": price_change_pct,
            }

        prev = parse_k(prev_k)
        last = parse_k(last_k)

        if prev["volume_base"] > 0:
            volume_change_base = (last["volume_base"] - prev["volume_base"]) / prev["volume_base"]
        else:
            volume_change_base = 0.0

        if prev["volume_usdt"] > 0:
            volume_change_quote = (last["volume_usdt"] - prev["volume_usdt"]) / prev["volume_usdt"]
        else:
            volume_change_quote = 0.0

        last["volume_change_base"] = volume_change_base
        last["volume_change_quote"] = volume_change_quote
        return last
    except Exception as e:
        logging.warning(f"{symbol} 获取闭合 1m K 失败：{e}")
        return None

def interpret_market(oi_change, price_change, buy_ratio):
    """智能解读市场"""
    small_move = 0.002
    try:
        if abs(price_change) < small_move and abs(oi_change) < small_move:
            return "⚔️ 市场震荡，暂无明显方向"
        if price_change > 0:
            strength = "🟢 主动拉高" if buy_ratio > 1.05 else "🔴 被动拉高"
            if oi_change > 0:
                return f"{strength} + 多头建仓"
            else:
                return f"{strength} + 空头平仓"
        if price_change < 0:
            strength = "🟢 主动打压" if buy_ratio < 0.95 else "🔴 被动下跌"
            if oi_change > 0:
                return f"{strength} + 空头建仓"
            else:
                return f"{strength} + 多头平仓"
        return "⚔️ 双方博弈，市场信号中性"
    except Exception:
        return "⚔️ 数据不足，暂无法判断"

def wait_until_next_minute(offset_sec: float = 1.0):
    """等待到下一个整分钟"""
    now = time.time()
    sec_in_min = now % 60
    sleep_sec = 60 - sec_in_min + offset_sec
    if sleep_sec < 0:
        sleep_sec = offset_sec
    time.sleep(sleep_sec)

def run_monitor():
    symbols = get_usdt_symbols()
    if not symbols:
        logging.error("无法获取币安合约列表，监控启动失败。")
        return
    logging.info(
        f"✅【1m 闭合 K 版】持仓监控已启动，共 {len(symbols)} 个 USDT 永续合约。\n"
        f"变化阈值：{CHANGE_THRESHOLD * 100:.2f}%（按分钟 OI 收盘对比）"
    )
    logging.info("等待对齐到下一分钟，获取基准 OI .")
    wait_until_next_minute(offset_sec=1.0)
    base_oi = fetch_all_open_interest(symbols)
    if not base_oi:
        logging.error("首次 OI 获取失败，监控无法启动。")
        return
    last_oi = base_oi
    logging.info(f"已获取基准 OI，共 {len(last_oi)} 个币种。监控正式开始。")

    while True:
        try:
            wait_until_next_minute(offset_sec=1.0)
            oi_data = fetch_all_open_interest(symbols)
            if not oi_data:
                raise ValueError("未获取到任何持仓数据")
            alert_msgs = []
            for symbol, oi_now in oi_data.items():
                oi_prev = last_oi.get(symbol)
                if oi_prev is None or oi_prev <= 0:
                    continue
                oi_change = (oi_now - oi_prev) / oi_prev
                if abs(oi_change) >= CHANGE_THRESHOLD:
                    kdata = get_last_closed_1m(symbol)
                    if kdata:
                        analysis = interpret_market(
                            oi_change, kdata["price_change"], kdata["buy_ratio"]
                        )
                        now_ts = int(time.time())
                        insert_oi_signal(symbol, now_ts, oi_change, kdata, analysis)
                        msg = (
                            f"---{symbol}---\n"
                            f"时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                            f"📊 持仓变化：{oi_change * 100:.2f}%\n"
                            f"💹 1m 收盘涨跌：{kdata['price_change']:.2f}%\n"
                            f"📈 1m 成交量变化 (张/币): {kdata['volume_change_base'] * 100:.2f}%\n"
                            f"⚔️ 买卖比：{kdata['buy_ratio']:.2f}\n"
                            f"{analysis}\n\n"
                            f"-------------------------\n"
                            f"1m 成交额变化 (USDT): {kdata['volume_change_quote'] * 100:.2f}%\n"
                            f"1m 成交额 (USDT): {kdata['volume_usdt']:.2f}\n"
                            f"主动买入额：{kdata['taker_buy_usdt']:.2f}\n"
                            f"主动卖出额：{kdata['taker_sell_usdt']:.2f}"
                        )
                    else:
                        msg = (
                            f"---{symbol}---\n"
                            f"📊 持仓变化：{oi_change * 100:.2f}%\n"
                            f"⚠️ 1m 闭合 K 数据获取失败，无法给出详细解读。"
                        )
                    alert_msgs.append(msg)
                    logging.info(msg)
            last_oi = oi_data
            if alert_msgs:
                combined_msg = "\n\n".join(alert_msgs)
                send_telegram_message(combined_msg)
                logging.info(
                    f"本轮完成，OI 快照 {len(oi_data)} 个币。产生告警 {len(alert_msgs)} 条。"
                )
        except Exception as e:
            err_msg = f"异常：{e}\n{traceback.format_exc().splitlines()[-1]}"
            logging.error(err_msg)
            send_telegram_message("⚠️ 程序异常，已尝试重连.\n" + str(e))
            time.sleep(15)
            continue

if __name__ == "__main__":
    init_oi_db()
    while True:
        try:
            run_monitor()
        except Exception as e:
            logging.error(f"主循环异常：{e}")
            send_telegram_message("🚨 主循环异常，程序已自动重启。")
            time.sleep(30)
