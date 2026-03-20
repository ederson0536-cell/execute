# TOOLS.md - 工具与技能配置

> 版本：1.1 | 更新：2026-03-19

---

## 技能库

### 已安装技能

| 技能 | 功能 |
|------|------|
| **spot** | 币安现货交易 API |
| **crypto-market-rank** | 市场排名、趋势、Alpha |
| **meme-rush** | 迷因币快讯、新币launch |
| **query-token-info** | 代币信息、价格、行情 |
| **query-token-audit** | 代币安全审计 |

### 技能位置
```
/home/bro/.openclaw/workspace-execute/skills/
├── spot
├── crypto-market-rank
├── meme-rush
├── query-token-info
└── query-token-audit
```

---

## 工具配置

### Exec
- **安全模式**: full
- **工作目录**: `/home/bro/.openclaw/workspace-execute`
- **默认**: 使用绝对路径

---

## 数据面板 (Dashboard)

### 访问地址
- **本地**: http://localhost:8888
- **功能**: 实时监控合约市场数据

### 面板布局 (4列 × 4行)
| 列 | 数据类型 | 说明 |
|----|----------|------|
| 1 | 资金费率 | 正费率/负费率 TOP10 |
| 2 | 价格变化 | 15m/1h/4h/24h 涨跌幅 |
| 3 | OI持仓量 | 15m/1h/4h/24h 变化 |
| 4 | 大户多空比 | 1小时周期变化 |

### 后端服务
- **脚本**: `scripts/dashboard_server.py`
- **端口**: 8888
- **前端**: `scripts/dashboard.html`
- **缓存**: 30秒

### 启动/重启
```bash
# 启动
cd /home/bro/.openclaw/workspace-execute
python3 scripts/dashboard_server.py &

# 重启
pkill -f dashboard_server
python3 scripts/dashboard_server.py &
```

---

## 数据采集脚本 (后台运行)

### 运行中的脚本

| 脚本 | 功能 | 频率 | 状态 |
|------|------|------|------|
| `ls_ratio_monitor.py` | 大户多空比变化 | 每小时 | 运行中 |
| `funding_rate_monitor.py` | 资金费率 | 每分钟 | 运行中 |
| `oi_period_tracker.py` | OI持仓量记录 | 每分钟 | 运行中 |
| `price_period_tracker.py` | 价格记录 | 每分钟 | 运行中 |
| `dashboard_server.py` | 数据面板服务 | 常驻 | 运行中 |

### 脚本位置
```
/home/bro/.openclaw/workspace-execute/scripts/
├── dashboard_server.py       # 数据面板后端 (端口8888)
├── dashboard.html            # 数据面板前端
├── ls_ratio_monitor.py       # 大户多空比监控
├── funding_rate_monitor.py   # 资金费率监控
├── oi_period_tracker.py     # OI持仓量追踪
├── price_period_tracker.py  # 价格追踪
└── 1m_oi_realtime.py        # 1分钟OI实时监控
```

---

## 数据文件

### 实时数据
| 文件 | 内容 |
|------|------|
| `data/funding_rate_report.txt` | 资金费率 TOP10 |
| `data/ls_ratio_changes.json` | 大户多空比变化 |
| `data/ls_ratio_report.txt` | 多空比报告 |

### 历史数据库
| 文件 | 大小 | 内容 |
|------|------|------|
| `data/price_history.db` | ~26MB | 价格历史 |
| `data/oi_history.db` | ~29MB | OI持仓量历史 |

### 启动脚本
```bash
# 启动数据采集
python3 scripts/funding_rate_monitor.py &
python3 scripts/ls_ratio_monitor.py &
python3 scripts/oi_period_tracker.py --daemon &
python3 scripts/price_period_tracker.py --daemon &

# 启动面板
python3 scripts/dashboard_server.py &
```

---

## API 接口

### Dashboard API
```
GET http://localhost:8888/api
```

返回 JSON:
```json
{
  "timestamp": "2026-03-19 23:50:00",
  "funding": {
    "positive": [{"symbol": "BULLAUSDT", "rate": 0.085}],
    "negative": [{"symbol": "ICNTUSDT", "rate": -0.744}]
  },
  "ls_ratio": {...},
  "price": {"15m": {...}, "60m": {...}},
  "oi": {"15m": {...}, "60m": {...}},
  "trading_pool": {...}
}
```

---

## 使用示例

```bash
# 查询代币信息
skill: query-token-info

# 查询代币安全
skill: query-token-audit

# 市场排名
skill: crypto-market-rank

# 迷因币
skill: meme-rush

# 查看数据面板API
curl http://localhost:8888/api
```

---

*这是你的工具箱，熟练使用每个技能。*
