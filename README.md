# Polymarket Live Data Collector

> 实时采集 Polymarket Up-or-Down 系列市场的订单簿和成交数据

## 目标

采集 BTC / ETH / SOL / XRP 的 1H / 4H / 1D Up-or-Down 市场数据，用于做市策略回测和实盘研究。

## 为什么不用 Struct API

| 方案 | 单日 BTC 1H 成本 | 4资产×3时间框架×30天 成本 |
|---|---|---|
| Struct API | ~5000 credits | ~150,000 credits |
| **CLOB WebSocket** | **免费** | **免费**（仅 VPS 费用） |

Struct API 的 `order-book/history` 端点每页收费，一个 BTC 1H 市场的订单簿历史约 40 页（~7800 条快照），24 个市场/天 = ~960 次 API 调用。批量采集完全不经济。

## 核心原理：CTF 镜像

Polymarket 基于 Gnosis CTF，UP (YES) 和 DOWN (NO) 的订单簿是同一组订单的两种视图：

```
UP  BID @$p  ←→  DOWN ASK @$(1-p)
UP  ASK @$p  ←→  DOWN BID @$(1-p)
```

**只采集 UP 一边的订单簿，DOWN 通过价格翻转 `1 - p` 推导。** 数据量减半，信息无损。

## 架构

```
┌───────────────────────────────────────────────────────────┐
│                    VPS (云服务器)                          │
│                                                           │
│  ┌──────────────┐  Gamma REST    ┌─────────────────┐     │
│  │ Gamma API    │ ←────────────→ │ market_discovery │     │
│  │ (免费)       │   每小时轮询    │ 发现新市场       │     │
│  └──────────────┘                └────────┬────────┘     │
│                                           │              │
│  ┌──────────────┐  WebSocket     ┌────────▼────────┐     │
│  │ CLOB API     │ ←────────────→ │ ws_collector    │     │
│  │ (免费)       │   实时推送      │ 订单簿+成交     │     │
│  └──────────────┘                └────────┬────────┘     │
│                                           │              │
│                                  ┌────────▼────────┐     │
│                                  │ Storage Layer   │     │
│                                  │ SQLite + Parquet│     │
│                                  └────────┬────────┘     │
│                                           │              │
│  ┌──────────────┐   rsync/scp    ┌────────▼────────┐     │
│  │ 本地电脑      │ ←────────────  │ sync_service   │     │
│  │ (研究用)     │   每小时同步    │                 │     │
│  └──────────────┘                └─────────────────┘     │
└───────────────────────────────────────────────────────────┘
```

## 采集范围

### 目标资产 & 时间框架

| 资产 | Series Slug (Gamma) | 1H | 4H | 1D |
|---|---|---|---|---|
| BTC | `btc-up-or-down-hourly` / `bitcoin-neg-risk-4h` / `bitcoin-neg-risk` | ✅ 24/天 | ✅ 6/天 | ✅ 1/天 |
| ETH | `eth-up-or-down-hourly` / `ethereum-neg-risk-4h` / `ethereum-neg-risk` | ✅ 24/天 | ✅ 6/天 | ✅ 1/天 |
| SOL | `sol-up-or-down-hourly` / `solana-neg-risk-4h` / `solana-neg-risk` | ✅ 24/天 | ✅ 6/天 | ✅ 1/天 |
| XRP | `xrp-up-or-down-hourly` / `xrp-neg-risk-4h` / `xrp-neg-risk` | ✅ 24/天 | ✅ 6/天 | ✅ 1/天 |

### 活跃市场数量估算

| 时间框架 | 每资产活跃市场 | 4资产合计 | WS 连接数 |
|---|---|---|---|
| 1H | ~24 | 96 | 96 |
| 4H | ~6 | 24 | 24 |
| 1D | ~1 | 4 | 4 |
| **合计** | ~31 | **124** | **124** |

### 数据量估算

| 指标 | 估算值 |
|---|---|
| 每日原始数据 | ~1 GB |
| 每月原始数据 | ~30 GB |
| 每日压缩后 | ~200 MB |
| 每月压缩后 | ~6 GB |

