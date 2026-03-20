#!/usr/bin/env python3
"""
资金费率监控脚本
每分钟运行一次，查询资金费率正负前十
"""

import requests
import json
import time
import os
import signal
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

INTERVAL_MINUTES = 1
LOG_FILE = "/home/bro/.openclaw/workspace-execute/data/funding_rate_monitor.log"

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

def get_funding(symbol):
    """获取单个币种的资金费率"""
    try:
        url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
        r = requests.get(url, timeout=2)
        if r.status_code == 200:
            data = r.json()
            return {
                'symbol': data['symbol'],
                'fundingRate': float(data['lastFundingRate']) * 100
            }
    except:
        pass
    return None

def fetch_all_funding():
    """并发获取所有币种资金费率"""
    symbols = get_all_usdt_symbols()
    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(get_funding, sym): sym for sym in symbols}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
    return results

def format_message(positive, negative):
    """格式化消息"""
    msg = f"**💰 资金费率 ({datetime.now().strftime('%H:%M')})**\n\n"
    
    msg += "**📈 正费率 TOP 10**\n"
    msg += "| 排名 | 交易对 | 费率 |\n"
    msg += "|:---:|--------|:---:|\n"
    for i, d in enumerate(positive, 1):
        msg += f"{i} | {d['symbol']} | **{d['fundingRate']:.3f}%**\n"
    
    msg += "\n**📉 负费率 TOP 10**\n"
    msg += "| 排名 | 交易对 | 费率 |\n"
    msg += "|:---:|--------|:---:|\n"
    for i, d in enumerate(negative, 1):
        msg += f"{i} | {d['symbol']} | **{d['fundingRate']:.3f}%**\n"
    
    return msg

def save_report(positive, negative):
    """保存报告到文件"""
    with open("/home/bro/.openclaw/workspace-execute/data/funding_rate_report.txt", "w") as f:
        f.write(format_message(positive, negative))

def run_once():
    """执行一次监控"""
    log("开始查询资金费率...")
    
    results = fetch_all_funding()
    log(f"共获取 {len(results)} 个合约数据")
    
    if not results:
        log("未获取到数据")
        return
    
    # 正费率排序
    positive = sorted(results, key=lambda x: x['fundingRate'], reverse=True)[:10]
    # 负费率排序
    negative = sorted(results, key=lambda x: x['fundingRate'])[:10]
    
    # 保存报告
    save_report(positive, negative)
    
    log("任务完成!")

def main():
    """主循环"""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    log("=" * 50)
    log("资金费率监控启动")
    log(f"运行间隔: {INTERVAL_MINUTES} 分钟")
    log("=" * 50)
    
    # 先运行一次
    run_once()
    
    # 后台循环
    while running:
        sleep_seconds = INTERVAL_MINUTES * 60
        log(f"等待 {INTERVAL_MINUTES} 分钟后再次运行...")
        
        for _ in range(sleep_seconds):
            if not running:
                break
            time.sleep(1)
        
        if running:
            run_once()
    
    log("监控已停止")

if __name__ == "__main__":
    main()
