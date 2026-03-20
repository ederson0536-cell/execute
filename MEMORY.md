# MEMORY.md - 记忆系统索引

> 版本：1.0 | 更新：2026-03-18

---

## 记忆系统架构

```
memory/
├── positions.md           # 当前持仓 (实时)
├── trading_log.md        # 交易日志 (所有交易记录)
├── lessons.md           # 交易教训 (亏损/盈利总结)
├── patterns.md          # 交易模式 (成功/失败模式库)
├── weekly.md            # 周总结 (每周复盘)
├── monthly.md           # 月总结 (每月复盘)
└── analysis/
    ├── daily_analysis.md   # 每日市场分析
    └── oi_signals.md      # OI 信号记录
```

---

## 快速索引

| 记忆类型 | 文件 | 用途 |
|----------|------|------|
| 持仓状态 | `positions.md` | 实时检查 |
| 历史交易 | `trading_log.md` | 复盘参考 |
| 交易教训 | `lessons.md` | 从错误学习 |
| 成功模式 | `patterns.md` | 入场参考 |
| 周复盘 | `weekly.md` | 周度总结 |
| 月复盘 | `monthly.md` | 月度总结 |
| 市场分析 | `analysis/daily_analysis.md` | 每日市场 |
| OI信号 | `analysis/oi_signals.md` | 信号验证 |

---

## 使用原则

### 写入时机
- 交易后 → 写入 `trading_log.md`
- 亏损后 → 写入 `lessons.md`
- 发现模式 → 写入 `patterns.md`
- 收盘后 → 写入 `daily_analysis.md`

### 读取时机
- 开仓前 → 读取 `patterns.md`
- 开盘前 → 读取 `daily_analysis.md`
- 复盘时 → 读取 `trading_log.md`

---

## 核心记忆

### 当前持仓
```
位置: memory/positions.md
内容: 所有未平仓合约的详细信息
```

### 交易历史
```
位置: memory/trading_log.md
内容: 所有平仓交易的完整记录
```

---

*这是记忆系统的入口，每次交易前查阅。*
