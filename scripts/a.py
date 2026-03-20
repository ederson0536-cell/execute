# -*- coding: utf-8 -*-
"""
币安USDT永续合约持仓多周期全市场监控机器人（带详细注释）
功能：
✅ 扫描全市场USDT合约
✅ 多周期持仓聚合 (5m,15m,30m,1h,4h,12h)
✅ 异动规则判断并发送Telegram提醒
✅ 日志记录
✅ 并发优化
"""

import requests  # HTTP请求
import time  # 时间延迟
import logging  # 日志记录
import traceback  # 捕获异常堆栈
from datetime import datetime, timedelta, timezone  # 时间处理
import concurrent.futures  # 并发处理
from datetime import datetime, timezone
from threading import Lock
alert_lock = Lock()
from logging.handlers import RotatingFileHandler

# 信号发送配置（只发Symbol+Score）
#SHORT_SIGNAL_URL = "http://127.0.0.1:8001/signal"  # 短线信号接口（沿用你原有）
#LONG_SIGNAL_URL = "http://127.0.0.1:9001/signal"   # 长线信号接口（沿用你原有）
FULL_SIGNAL_URL = "http://127.0.0.1:8001/signal_full"



# === 防止重复提醒 ===
last_alert_time = {}
ALERT_INTERVAL = 3 * 60  # 3分钟内同币种不重复提醒

# =================== 配置 ===================
# Telegram Bot配置
TELEGRAM_BOT_TOKEN = "8242454526:AAH6ZV4ci9_rSQbuXm5q2W-exRdUeCAFEBc"  # Bot Token
TELEGRAM_CHAT_ID = "-4835914620"  # 频道/群ID


# Binance API基础URL
BASE_URL = "https://fapi.binance.com"

# 多周期配置：单位为5分钟K线的倍数
PERIODS = {
    "5m": 1,    "15m": 3,    "30m": 6,    "1h": 12,    "4h": 48,    "8h": 96,    "12h": 144,    "24h": 288}
# === 定义黑名单 ===
BLACKLIST = ["BAKEUSDT", "HIFIUSDT", "NEIROETHUSDT","SLERFUSDT","AI16ZUSDT","1000XUSDT",
"XCNUSDT","FLMUSDT","PONKEUSDT","SXPUSDT","OBOLUSDT","MILKUSDT","VOXELUSDT","FISUSDT","42USDT","REIUSDT",
"EPTUSDT","TANSSIUSDT","BIDUSDT","ZRCUSDT","DFUSDT","RVVUSDT","CHESSUSDT"]  # 你不想提醒的币种

# 记录每个交易对24小时内的提醒次数
alert_counter = {}  # 格式: {symbol: [(timestamp1), (timestamp2), ...]}
ALERT_WINDOW = 24 * 60 * 60  # 24小时，单位秒


# === 高级日志配置（自动轮转，防止重复打印） ===
LOG_FILE = "a.log"              # 日志文件名
MAX_LOG_SIZE = 5 * 1024 * 1024  # 单个日志文件最大 5MB
BACKUP_COUNT = 5                # 最多保留 5 个旧日志

# 初始化日志（确保全局唯一，无重复处理器
def init_logger():
    logger = logging.getLogger()  # 根logger
    logger.setLevel(logging.INFO)

    # 清除旧处理器
    if logger.handlers:
        logger.handlers.clear()

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        "%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.propagate = False   # ✅ 防止日志冒泡重复
    logger.info("✅ 日志系统初始化完成（支持自动分割，无重复打印）")
    return logger


# =================== 工具函数 ===================
# Telegram发送消息
def send_telegram_message(text, chat_id=TELEGRAM_CHAT_ID):
    """
    安全版 Telegram 消息发送：
    ✅ 自动分段防止超长被截断
    ✅ 返回发送成功(True)/失败(False)
    ✅ 打日志确认是否真的发送
    """
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        max_len = 3900  # Telegram上限4096，留点安全空间

        # 分段发送防止被截断
        for i in range(0, len(text), max_len):
            chunk = text[i:i+max_len]
            payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
            r = requests.post(url, data=payload, timeout=5)
            if r.status_code != 200:
                logging.error(f"Telegram 返回错误: {r.status_code} {r.text[:200]}")
                return False
            time.sleep(0.3)  # 避免被限速
        logging.info(f"✅ Telegram 发送成功，长度={len(text)}")
        return True
    except Exception as e:
        logging.error(f"Telegram 发送失败: {e}")
        return False


        

'''def send_trade_signal(side, symbol):
    """
    发送交易信号给交易机器人本地HTTP接口
    side: 'BUY' 或 'SELL'
    usdt_amount: 下单金额
    """
    try:
        url = "http://127.0.0.1:8001/signal"  # ⚠️ 交易机器人本地接口
        payload = {
            "action": side.upper(),
            "symbol": symbol,
        }
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code == 200:
            logging.info(f"✅ 已发送交易信号到交易机器人: {payload}")
        else:
            logging.error(f"交易机器人返回错误: {r.status_code} {r.text}")
    except Exception as e:
        logging.error(f"发送交易信号失败: {e}")'''

'''def send_long_trade_signal(side, symbol):
    """
    发送交易信号给交易机器人本地HTTP接口
    side: 'BUY' 或 'SELL'
    usdt_amount: 下单金额
    """
    try:
        url = "http://127.0.0.1:9001/signal"  # ⚠️ 交易机器人本地接口
        payload = {
            "action": side.upper(),
            "symbol": symbol,
        }
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code == 200:
            logging.info(f"✅ 已发送交易信号到交易机器人: {payload}")
        else:
            logging.error(f"交易机器人返回错误: {r.status_code} {r.text}")
    except Exception as e:
        logging.error(f"发送交易信号失败: {e}")'''