## 数据采集策略

### 只接 UP (YES) Token

每个 Polymarket Up-or-Down 市场有两个 token：
- UP (YES) token: `clobTokenIds[0]`（Gamma API 返回顺序）
- DOWN (NO) token: `clobTokenIds[1]`

**只订阅 UP token 的订单簿**。DOWN 订单簿可这样推导（在本地 NPZ 转换时完成）：

```python
def mirror_orderbook(up_ob):
    """UP orderbook → DOWN orderbook (价格翻转)"""
    return {
        'bids': [{'p': round(1 - float(a['p']), 4), 's': a['s']} 
                 for a in sorted(up_ob['asks'], key=lambda x: float(x['p']))],
        'asks': [{'p': round(1 - float(b['p']), 4), 's': b['s']} 
                 for b in sorted(up_ob['bids'], key=lambda x: float(x['p']), reverse=True)],
    }
```

### 直接输出原始 JSONL，本地转 NPZ

**VPS 只保存原始 WS 消息（JSONL 格式），NPZ 转换在本地完成。**

为什么不在 VPS 直接生成 NPZ：
- 转换逻辑有 bug → 原始数据还在，可重新处理
- event_dtype 定义变了 → 不需要重新采集
- JSONL 可读可调试，NPZ 二进制不可读
- VPS 不需要 numpy，依赖更少更稳定

VPS 上的 JSONL 文件格式（每行一条 WS 消息 + local_ts）：
```jsonl
{"local_ts":1774306772465123456,"event_type":"book","asset_id":"TOKEN_ID",...}
{"local_ts":1774306780000123456,"event_type":"price_change",...}
{"local_ts":1774306785000123456,"event_type":"last_trade_price",...}
```

本地转换时做 WS 消息 → hbt event_dtype 映射：

| WS event_type | hbt 事件 | 说明 |
|---|---|---|
| `book` | `INIT_CLEAR` → `BUY/SELL_SNAPSHOT` | 初始全量快照（连接后首次推送） |
| `price_change` | `BUY_DEPTH` / `SELL_DEPTH` | 深度增量更新（size=0 表示该价位清空） |
| `last_trade_price` | `BUY_TRADE` / `SELL_TRADE` | 成交推送 |

时间戳：`int(msg["timestamp"]) * 1_000_000`（Polymarket ms → hbt ns）

### 采集内容

| 数据类型 | 采集方式 | 频率 | 说明 |
|---|---|---|---|
| 订单簿快照 + 增量 | CLOB WebSocket | 实时 | `book` + `price_change` |
| 成交记录 | CLOB WebSocket | 实时 | `last_trade_price` |
| 市场元数据 | Gamma REST `/events` | 每小时 | 发现新市场、获取 token_id |
| tick_size | CLOB REST `/tick-size` | 每新市场 1 次 | backtest 需要 |

### 市圼生命周期

```
BTC 1H 示例:
09:00 ET → 新市场创建（Gamma API 可发现）
           → 订阅 YES token WS
           → 收到 book 初始快照
09:00-10:00 ET → 持续收 price_change + last_trade_price
                  → 实时写入 JSONL
10:00 ET → 结算，关闭 JSONL 文件，gzip 压缩
           → 取消订阅，释放资源
```

### 本地转换流程

```
1. rsync 同步 JSONL.gz 到本地
2. 运行 converter/jsonl_to_npz.py → 生成 hftbacktest NPZ
3. 运行 converter/verify_npz.py → 质量检查
4. 可选: converter/mirror.py → UP NPZ 生成 DOWN NPZ
```

### 本地数据同步

VPS 采集的数据需要同步到本地用于分析和回测。

#### 同步原理

`scripts/sync_to_local.sh` 使用 rsync **只同步已完成（gzip 压缩后）的数据**：
- ✅ 下载 `*.jsonl.gz` — 已结束并压缩的市场数据
- ❌ 跳过 `*.jsonl` — 仍在活跃采集的市场

这意味着只有市场结算后（文件自动 gzip 压缩），数据才会同步到本地。

