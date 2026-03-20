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

def fetch_all_funding():
    """
    批量获取资金费率（单API调用版）
    使用 /fapi/v1/premiumIndex 不传 symbol，一次返回全市场数据。
    """
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=8)
        if r.status_code != 200:
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        results = []
        for row in data:
            symbol = row.get("symbol", "")
            # 这里只保留 USDT 永续主列表（排除无效字段）
            if not symbol.endswith("USDT"):
                continue
            if "lastFundingRate" not in row:
                continue
            try:
                results.append(
                    {
                        "symbol": symbol,
                        "fundingRate": float(row["lastFundingRate"]) * 100,
                    }
                )
            except Exception:
                continue
        return results
    except Exception:
        return []

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