def _sign(x, eps=1e-9):
    if x > eps:
        return 1
    if x < -eps:
        return -1
    return 0


def local_quant_analysis(symbol, agg_results, period_strength_ratio, nb_disjoint_ratios):
    """
    本地量化解读（替代外部 GPT 调用）：
    - 识别主导周期（资金强度最大）
    - 计算方向一致性（价格/NB/OI 共振）
    - 识别资金结构与风险（背离、锁仓、虚假推动）
    - 输出结构化文本 + score(-100~100)
    """
    valid_periods = {k: v for k, v in agg_results.items() if v.get("valid", True)}
    if not valid_periods:
        return {
            "score": 0.0,
            "summary": "全部周期波动不足阈值，本轮判定为低波动震荡。",
            "dominant_period": "N/A",
            "direction": "震荡",
            "coherence": "弱共振"
        }

    ordered_periods = [p for p in ["5m", "15m", "30m", "1h", "4h", "8h", "12h", "24h"] if p in valid_periods]

    dominant_period = max(
        ordered_periods,
        key=lambda p: abs(period_strength_ratio.get(p, 0.0)) * (1 + abs(valid_periods[p].get("NB_OI_pct", 0.0)))
    )
    dom = valid_periods[dominant_period]

    dom_price_sign = _sign(dom.get("price_pct", 0.0))
    dom_nb_sign = _sign(dom.get("NB_OI_pct", 0.0))
    dom_doi_sign = _sign(dom.get("ΔOI_percent", 0.0))

    # 趋势方向（优先看主导周期价格+资金）
    if dom_price_sign == dom_nb_sign and dom_price_sign != 0:
        direction_sign = dom_price_sign
    else:
        direction_sign = _sign(dom.get("NB_OI_pct", 0.0) + dom.get("ΔOI_percent", 0.0))

    direction = "多头" if direction_sign > 0 else ("空头" if direction_sign < 0 else "震荡")

    # 周期协同度：统计主导方向一致的周期占比
    agree = 0
    for p in ordered_periods:
        row = valid_periods[p]
        ps = _sign(row.get("price_pct", 0.0))
        ns = _sign(row.get("NB_OI_pct", 0.0))
        ds = _sign(row.get("ΔOI_percent", 0.0))
        if direction_sign == 0:
            continue
        if ps == direction_sign and (ns == direction_sign or ds == direction_sign):
            agree += 1
    coherence_ratio = (agree / len(ordered_periods)) if ordered_periods else 0.0
    if coherence_ratio >= 0.75:
        coherence = "强共振"
    elif coherence_ratio >= 0.45:
        coherence = "弱共振"
    else:
        coherence = "分歧"

    # 风险/异常识别
    lock_position = abs(dom.get("R", 0.0)) < 0.15 and abs(dom.get("ΔOI_percent", 0.0)) > 1.0
    divergence = _sign(dom.get("price_pct", 0.0)) != _sign(dom.get("NB_OI_pct", 0.0)) and abs(dom.get("price_pct", 0.0)) > 0.4
    fake_push = abs(dom.get("price_pct", 0.0)) > 0.8 and dom.get("ΔOI_percent", 0.0) < 0

    # 评分：趋势强度 + 协同度 + 结构质量 - 风险项
    trend_core = (
        dom.get("NB_OI_pct", 0.0) * 3.2 +
        dom.get("ΔOI_percent", 0.0) * 2.2 +
        dom.get("price_pct", 0.0) * 2.0
    )
    structure_bonus = abs(dom.get("R", 0.0)) * 30
    coherence_bonus = coherence_ratio * 28
    effect = dom.get("fund_effect", 0.0)
    effect_bonus = max(-18, min(18, effect * 4))
    volume_confirm = nb_disjoint_ratios.get(dominant_period, 0.0) * 16

    penalty = 0.0
    if lock_position:
        penalty += 22
    if divergence:
        penalty += 16
    if fake_push:
        penalty += 12

    raw_score = direction_sign * (abs(trend_core) + structure_bonus + coherence_bonus + volume_confirm) + effect_bonus - penalty
    score = max(-100.0, min(100.0, raw_score))

    structure_type = "共振型" if _sign(dom.get("NB_OI_pct", 0.0)) == _sign(dom.get("ΔOI_percent", 0.0)) else "对冲型"
    if lock_position:
        structure_type = "多空双开"
    elif divergence and _sign(dom.get("price_pct", 0.0)) > 0 and _sign(dom.get("NB_OI_pct", 0.0)) < 0:
        structure_type = "吸筹背离"

    long_short = "多" if score > 50 else ("空" if score < -50 else "观望")
    anomaly_tags = []
    if lock_position:
        anomaly_tags.append("锁仓")
    if divergence:
        anomaly_tags.append("背离")
    if fake_push:
        anomaly_tags.append("虚假推动")
    anomaly_text = "、".join(anomaly_tags) if anomaly_tags else "无"

    summary = (
        f"📌 趋势方向：{direction} | 主导周期：{dominant_period} | 周期协同度：{coherence}\n"
        f"💠 资金结构：{structure_type}（R={dom.get('R', 0.0):.2f}，资金效应={dom.get('fund_effect', 0.0):.2f}）\n"
        f"⚠️ 异常项：{anomaly_text}\n"
        f"💡 交易建议（自动交易）：{long_short}\n"
        f"📊 综合评分（score）：{score:.2f}"
    )

    return {
        "score": score,
        "summary": summary,
        "dominant_period": dominant_period,
        "direction": direction,
        "coherence": coherence
    }

