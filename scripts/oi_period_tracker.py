#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多周期 OI 持仓量监控脚本
功能：
- 每分钟记录当前 OI 到数据库
- 计算 15m/1h/4h/24h 的 OI 变化率
- 输出各周期 OI 变化 TOP10

使用方法:
    # 后台运行 (持续记录 OI)
    python scripts/oi_period_tracker.py --daemon
    
    # 查询当前 OI 变化 (需先运行一段时间积累数据)
    python scripts/oi_period_tracker.py --query
    
    # 后台运行 + 查询
    python scripts/oi_period_tracker.py --daemon --query
"""

import os
import sys
import time
import sqlite3
import argparse
import requests
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# === 配置 ===
BASE_URL = "https://fapi.binance.com"
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "oi_history.db")
LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "oi_tracker.log")

# 日志配置
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def init_db():
    """初始化 OI 历史数据库"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # OI 历史记录表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS oi_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            oi REAL NOT NULL,
            UNIQUE(ts, symbol)
        );
    """)
    
    # 创建索引加速查询
    cur.execute("CREATE INDEX IF NOT EXISTS idx_oi_ts ON oi_history(ts);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_oi_symbol ON oi_history(symbol);")
    
    conn.commit()
    conn.close()
    logging.info(f"OI 数据库初始化完成: {DB_PATH}")

def get_usdt_symbols():
    """获取 USDT 永续合约列表"""
    try:
        data = requests.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=10).json()
        symbols = [
            s["symbol"] for s in data["symbols"]
            if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL"
        ]
        return symbols
    except Exception as e:
        logging.error(f"获取交易对失败: {e}")
        return []

def get_open_interest(symbol):
    """获取单个币种 OI"""
    try:
        r = requests.get(f"{BASE_URL}/fapi/v1/openInterest?symbol={symbol}", timeout=5)
        if r.status_code == 200:
            return float(r.json()["openInterest"])
    except:
        pass
    return None

def fetch_all_oi(symbols):
    """批量获取所有币种 OI"""
    result = {}
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(get_open_interest, s): s for s in symbols}
        for future in as_completed(futures):
            s = futures[future]
            try:
                oi = future.result()
                if oi is not None:
                    result[s] = oi
            except:
                continue
    return result

def record_oi():
    """记录当前 OI 到数据库"""
    symbols = get_usdt_symbols()
    if not symbols:
        logging.warning("无法获取交易对列表")
        return
    
    oi_data = fetch_all_oi(symbols)
    if not oi_data:
        logging.warning("未获取到任何 OI 数据")
        return
    
    ts = int(time.time())
    # 取整到分钟
    ts = (ts // 60) * 60
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    inserted = 0
    for symbol, oi in oi_data.items():
        try:
            cur.execute(
                "INSERT OR REPLACE INTO oi_history (ts, symbol, oi) VALUES (?, ?, ?);",
                (ts, symbol, oi)
            )
            inserted += 1
        except Exception as e:
            logging.warning(f"写入失败 {symbol}: {e}")
    
    conn.commit()
    conn.close()
    
    logging.info(f"本轮记录 OI {len(oi_data)} 个币种，成功 {inserted} 条")
    return len(oi_data)

def get_oi_change(symbol, minutes):
    """获取指定时间周期的 OI 变化率
    
    minutes: 周期 (15=15m, 60=1h, 240=4h, 1440=24h)
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    now = int(time.time())
    now = (now // 60) * 60
    past = now - (minutes * 60)
    
    # 获取当前 OI
    cur.execute("SELECT oi FROM oi_history WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1;", 
                (symbol, now))
    row_now = cur.fetchone()
    if not row_now:
        conn.close()
        return None
    oi_now = row_now[0]
    
    # 获取历史 OI
    cur.execute("SELECT oi FROM oi_history WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1;", 
                (symbol, past))
    row_past = cur.fetchone()
    conn.close()
    
    if not row_past:
        return None
    
    oi_past = row_past[0]
    if oi_past <= 0:
        return None
    
    change = (oi_now - oi_past) / oi_past
    return {
        'symbol': symbol,
        'oi_now': oi_now,
        'oi_past': oi_past,
        'change': change,
        'change_pct': change * 100
    }

def query_oi_changes(top_n=10):
    """查询各周期 OI 变化 TOP10"""
    symbols = get_usdt_symbols()
    if not symbols:
        print("❌ 无法获取交易对列表")
        return
    
    # 检查数据
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT MIN(ts), MAX(ts), COUNT(DISTINCT ts) FROM oi_history;")
    row = cur.fetchone()
    conn.close()
    
    if not row or row[0] is None:
        print("❌ 数据库中暂无 OI 数据，请先运行 --daemon 记录数据")
        return
    
    min_ts, max_ts, count = row
    print(f"📊 数据范围: {datetime.fromtimestamp(min_ts)} ~ {datetime.fromtimestamp(max_ts)}")
    print(f"   记录条数: {count} 条\n")
    
    results = {}
    for minutes, name in [(15, "15分钟"), (60, "1小时"), (240, "4小时"), (1440, "24小时")]:
        changes = []
        for symbol in symbols:
            try:
                result = get_oi_change(symbol, minutes)
                if result and result['change'] is not None:
                    changes.append(result)
            except:
                continue
        
        # 排序
        changes.sort(key=lambda x: x['change'], reverse=True)
        
        results[name] = {
            'gainers': changes[:top_n],
            'losers': changes[-top_n:][::-1]
        }
    
    # 打印结果
    for period, data in results.items():
        print(f"\n{'='*60}")
        print(f"📈 {period} OI 涨幅 TOP10")
        print('='*60)
        print(f"{'#':<3} {'交易对':<15} {'当前OI':<15} {'变化率':<10}")
        print('-'*50)
        for i, d in enumerate(data['gainers'], 1):
            print(f"{i:<3} {d['symbol']:<15} {d['oi_now']:<15,.0f} {d['change_pct']:>+8.2f}%")
        
        print(f"\n{'='*60}")
        print(f"📉 {period} OI 跌幅 TOP10")
        print('='*60)
        print(f"{'#':<3} {'交易对':<15} {'当前OI':<15} {'变化率':<10}")
        print('-'*50)
        for i, d in enumerate(data['losers'], 1):
            print(f"{i:<3} {d['symbol']:<15} {d['oi_now']:<15,.0f} {d['change_pct']:>+8.2f}%")

def run_daemon(interval=60):
    """后台运行，持续记录 OI"""
    print(f"🚀 OI 记录器启动，每 {interval} 秒记录一次")
    print("   按 Ctrl+C 停止\n")
    
    init_db()
    
    while True:
        try:
            record_oi()
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n🛑 已停止")
            break
        except Exception as e:
            logging.error(f"异常: {e}")
            time.sleep(10)

def main():
    parser = argparse.ArgumentParser(description='多周期 OI 持仓量监控')
    parser.add_argument('--daemon', '-d', action='store_true', help='后台运行，持续记录 OI')
    parser.add_argument('--query', '-q', action='store_true', help='查询 OI 变化')
    parser.add_argument('--interval', '-i', type=int, default=60, help='记录间隔(秒)，默认60')
    parser.add_argument('--top', '-t', type=int, default=10, help='TOP数量，默认10')
    
    args = parser.parse_args()
    
    if args.daemon:
        run_daemon(args.interval)
    elif args.query:
        query_oi_changes(args.top)
    else:
        parser.print_help()
        print("\n示例:")
        print("  python oi_period_tracker.py -d        # 后台运行记录 OI")
        print("  python oi_period_tracker.py -q        # 查询 OI 变化")
        print("  python oi_period_tracker.py -d -q      # 后台运行 + 查询")

if __name__ == "__main__":
    main()