#### 使用方法

**前提**: 本地需安装 rsync 和 SSH（Windows 推荐使用 Git Bash 或 WSL）

```bash
# 基本用法
bash scripts/sync_to_local.sh [VPS_HOST] [SSH_PORT] [LOCAL_DIR]

# 示例（使用默认配置）
bash scripts/sync_to_local.sh

# 指定参数
bash scripts/sync_to_local.sh root@your-vps-ip 22 /path/to/local/data

# Windows (Git Bash)
bash scripts/sync_to_local.sh root@your-vps-ip 22 D:/polymarket_data/live
```

#### 定时自动同步（推荐）

**Linux/macOS** — 加入 crontab 每小时同步：
```bash
crontab -e
# 添加以下行:
0 * * * * /path/to/scripts/sync_to_local.sh root@vps-ip 22 /path/to/local/data >> /tmp/polymarket_sync.log 2>&1
```

**Windows** — 使用 Task Scheduler：
1. 创建基本任务 → 触发器设为每小时
2. 操作: 启动程序 → `C:\Program Files\Git\bin\bash.exe`
3. 参数: `-c "/path/to/sync_to_local.sh root@vps-ip 22 D:/polymarket_data/live"`

#### 同步后的本地目录结构

```
D:/polymarket_data/live/
├── btc_1h/
│   └── 2026-03-26/
│       ├── bitcoin-up-or-down-march-26-2026-4am-et.jsonl.gz
│       ├── bitcoin-up-or-down-march-26-2026-5am-et.jsonl.gz
│       └── ...
├── btc_4h/
├── eth_1h/
├── sol_1h/
└── xrp_1h/
```

#### 手动检查同步状态

```bash
# VPS 上查看已压缩文件数（可同步）
find data/ -name "*.jsonl.gz" | wc -l

# VPS 上查看仍在采集的文件（不会同步）
find data/ -name "*.jsonl" | wc -l

# 本地查看已同步的数据量
du -sh /path/to/local/data/
```

## VPS 部署要求

### 推荐配置

| 项目 | 推荐 | 说明 |
|---|---|---|
| **位置** | AWS us-east-1 (弗吉尼亚) 或低价 VPS | Polymarket CLOB 后端在 us-east-1，WS 延迟 1-5ms |
| **CPU** | 1-2 核 | 数据采集不需要大计算 |
| **内存** | 1-2 GB | 124 tokens 的内存 buffer |
| **硬盘** | 40 GB SSD | 存 1 个月数据（~30GB 原始，压缩后 ~6GB） |
| **带宽** | 3-5 Mbps | |
| **系统** | Ubuntu 22.04 LTS | Python 3.12 |
| **预算** | 咸鱼 ~20-50 元/月 或 AWS t3.small ~$15/月 | |

> **关键**: 选 us-east-1 可获得最低 WS 延迟（1-5ms），数据质量更高。
> 如果用咸鱼便宜 VPS（非 us-east-1），延迟会高一些但对回测数据影响不大。

### 快速部署

```bash
# 一键 setup（推荐）
bash scripts/setup_vps.sh

# 或手动：
# 1. 安装系统依赖
apt update && apt install -y python3 python3-venv rsync

# 2. 创建虚拟环境 & 安装 Python 依赖
cd /usr/local/application/polymarket-hft-live-data-collector
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. 安装 systemd 服务
cp deploy/polymarket-collector.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable polymarket-collector
```

### 测试运行（前台）

```bash
cd /usr/local/application/polymarket-hft-live-data-collector
source .venv/bin/activate
python -m src.main -c config_test.yaml   # 仅采集 BTC 1H
python -m src.main -c config.yaml        # 全量采集
```

> Ctrl+C 可安全停止，程序会 flush 所有缓冲区。

### systemd 服务管理

采集器通过 **systemd 系统服务** 运行，优于 screen/tmux：
- 开机自启
- 崩溃后 10 秒自动重启（`Restart=always`）
- 不依赖 SSH 会话
- 日志自动由 journald 管理