def send_score_signal(url, symbol, score):
    """仅发送币种和评分到指定接口"""
    try:
        payload = {
            "symbol": symbol,
            "score": round(score, 2)  # 保留2位小数
        }
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code == 200:
            logging.info(f"✅ 发送评分信号成功: {symbol} | 评分: {score:.2f}")
            return True
        else:
            logging.error(f"发送评分信号失败: {symbol} | 状态码: {r.status_code} | 响应: {r.text[:200]}")
    except Exception as e:
        logging.error(f"发送评分信号异常: {symbol} | 错误: {e}")
    return False

def send_full_signal(url, symbol, payload):
    """
    发送完整结构化周期数据（包括所有周期的数据）
    """
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code == 200:
            logging.info(f"✅ FULL 信号发送成功: {symbol}")
            return True
        else:
            logging.error(f"❌ FULL 信号发送失败: {symbol} | 状态码: {r.status_code} | 响应: {r.text[:200]}")
    except Exception as e:
        logging.error(f"❌ FULL 信号异常: {symbol} | 错误: {e}")
    return False

# 安全API调用，带重试机制
def safe_api_call(func, *args, retries=3, **kwargs):
    for i in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if i == retries - 1:
                raise e  # 最后一次失败抛出异常
            time.sleep(1)  # 等待1秒后重试


