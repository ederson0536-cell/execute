#!/usr/bin/env python3
"""
大户持仓多空比变化监控 - 后台常驻运行
每小时自动查询并推送Telegram
"""

import requests
import json
import time
import os
import signal
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# 配置 - 使用OpenClaw的message工具发送，需要配置telegram
# 这里使用环境变量，如果没有则跳过Telegram发送
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
INTERVAL_HOURS = 1
LOG_FILE = "/home/bro/.openclaw/workspace-execute/data/ls_ratio_monitor.log"

running = True

def log(msg):
    """日志记录"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] {msg}"
    print(log_msg)
    with open(LOG_FILE, "a") as f:
        f.write(log_msg + "\n")

def signal_handler(sig, frame):
    """处理退出信号"""
    global running
    log("收到退出信号，正在停止...")
    running = False

def get_all_usdt_symbols():
    """获取所有USDT合约"""
    resp = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo")
    symbols = [s['symbol'] for s in resp.json()['symbols'] 
               if s['status'] == 'TRADING' and s.get('contractType') == 'PERPETUAL' and s['quoteAsset'] == 'USDT']
    return symbols

def get_change(symbol):
    """获取单个币种的多空比变化"""
    try:
        url = f"https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol={symbol}&period=1h&limit=2"
        r = requests.get(url, timeout=3)
        if r.status_code == 200 and r.text and r.text != '[]':
            data = r.json()
            if len(data) >= 2:
                current = data[-1]
                prev = data[-2]
                cur_ratio = float(current['longShortRatio'])
                prev_ratio = float(prev['longShortRatio'])
                if prev_ratio > 0:
                    change_pct = (cur_ratio - prev_ratio) / prev_ratio * 100
                    return {
                        'symbol': current['symbol'],
                        'cur_long': float(current['longAccount']) * 100,
                        'prev_long': float(prev['longAccount']) * 100,
                        'cur_ratio': cur_ratio,
                        'prev_ratio': prev_ratio,
                        'change_pct': change_pct
                    }
    except Exception as e:
        pass
    return None

def fetch_all_changes():
    """并发获取所有币种变化数据"""
    symbols = get_all_usdt_symbols()
    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(get_change, sym): sym for sym in symbols}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
    return results

def format_message(results, title, reverse=True):
    """格式化消息"""
    sorted_results = sorted(results, key=lambda x: x['change_pct'], reverse=reverse)[:10]
    
    msg = f"**{title}** (更新时间: {datetime.now().strftime('%H:%M')})\n\n"
    msg += "| 排名 | 交易对 | 1小时前 | 当前 | 变化% |\n"
    msg += "|:---:|--------|:---:|:---:|:---:|\n"
    
    for i, d in enumerate(sorted_results, 1):
        sign = "+" if d['change_pct'] > 0 else ""
        msg += f"{i} | {d['symbol']} | {d['prev_ratio']:.2f} | {d['cur_ratio']:.2f} | **{sign}{d['change_pct']:.1f}%**\n"
    
    return msg

def send_telegram(message):
    """发送Telegram消息"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram配置未设置，尝试保存到文件")
        with open("/home/bro/.openclaw/workspace-execute/data/ls_ratio_report.txt", "a") as f:
            f.write(f"\n=== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            f.write(message + "\n")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        resp = requests.post(url, json=data, timeout=10)
        if resp.status_code == 200:
            log("Telegram消息发送成功")
        else:
            log(f"Telegram发送失败: {resp.text}")
    except Exception as e:
        log(f"发送失败: {e}")

def save_to_file(data, filename):
    """保存数据到文件"""
    with open(f"/home/bro/.openclaw/workspace-execute/data/{filename}", "w") as f:
        json.dump(data, f, indent=2)

def run_once():
    """执行一次监控"""
    log("开始查询大户持仓多空比变化...")
    
    results = fetch_all_changes()
    log(f"共获取 {len(results)} 个合约数据")
    
    if not results:
        log("未获取到数据")
        return
    
    # 保存原始数据
    save_to_file(results, "ls_ratio_changes.json")
    
    # 增加前十
    increase_msg = format_message(results, "📈 多空比增幅 TOP 10 (1小时)", reverse=True)
    
    # 减少前十
    decrease_msg = format_message(results, "📉 多空比降幅 TOP 10 (1小时)", reverse=False)
    
    # 发送Telegram
    full_message = increase_msg + "\n" + decrease_msg
    send_telegram(full_message)
    
    log("任务完成!")

def main():
    """主循环"""
    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    log("=" * 50)
    log("大户持仓多空比监控启动")
    log(f"运行间隔: {INTERVAL_HOURS} 小时")
    log("=" * 50)
    
    # 先运行一次
    run_once()
    
    # 后台循环
    while running:
        # 等待INTERVAL_HOURS小时
        sleep_seconds = INTERVAL_HOURS * 3600
        log(f"等待 {INTERVAL_HOURS} 小时后再次运行...")
        
        # 分段睡眠，可以更快响应退出信号
        for _ in range(sleep_seconds):
            if not running:
                break
            time.sleep(1)
        
        if running:
            run_once()
    
    log("监控已停止")

if __name__ == "__main__":
    main()