```bash
# 启动服务
systemctl start polymarket-collector

# 查看服务状态
systemctl status polymarket-collector

# 停止服务
systemctl stop polymarket-collector

# 重启服务
systemctl restart polymarket-collector

# 开机自启（setup 已执行）
systemctl enable polymarket-collector

# 取消开机自启
systemctl disable polymarket-collector
```

### 日志查看

```bash
# 实时日志（Ctrl+C 退出）
journalctl -u polymarket-collector -f

# 最近 100 行
journalctl -u polymarket-collector -n 100 --no-pager

# 今天的日志
journalctl -u polymarket-collector --since today --no-pager

# 搜索错误
journalctl -u polymarket-collector --no-pager | grep ERROR
```

### 常用运维命令

```bash
# 查看当前采集进程
systemctl status polymarket-collector

# 查看磁盘占用
du -sh data/*/

# 查看今天采集的文件数
find data/ -name "*.jsonl" -newer data/ -type f | wc -l

# 查看某个市场的数据行数
wc -l data/btc_1h/2026-03-26/*.jsonl

# 修改配置后重启
vi config.yaml
systemctl restart polymarket-collector

# 查看 systemd service 文件
cat /etc/systemd/system/polymarket-collector.service
```

## 项目文件结构

```
live_data_collector/
├── README.md                 # 本文件
├── PLAN.md                   # 开发计划（分阶段）
├── config.yaml               # 采集配置
├── requirements.txt          # VPS: websockets, requests, pyyaml
│                             # 本地额外: numpy
├── src/                      # VPS 采集代码
│   ├── __init__.py
│   ├── config.py             # 配置加载
│   ├── constants.py          # WS URL + 采集常量
│   ├── market_discovery.py   # 市场发现（Gamma API）
│   ├── ws_collector.py       # WebSocket 采集 → JSONL 文件
│   └── main.py               # asyncio 主入口
├── converter/                # 本地转换工具（不部署到 VPS）
│   ├── jsonl_to_npz.py       # JSONL → hftbacktest NPZ
│   ├── mirror.py             # UP → DOWN 镜像转换
│   ├── verify_npz.py         # NPZ 质量检查
│   └── batch_convert.py      # 批量转换脚本
├── scripts/
│   ├── setup_vps.sh          # VPS 初始化脚本
│   └── sync_to_local.sh      # rsync 数据同步
├── deploy/
│   ├── polymarket-collector.service  # systemd 服务文件
│   └── logrotate.conf        # 日志轮转
└── data/                     # JSONL 原始数据（git ignore）
    ├── btc_1h/{date}/{slug}.jsonl.gz
    ├── btc_4h/
    ├── eth_1h/
    └── ...
```

## Polymarket API 端点参考

### Gamma API（市场发现，免费）

```python
# 获取活跃市场（推荐用 /events 端点，返回 clobTokenIds）
GET https://gamma-api.polymarket.com/events
    ?slug=bitcoin-up-or-down-hourly
    &closed=false
    &limit=50

# 返回结构:
# event.markets[].conditionId       → 市场条件ID
# event.markets[].clobTokenIds[0]   → YES (UP) token_id
# event.markets[].clobTokenIds[1]   → NO (DOWN) token_id
# event.markets[].endDate           → 结算时间
```

### CLOB API（订单簿 & 成交，免费）

```python
# REST - 全量订单簿（校验用）
GET https://clob.polymarket.com/book?token_id={token_id}

# REST - tick size 查询
GET https://clob.polymarket.com/tick-size?token_id={token_id}

# WebSocket - 实时数据流（核心采集源）
URL: wss://ws-subscriptions-clob.polymarket.com/ws/market

# 订阅消息:
{"assets_ids": ["{token_id}"], "type": "market", "custom_feature_enabled": true}

# 心跳: 每 8 秒发送 "PING"（纯文本），服务端回 "PONG"

# 接收事件类型:
#   book              → 连接后首次全量快照
#   price_change      → 深度增量更新
#   last_trade_price  → 成交推送
#   best_bid_ask      → BBO 更新（可选，可从 depth 重建）
```