# =================== 数据获取 ===================
# 获取USDT永续合约交易对
def get_all_usdt_futures():
    try:
        url = f"{BASE_URL}/fapi/v1/exchangeInfo"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        # 筛选永续合约和USDT计价
        symbols = [s['symbol'] for s in data['symbols'] if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT']
        return symbols
    except Exception as e:
        logging.error(f"获取合约列表失败: {e}")
        return []

# 获取持仓量历史数据
def get_open_interest_hist(symbol, period="5m", limit=300):
    try:
        url = f"{BASE_URL}/futures/data/openInterestHist"
        params = {"symbol": symbol, "period": period, "limit": limit}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        for d in data:
            # 确保openInterest为浮点数
            d['openInterest'] = float(d.get('sumOpenInterest',  0))
            d['openInterestValue'] = float(d.get('sumOpenInterestValue', 0))  # ✅ 新增：持仓价值
            d['timestamp'] = int(d['timestamp'])
        return sorted(data, key=lambda x: x['timestamp'])
    except Exception as e:
        logging.error(f"{symbol} 获取持仓量历史失败: {e}")
        return []

# 获取taker买卖量
def get_taker_buy_sell(symbol, period="5m", limit=300):
    try:
        url = f"{BASE_URL}/futures/data/takerlongshortRatio"
        params = {"symbol": symbol, "period": period, "limit": limit, "type": "longShortVol"}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        for d in data:
            d['buyVol'] = float(d.get('buyVol', 0))
            d['sellVol'] = float(d.get('sellVol', 0))
            d['timestamp'] = int(d['timestamp'])
        return sorted(data, key=lambda x: x['timestamp'])
    except Exception as e:
        logging.error(f"{symbol} 获取taker数据失败: {e}")
        return []

# 获取5m K线数据
def get_klines(symbol, limit=300):
    try:
        url = f"{BASE_URL}/fapi/v1/klines"
        params = {"symbol": symbol, "interval": "5m", "limit": limit}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        result = []
        for k in data:
            result.append({
                "timestamp": int(k[0]),  # 开盘时间
                "open": float(k[1]),     # 开盘价
                "close": float(k[4])     # 收盘价
            })
        return sorted(result, key=lambda x: x['timestamp'])
    except Exception as e:
        logging.warning(f"{symbol} 获取K线失败: {e}")
        return []

def is_valid_period(price_pct, nb_oi_pct, doi_pct, threshold=1.0):
    """
    判断周期是否有效（即是否有代表性）
    当价格、NB/OI、ΔOI三者都小于阈值时，认为该周期波动无代表性。
    """
    return not (
        abs(price_pct) < threshold and
        abs(nb_oi_pct) < threshold and
        abs(doi_pct) < threshold
    )

# === 方案 A: 相对强度（密度 × 最大值归一） ===
def calc_period_strength_ratio(taker_data, period_map):
    """
    基于周期长度，把对应长度的 NB 区间求和，然后对最大值做归一化（0~1）
    用于替代 density_ratio。
    """

    nb5 = [(t["buyVol"] - t["sellVol"]) for t in taker_data]
    L = len(nb5)

    strength = {}

    for period, count in period_map.items():
        if count > L:
            strength[period] = 0
            continue

        # 取最近 count 个5m
        seg = nb5[-count:]
        s = abs(sum(seg))
        strength[period] = s

    # 归一化（找最大值）
    vmax = max(strength.values()) if strength else 0
    if vmax == 0:
        return {p: 0.0 for p in strength}

    # 归一化比值（0~1）
    ratio = {p: strength[p] / vmax for p in strength}
    return ratio


# === 方案 B: 不重叠增量区间占比 ===
INCRE_BUCKETS = [
    ("5m", 1),
    ("15m", 3-1),
    ("30m", 6-3),
    ("1h", 12-6),
    ("4h", 48-12),
    ("8h", 96-48),
    ("12h", 144-96),
    ("24h", 288-144),
]


def calc_nb_distribution_disjoint(taker_data):
    """
    不同区间的 5m 平均成交量强度（0~1）
    区间 = 5m、15m、30m、1h、4h… 根据 INCRE_BUCKETS 定义
    强度 = 区间 5m 平均成交量 / 全区间最大平均成交量
    """

    vol5 = [(t["buyVol"] + t["sellVol"]) for t in taker_data]

    avg_strength = {}
    idx = len(vol5)

    for name, count in INCRE_BUCKETS:
        start = max(0, idx - count)
        segment = vol5[start:idx]

        if len(segment) == 0:
            avg_strength[name] = 0
        else:
            avg_strength[name] = sum(segment) / len(segment)

        idx = start

    # 找最大平均成交量
    vmax = max(avg_strength.values()) if avg_strength else 0

    if vmax == 0:
        return {k: 0.0 for k in avg_strength}

    # 归一化成强度
    return {k: avg_strength[k] / vmax for k in avg_strength}

# =================== 指标计算 ===================
# R值计算
def calc_R(nb, delta_oi):
    if abs(nb) >= abs(delta_oi) and abs(nb) > 0:
        return delta_oi / abs(nb)
    elif abs(delta_oi) > 0:
        return nb / abs(delta_oi)
    return 0

# 买卖量和持仓变化数据关系解读
def interpret_nboi_final(nb, delta_oi, eps=1e-6):
    """
    主动净买卖量(NB) 与 持仓变化(ΔOI) 的行为 + 趋势综合解读（精简版）
    ————————————————————————————————
    逻辑：
    1️⃣ 根据NB与ΔOI方向判断主导与被动资金行为；
    2️⃣ 计算R值量化主导强度；
    3️⃣ 判断为 共振型（方向一致） 或 对冲型（方向分歧）；
    4️⃣ R ≥ 0.4 为纯趋势，R < 0.4 为混合/震荡；
    """

    result = {"interpretation": "市场震荡 / 双方平衡", "trend": "无效"}

    # === 无变化时返回 ===
    if abs(nb) < eps and abs(delta_oi) < eps:
        return result

    # === 计算R值与比例 ===
    R = calc_R(nb, delta_oi)
    dom_ratio = (1 + abs(R)) / 2
    sub_ratio = (1 - abs(R)) / 2

    # === 判断主导类型 ===
    if abs(nb) >= abs(delta_oi):  # 主导因子：主动成交（共振型）
        if nb > 0 and delta_oi > 0:
            dom_action, sub_action = "开多", "平空"
        elif nb > 0 and delta_oi < 0:
            dom_action, sub_action = "平空", "开多"
        elif nb < 0 and delta_oi < 0:
            dom_action, sub_action = "平多", "开空"
        else:
            dom_action, sub_action = "开空", "平多"
        dominance_type = "共振型"
    else:  # 主导因子：持仓变化（对冲型）
        if nb > 0 and delta_oi > 0:
            dom_action, sub_action = "开多", "开空"
        elif nb < 0 and delta_oi > 0:
            dom_action, sub_action = "开空", "开多"
        elif nb < 0 and delta_oi < 0:
            dom_action, sub_action = "平多", "平空"
        else:
            dom_action, sub_action = "平空", "平多"
        dominance_type = "对冲型"

    # === 趋势判断 ===
    absR = abs(R)
    if dominance_type == "共振型":
        if absR >= 0.4:
            trend = "纯趋势（强一致）"
        else:
            trend = "混趋势（次强一致）"
    else:
        if absR >= 0.4:
            trend = "纯趋势（弱分歧）"
        else:
            trend = "震荡（强分歧）"

    # === 组合解释输出 ===
    interp = (
        f"<b>{dom_action}为主</b>（{dom_ratio*100:.0f}%）,"
        f"{sub_action}（{sub_ratio*100:.0f}%）-"
        f"{dominance_type}-{trend}"
    )

    result.update({
        "interpretation": interp,
        "dominance_type": dominance_type,
        "trend": trend,
        "R": R,
        "dom_ratio": dom_ratio,
        "sub_ratio": sub_ratio
    })
    return result

# =================== 最新5m数据处理 ===================
def process_latest_5m(symbol, oi_hist, taker_data, klines):
    oi_latest = oi_hist[-2]  # 最新持仓
    oi_prev = oi_hist[-3]    # 前一条持仓

    # 最近 <= 最新持仓时间的taker
    taker_candidates = [t for t in taker_data if t['timestamp'] <= oi_latest['timestamp']]
    taker_latest = taker_candidates[-1] if taker_candidates else {'buyVol':0, 'sellVol':0, 'timestamp':oi_latest['timestamp']}

    # 区间开始K线
    kline_prev = min((k for k in klines if k['timestamp'] > oi_prev['timestamp']), key=lambda x: x['timestamp'], default=klines[0])
    # 区间结束K线
    kline_latest = next((k for k in klines if k['timestamp'] == oi_latest['timestamp']), klines[-1])
    if kline_latest['close'] == 0:
        logging.info(f"{symbol} 最新K线价格为0，可能合约下架，跳过提醒")
        return  # 不发送消息

    nb = taker_latest['buyVol'] - taker_latest['sellVol']  # 净买卖量
    delta_oi = oi_latest['openInterest'] - oi_prev['openInterest']  # ΔOI
    price_change = (kline_latest['close'] - kline_prev['open']) / kline_prev['open'] * 100  # 区间涨幅%
    r_value = calc_R(nb, delta_oi)  # R值
    interp = interpret_nboi_final(nb, delta_oi)  # 数据解读
    nb_oi_ratio = nb / oi_prev['openInterest'] if oi_prev['openInterest'] != 0 else 0  # NB/OI比例


    return {
        "NB": nb,
        "ΔOI": delta_oi,
        "price_change": price_change,
        "R": r_value,
        "interp": interp,
        "oi_prev": oi_prev,
        "oi_latest": oi_latest,
        "NB/OI_ratio": nb_oi_ratio,
        "taker_latest": taker_latest,
        "kline_prev": kline_prev,
        "kline_latest": kline_latest,
    }

# =================== 多周期聚合 ===================
def aggregate_period(oi_hist, taker_data, klines, n):
    """按n个5m周期聚合数据"""
    if len(oi_hist) < n + 2 or len(taker_data) < n:
        return None
    oi_latest = oi_hist[-2]
    oi_start = oi_hist[-(n+2)]
    delta_oi = oi_latest['openInterest'] - oi_start['openInterest']
    delta_oi_percent = (delta_oi / oi_start['openInterest']*100) if oi_start['openInterest']!=0 else 0

    # 对应K线价格变化
    kline_latest = next((k for k in klines if k['timestamp']==oi_latest['timestamp']), klines[-1])
    kline_start_obj = next((k for k in klines if k['timestamp']>oi_start['timestamp']), klines[0])
    price_change = (kline_latest['close'] - kline_start_obj['open']) / kline_start_obj['open'] * 100

    # 区间净买卖量
    taker_interval = taker_data[-n:]
    nb = sum(t['buyVol'] - t['sellVol'] for t in taker_interval)
    r_value = calc_R(nb, delta_oi)
    interp = interpret_nboi_final(nb, delta_oi)
    nb_oi_pct = nb / oi_start['openInterest']*100 if oi_start['openInterest']!=0 else 0

    taker_latest = taker_interval[-1] if taker_interval else {'timestamp': oi_latest['timestamp']}

    # === 资金强度（动能） ===
    # 表示该周期主动买卖量占持仓量的比例，反映资金参与度
    strength = abs(nb)

        # === 资金效应计算 ===
    if abs(nb_oi_pct) > 0.5:
        fund_effect = price_change / nb_oi_pct
    else:
        fund_effect = 0

    valid = is_valid_period(price_change, nb_oi_pct, delta_oi_percent)

        


    return {
        "price_pct": price_change,
        "ΔOI_percent": delta_oi_percent,
        "NB_OI_pct": nb_oi_pct,
        "R": r_value,
        "interp": interp,
        "oi_start": oi_start,
        "fund_effect": fund_effect, 
        "oi_latest": oi_latest,
        "kline_start": kline_start_obj,
        "kline_latest": kline_latest,
        "valid": valid,
        "NB_raw": nb,  # ✅ 新增：用于密度计算  
        "taker_latest": taker_latest
    }


# === 构建消息（多周期） ===
def build_full_period_message(symbol, agg_results, anomaly_reasons, alert_24h_count, period_strength_ratio=None, nb_disjoint_ratios=None):

    period_strength_ratio = period_strength_ratio or {}
    nb_disjoint_ratios = nb_disjoint_ratios or {}
    """
    agg_results: { period: 聚合结果字典 }
    anomaly_reasons: 异动触发原因列表
    """
    if not agg_results:
        return ""
    
        # === 直接读取sumOpenInterestValue ===
    try:
        latest_agg = agg_results.get("5m") or list(agg_results.values())[-1]
        oi_value = latest_agg["oi_latest"].get("openInterestValue", 0)
        oi_value_m = oi_value / 1_000_000
        oi_text = f"💰 持仓: {oi_value_m:.2f} M USDT"
    except Exception:
        oi_text = "💰 持仓: N/A"

    # 计算整个区间的开始和结束时间
    latest_ts = max(agg['taker_latest']['timestamp'] for agg in agg_results.values() if 'taker_latest' in agg)
    end_dt = datetime.fromtimestamp(latest_ts/1000, tz=timezone.utc) + timedelta(minutes=5)





    msg_lines = [
    f"📊 #{symbol} | ⏱️ 截至: {end_dt.strftime('%H:%M')}  | {oi_text} | ⚔️提醒: {alert_24h_count} ",
    f"💥 异动: {', '.join(anomaly_reasons)}\n"
    f"周期： 价格% | NB/OI% |OI%  | R | 强度|成交量分布| 开仓情况 | 资金效应\n"
    ]

    # 按周期顺序展示
    for period in ['5m','15m','30m','1h','4h','8h','12h','24h']:
        agg = agg_results.get(period)
        if not agg:
            continue

        strength_ratio = period_strength_ratio.get(period, 0)

        disjoint_ratio = nb_disjoint_ratios.get(period, 0)

    # === 判断是否有效 ===
        is_valid = agg.get("valid", True)

    # ✅ 无效周期用⚪开头，有效用🔹
        prefix = "⚪" if not is_valid else "🔹"

        msg_lines.append(
            f"{prefix} {period}: {agg['price_pct']:+.2f}% |"
            f" {agg['NB_OI_pct']:+.2f}% |"
            f" {agg['ΔOI_percent']:+.2f}% |"
            f" <b>R: {agg['R']:.2f}</b> |"
            f" {strength_ratio:.2f} | "
            f" {disjoint_ratio*100:.2f} |\n"
            f"{agg['interp']['interpretation']} |"
            f"{agg['fund_effect']:.2f}\n"

            
        )


    return "\n".join(msg_lines)

def is_quiet_agg_periods(agg_results, periods=None, threshold=5.0):
    """
    判断一组聚合周期是否都很“安静”：
    条件：对每个周期，|NB_OI_pct| < threshold 且 |ΔOI_percent| < threshold
    全部满足 -> 返回 True（整体没什么像样波动，可以忽略本次异动）

    agg_results: {period: {...}}，来自 aggregate_period 的结果
    periods: 要检查的周期列表，比如 ["5m","15m","30m","1h","4h"]
    """
    if periods is None:
        periods = ["5m", "15m", "30m", "1h", "4h", "8h"]

    for p in periods:
        agg = agg_results.get(p)
        # 如果某周期没有聚合数据，保守起见，认为“不安静”，直接 False
        if not agg:
            return False

        nb_oi = agg.get("NB_OI_pct", 0.0)
        doi = agg.get("ΔOI_percent", 0.0)

        # 只要有一个周期的任意一个指标超过阈值，就不是安静区间
        if abs(nb_oi) >= threshold and abs(doi) >= threshold:
            return False

    # 所有指定周期都“波动很小”
    return True


# === 单个交易对处理函数 ===
def process_symbol(symbol):

    # 判断是否在黑名单
    if symbol in BLACKLIST:
        logging.info(f"⛔ {symbol} 在黑名单中，跳过提醒。")
        return

    try:
        # 获取5分钟历史数据（快速判断用）
        oi_hist = get_open_interest_hist(symbol)
        # 防重复提醒逻辑
        with alert_lock:
            now_ts = time.time()
            if symbol in last_alert_time and now_ts - last_alert_time[symbol] < ALERT_INTERVAL:
                logging.info(f"⏸️ {symbol} 在 {ALERT_INTERVAL/60} 分钟内已提醒，跳过重复发送")
                return

        taker_data = get_taker_buy_sell(symbol)
        klines = get_klines(symbol)
        if len(oi_hist)<3 or len(taker_data)<1 or len(klines)<2:
            return

        # 先处理最新5m数据
        latest_5m = process_latest_5m(symbol, oi_hist, taker_data, klines)
        anomaly_reasons = []
        send_msg = False

        # 异动规则1: ΔOI>1%或NB/OI>1% 且 |R|>=0.5
        if (abs(latest_5m['ΔOI']/latest_5m['oi_prev']['openInterest']*100)>=1
            or abs(latest_5m['NB/OI_ratio']*100)>=1) and abs(latest_5m['R'])>=0.5:
            anomaly_reasons.append("5m 比例>1% 且 |R|>=0.5")
            send_msg = True

        # 异动规则2: ΔOI>3%或NB/OI>3%
        if (abs(latest_5m['ΔOI']/latest_5m['oi_prev']['openInterest']*100)>=3
            or abs(latest_5m['NB/OI_ratio']*100)>=3):
            anomaly_reasons.append("5m 比例>3%")
            send_msg = True

        # 如果没有异动则跳过
        if not send_msg:
            return




        # 仅对触发异动的交易对再计算多周期聚合
        agg_results = {}
        for period, n in PERIODS.items():
            agg = aggregate_period(oi_hist, taker_data, klines, n)
            if agg:
                agg_results[period] = agg

        # === 新增：如果 5m/15m/30m/1h/4h 聚合周期整体很“安静”，则忽略本次异动 ===
        if is_quiet_agg_periods(agg_results, periods=["5m", "15m", "30m", "1h", "4h", "8h"], threshold=5.0):
            logging.info(
                f"{symbol} 触发 5m 异动，但 5m~4h 聚合周期的 |NB/OI%| 和 |OI%| 均 < 5%，"
                f"判定为弱波动结构，跳过本次提醒。"
            )
            return

        
        # 方案 A: 相对强度（密度 × 最大值归一）
        period_strength_ratio = calc_period_strength_ratio(taker_data, PERIODS)

        # 方案 B: 不重叠增量区间占比
        nb_disjoint_ratios = calc_nb_distribution_disjoint(taker_data)

        # ===== 更新 alert_counter =====
        now_ts = time.time()
        with alert_lock:
            if symbol not in alert_counter:
                alert_counter[symbol] = []
            alert_counter[symbol].append(now_ts)
            alert_counter[symbol] = [t for t in alert_counter[symbol] if now_ts - t <= ALERT_WINDOW]
            alert_24h_count = len(alert_counter[symbol])

        # 构建消息并发送
        msg = build_full_period_message( symbol, agg_results, anomaly_reasons, alert_24h_count,  period_strength_ratio=period_strength_ratio,nb_disjoint_ratios=nb_disjoint_ratios)
        logging.info(f"[{symbol}] 生成监控报告")

        # === 构造本地量化输入，仅保留有效周期 ===
        valid_agg_results = {k: v for k, v in agg_results.items() if v.get("valid", True)}
        if not valid_agg_results:
            logging.info(f"{symbol} 所有周期波动<1%，本地量化将降级为低波动判定。")



# ========== 本地量化解读整合发送 ==========
        final_msg = msg
        symbol_score = 0.0  # 初始化评分
        analysis_result = None
        ai_summary = ""
        try:
            analysis_result = local_quant_analysis(
                symbol=symbol,
                agg_results=valid_agg_results if valid_agg_results else agg_results,
                period_strength_ratio=period_strength_ratio,
                nb_disjoint_ratios=nb_disjoint_ratios
            )
            symbol_score = float(analysis_result["score"])
            ai_summary = analysis_result["summary"]
            final_msg = f"{msg}\n\n🧠 本地量化解读:\n{ai_summary}"
            logging.info(f"{symbol} 本地量化评分: {symbol_score:.2f}")

        except Exception as e:
            logging.error(f"本地量化分析失败: {e}")
            final_msg = f"{msg}\n\n🧠 本地量化解读: (生成失败)"
            ai_summary = ""

        # ✅ 一次性发送完整消息
        sent_ok = send_telegram_message(final_msg)
        if not sent_ok:
            logging.warning(f"{symbol} 消息发送失败，不计入汇总")
            return  # 不返回结果 -> 汇总不会出现
        time.sleep(0.3)
        logging.info(f"{symbol} 提醒消息已成功发送。")

        # === 构建结构化 FULL SIGNAL Payload ===
        full_payload = {
            "symbol": symbol,
            "score": symbol_score,
            "trigger": ", ".join(anomaly_reasons),
            "periods": {},
            "meta": {
                "alert_count_24h": alert_24h_count,
                "timestamp": int(latest_5m["oi_latest"]["timestamp"]) + 5 * 60 * 1000,
                "ai_summary": ai_summary or "",
                "analysis_mode": "local_quant_v1"
            }
        }

        # 填充所有周期数据
        for period, agg in agg_results.items():
            full_payload["periods"][period] = {
                "price_pct": agg["price_pct"],
                "nb_oi_pct": agg["NB_OI_pct"],
                "doi_pct": agg["ΔOI_percent"],
                "R": agg["R"],
                "strength": period_strength_ratio.get(period, 0),
                "volume_strength": nb_disjoint_ratios.get(period, 0),

                # ❗❗修复 422：交易脚本要求 string，但监控脚本原来传 float
                "structure": str(agg["interp"]["interpretation"]),
                "fund_effect": str(agg["fund_effect"]),

                "valid": agg["valid"]
            }




        '''# 基于 AI 解读或者 R 值判断买卖信号
        trade_signal = None
        if "短线单：方向（多）" in final_msg:
            trade_signal = "buy"
        elif "短线单：方向（空）" in final_msg:
            trade_signal = "sell"
        # === 黑名单币种不下单，但仍发提醒 ===
        BLACKLIST_TRADE = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "SOLUSDT", "TRXUSDT", "DOGEUSDT", "ADAUSDT", "HYPEUSDT", "LINKUSDT", "BCHUSDT", "XLMWBTUSDT", "SUIUSDT", "HBARUSDT", "AVAXUSDT", "ZECUSDT", "LTCUSDT", "XMRUSDT", "SHIBUSDT", "TONUSDT", "CROUSDT", "TAOUSDT", "DOTUSDT", "MNTUSDT", "MUSDT", "WLFIUSDT", "UNIUSDT", "AAVEUSDT", "OKBUSDT", "BGBUSDT", "NEARUSDT", "PEPEUSDT", "ENAUSDT", "ETCUSDT", "ICPUSDT", "APTUSDT", "ONDOUSDT", "PIUSDT", "ASTERUSDT", "POLUSDT", "WLDUSDT", "HTXUSDT", "MKRUSDT", "DASHUSDT", "ARBUSDT", "TRUMPUSDT", "ALGOUSDT", "GTUSDT", "PUMPUSDT", "IPUSDT", "VETUSDT", "KASUSDT", "SKYUSDT", "ATOMUSDT", "JUPUSDT", "NEXOUSDT", "FLRUSDT", "QNTUSDT", "RENDERUSDT", "SEIUSDT", "FILUSDT"]

        if trade_signal and symbol not in BLACKLIST_TRADE:
            send_trade_signal(trade_signal, symbol)
        
        # 基于 AI 解读或者 R 值判断买卖信号
        trade_long_signal = None
        if "长线单：方向（多）" in final_msg:
            trade_long_signal = "buy"
        elif "长线单：方向（空）" in final_msg:
            trade_long_signal = "sell"
        # === 黑名单币种不下单，但仍发提醒 ===
        BLACKLIST_TRADE = ["BTCUSDT","ALLUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "SOLUSDT", "TRXUSDT", "DOGEUSDT", "ADAUSDT", "HYPEUSDT", "LINKUSDT", "BCHUSDT", "XLMWBTUSDT", "SUIUSDT", "HBARUSDT", "AVAXUSDT", "ZECUSDT", "LTCUSDT", "XMRUSDT", "SHIBUSDT", "TONUSDT", "CROUSDT", "TAOUSDT", "DOTUSDT", "MNTUSDT", "MUSDT", "WLFIUSDT", "UNIUSDT", "AAVEUSDT", "OKBUSDT", "BGBUSDT", "NEARUSDT", "PEPEUSDT", "ENAUSDT", "ETCUSDT", "ICPUSDT", "APTUSDT", "ONDOUSDT", "PIUSDT", "ASTERUSDT", "POLUSDT", "WLDUSDT", "HTXUSDT", "MKRUSDT", "DASHUSDT", "ARBUSDT", "TRUMPUSDT", "ALGOUSDT", "GTUSDT", "PUMPUSDT", "IPUSDT", "VETUSDT", "KASUSDT", "SKYUSDT", "ATOMUSDT", "JUPUSDT", "NEXOUSDT", "FLRUSDT", "QNTUSDT", "RENDERUSDT", "SEIUSDT", "FILUSDT"]

        if trade_long_signal and symbol not in BLACKLIST_TRADE:
            send_long_trade_signal(trade_long_signal, symbol)'''

        last_alert_time[symbol] = now_ts
        # ✅ 返回用于汇总的结果
        return {
            "symbol": symbol,
            "R": latest_5m['R'],
            "count": alert_24h_count,
            "score": symbol_score,
            "full_payload": full_payload,   # 👈 新增
            "source": "a_scan"

        }
        


    except Exception as e:
        logging.error(f"{symbol} 异常: {traceback.format_exc()}")
    
# =================== 主循环 ===================
def main_loop():
    logging.info("程序启动成功")
    symbols = safe_api_call(get_all_usdt_futures)
    logging.info(f"共扫描 {len(symbols)} 个合约")

    while True:
        start = time.time()
        alerted_results = []  # ✅ 存储触发报警的币种结果

        # 并发处理所有交易对
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(process_symbol, sym) for sym in symbols]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    alerted_results.append(result)

        # === 汇总提示 + 按评分发送信号（仅当有异动币种时执行）===
        if alerted_results:
            end_time = datetime.now(timezone.utc).strftime("%H:%M UTC")
            summary_lines = [f"📅 截至 {end_time} 本轮扫描结果："]
            summary_lines.append(f"共触发报警 {len(alerted_results)} 个合约:\n")

            # 排序: 按 R 值绝对值从大到小（用于汇总消息）
            alerted_results.sort(key=lambda x: abs(x["R"]), reverse=True)

            for item in alerted_results:
                summary_lines.append(
                    f"🔸 {item['symbol']} | 来源:{item.get('source','a_scan')} | R={item['R']:+.3f} | 报警次数: {item['count']} | 评分: {item['score']:.2f}"
                )

            # 发送汇总消息
            summary_msg = "\n".join(summary_lines)
            logging.info(summary_msg.replace("\n", " "))
            send_telegram_message(summary_msg)

            # === 新增：按评分绝对值排序，依次发送 symbol+score 信号 ===
            # 优先级：评分绝对值越大，越先发送
            alerted_results_sorted_score = sorted(
                alerted_results,
                key=lambda x: abs(x["score"]),
                reverse=True
            )
            logging.info(f"\n开始按评分排序发送信号（共 {len(alerted_results_sorted_score)} 个币种）：")
            
            # 交易黑名单（统一定义，避免重复）
            BLACKLIST_TRADE = [
                "BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "SOLUSDT", "TRXUSDT", "DOGEUSDT",
                "ADAUSDT", "HYPEUSDT", "LINKUSDT", "BCHUSDT", "XLMWBTUSDT", "SUIUSDT", "HBARUSDT",
                "AVAXUSDT", "ZECUSDT", "LTCUSDT", "XMRUSDT", "SHIBUSDT", "TONUSDT", "CROUSDT",
                "TAOUSDT", "DOTUSDT", "MNTUSDT", "MUSDT", "WLFIUSDT", "UNIUSDT", "AAVEUSDT",
                "OKBUSDT", "BGBUSDT", "NEARUSDT", "PEPEUSDT", "ENAUSDT", "ETCUSDT", "ICPUSDT",
                "APTUSDT", "ONDOUSDT", "PIUSDT", "ASTERUSDT", "POLUSDT", "WLDUSDT", "HTXUSDT",
                "MKRUSDT", "DASHUSDT", "ARBUSDT", "TRUMPUSDT", "ALGOUSDT", "GTUSDT", "PUMPUSDT",
                "IPUSDT", "VETUSDT", "KASUSDT", "SKYUSDT", "ATOMUSDT", "JUPUSDT", "NEXOUSDT",
                "FLRUSDT", "QNTUSDT", "RENDERUSDT", "SEIUSDT", "FILUSDT"
            ]

            # 遍历发送信号
            for item in alerted_results_sorted_score:
                symbol = item["symbol"]
                score = item["score"]
                payload = item["full_payload"]     # 👈 获取 payload

                # 过滤黑名单币种
                if symbol in BLACKLIST_TRADE:
                    logging.info(f"⛔ {symbol} 在交易黑名单中，跳过信号发送")
                    continue

                # 发送短线信号
                #send_score_signal(SHORT_SIGNAL_URL, symbol, score)
                send_full_signal(FULL_SIGNAL_URL, symbol, payload)

                
                # 如需发送长线信号，解开下面注释（确保已定义 LONG_SIGNAL_URL）
                # if 'LONG_SIGNAL_URL' in locals() and LONG_SIGNAL_URL:
                #     send_score_signal(LONG_SIGNAL_URL, symbol, score)

                time.sleep(0.1)  # 避免接口限流

        # === 控制循环间隔（5分钟/轮）===
        elapsed = time.time() - start
        logging.info(f"本轮扫描完成，耗时 {elapsed:.2f}s")
        sleep_time = max(0, 5 * 60 - elapsed)  # 不足5分钟则补足睡眠
        time.sleep(sleep_time)

# =================== 启动程序 ===================
if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logging.info("✅ 程序被用户手动终止")
    except Exception as e:
        logging.error(f"❌ 程序异常终止：{traceback.format_exc()}")   


