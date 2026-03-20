#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多周期价格监控脚本
功能：
- 每分钟记录价格到数据库
- 计算 15m/1h/4h/24h 的价格变化率
- 快速查询，秒级响应

使用方法:
    # 后台运行 (持续记录价格)
    python scripts/price_period_tracker.py --daemon
    
    # 查询价格变化
    python scripts/price_period_tracker.py --query
    
    # 后台运行 + 查询
    python scripts/price_period_tracker.py --daemon --query
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
BASE_URL = "https://api.binance.com"
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "price_history.db")
LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "price_tracker.log")

# 日志配置
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def init_db():
    """初始化价格历史数据库"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 价格历史记录表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            UNIQUE(ts, symbol)
        );
    """)
    
    # 创建索引
    cur.execute("CREATE INDEX IF NOT EXISTS idx_price_ts ON price_history(ts);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_price_symbol ON price_history(symbol);")
    
    conn.commit()
    conn.close()
    logging.info(f"价格数据库初始化完成: {DB_PATH}")

def get_usdt_symbols():
    """获取 USDT 现货交易对列表"""
    try:
        data = requests.get(f"{BASE_URL}/api/v3/exchangeInfo", timeout=10).json()
        symbols = [
            s["symbol"] for s in data["symbols"]
            if s["symbol"].endswith("USDT") and s["status"] == "TRADING"
            and not s["symbol"].endswith("UPUSDT")
            and not s["symbol"].endswith("DOWNUSDT")
        ]
        return symbols
    except Exception as e:
        logging.error(f"获取交易对失败: {e}")
        return []

def get_price(symbol):
    """获取单个币种价格 (24h ticker)"""
    try:
        r = requests.get(f"{BASE_URL}/api/v3/ticker/24hr?symbol={symbol}", timeout=5)
        if r.status_code == 200:
            return float(r.json()["lastPrice"])
    except:
        pass
    return None

def fetch_all_prices(symbols):
    """批量获取所有币种价格"""
    result = {}
    with ThreadPoolExecutor(max_workers=30) as ex:
        futures = {ex.submit(get_price, s): s for s in symbols}
        for future in as_completed(futures):
            s = futures[future]
            try:
                price = future.result()
                if price is not None:
                    result[s] = price
            except:
                continue
    return result

def record_price():
    """记录当前价格到数据库"""
    symbols = get_usdt_symbols()
    if not symbols:
        logging.warning("无法获取交易对列表")
        return
    
    price_data = fetch_all_prices(symbols)
    if not price_data:
        logging.warning("未获取到任何价格数据")
        return
    
    ts = int(time.time())
    ts = (ts // 60) * 60  # 取整到分钟
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    inserted = 0
    for symbol, price in price_data.items():
        try:
            cur.execute(
                "INSERT OR REPLACE INTO price_history (ts, symbol, price) VALUES (?, ?, ?);",
                (ts, symbol, price)
            )
            inserted += 1
        except Exception as e:
            logging.warning(f"写入失败 {symbol}: {e}")
    
    conn.commit()
    conn.close()
    
    logging.info(f"本轮记录价格 {len(price_data)} 个币种，成功 {inserted} 条")
    return len(price_data)

def get_price_change(symbol, minutes):
    """获取指定时间周期的价格变化率"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    now = int(time.time())
    now = (now // 60) * 60
    past = now - (minutes * 60)
    
    # 获取当前价格
    cur.execute("SELECT price FROM price_history WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1;", 
                (symbol, now))
    row_now = cur.fetchone()
    if not row_now:
        conn.close()
        return None
    price_now = row_now[0]
    
    # 获取历史价格
    cur.execute("SELECT price FROM price_history WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1;", 
                (symbol, past))
    row_past = cur.fetchone()
    conn.close()
    
    if not row_past:
        return None
    
    price_past = row_past[0]
    if price_past <= 0:
        return None
    
    change = (price_now - price_past) / price_past
    return {
        'symbol': symbol,
        'price_now': price_now,
        'price_past': price_past,
        'change': change,
        'change_pct': change * 100
    }

def query_price_changes(top_n=10):
    """查询各周期价格变化 TOP10"""
    symbols = get_usdt_symbols()
    if not symbols:
        print("❌ 无法获取交易对列表")
        return
    
    # 检查数据
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT MIN(ts), MAX(ts), COUNT(DISTINCT ts) FROM price_history;")
    row = cur.fetchone()
    conn.close()
    
    if not row or row[0] is None:
        print("❌ 数据库中暂无价格数据，请先运行 --daemon 记录数据")
        return
    
    min_ts, max_ts, count = row
    print(f"📊 数据范围: {datetime.fromtimestamp(min_ts)} ~ {datetime.fromtimestamp(max_ts)}")
    print(f"   记录条数: {count} 条\n")
    
    results = {}
    for minutes, name in [(15, "15分钟"), (60, "1小时"), (240, "4小时"), (1440, "24小时")]:
        changes = []
        for symbol in symbols:
            try:
                result = get_price_change(symbol, minutes)
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
        print(f"\n{'='*65}")
        print(f"📈 {period} 涨幅 TOP{top_n}")
        print('='*65)
        print(f"{'#':<3} {'交易对':<15} {'当前价格':<15} {'变化率':<10}")
        print('-'*55)
        for i, d in enumerate(data['gainers'], 1):
            print(f"{i:<3} {d['symbol']:<15} {d['price_now']:<15.4f} {d['change_pct']:>+8.2f}%")
        
        print(f"\n{'='*65}")
        print(f"📉 {period} 跌幅 TOP{top_n}")
        print('='*65)
        print(f"{'#':<3} {'交易对':<15} {'当前价格':<15} {'变化率':<10}")
        print('-'*55)
        for i, d in enumerate(data['losers'], 1):
            print(f"{i:<3} {d['symbol']:<15} {d['price_now']:<15.4f} {d['change_pct']:>+8.2f}%")

def run_daemon(interval=60):
    """后台运行，持续记录价格"""
    print(f"🚀 价格记录器启动，每 {interval} 秒记录一次")
    print("   按 Ctrl+C 停止\n")
    
    init_db()
    
    while True:
        try:
            record_price()
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n🛑 已停止")
            break
        except Exception as e:
            logging.error(f"异常: {e}")
            time.sleep(10)

def main():
    parser = argparse.ArgumentParser(description='多周期价格监控')
    parser.add_argument('--daemon', '-d', action='store_true', help='后台运行，持续记录价格')
    parser.add_argument('--query', '-q', action='store_true', help='查询价格变化')
    parser.add_argument('--interval', '-i', type=int, default=60, help='记录间隔(秒)，默认60')
    parser.add_argument('--top', '-t', type=int, default=10, help='TOP数量，默认10')
    
    args = parser.parse_args()
    
    if args.daemon:
        run_daemon(args.interval)
    elif args.query:
        query_price_changes(args.top)
    else:
        parser.print_help()
        print("\n示例:")
        print("  python price_period_tracker.py -d        # 后台运行记录价格")
        print("  python price_period_tracker.py -q        # 查询价格变化")
        print("  python price_period_tracker.py -d -q      # 后台运行 + 查询")

if __name__ == "__main__":
    main()
