# 开发计划

> 参考文档: `poly_mm_backtest/docs/data_collection_guide.md`

---

## 数据架构：原始 JSONL → 本地 NPZ

**VPS 只保存原始 WS 消息（JSONL 格式），NPZ 转换在本地完成。**

为什么不在 VPS 直接生成 NPZ：
- 转换逻辑有 bug → 原始数据还在，可重新处理
- event_dtype 定义变了 → 不需要重新采集
- JSONL 可读可调试，NPZ 二进制不可读
- VPS 不需要安装 numpy，依赖更少更稳定

```
VPS:   WS 消息 → JSONL（按 token/天 分文件）
  ↓ rsync (每小时增量同步)
本地:  JSONL → NPZ 转换 → hftbacktest 回测
```

### JSONL 文件格式

每行一条 WS 消息，附加 `local_ts`（本地接收时间）：

```jsonl
{"local_ts":1774306772465123456,"event_type":"book","asset_id":"TOKEN_ID",...}
{"local_ts":1774306780000123456,"event_type":"price_change",...}
{"local_ts":1774306785000123456,"event_type":"last_trade_price",...}
```

文件命名：`data/{asset}_{tf}/{date}/{token_id}.jsonl.gz`

### 本地 NPZ 转换目标格式

### NPZ event_dtype

| 字段 | 类型 | 说明 |
|---|---|---|
| `ev` | uint64 | 事件类型标志位（位掩码） |
| `exch_ts` | int64 | 交易所时间戳（纳秒） |
| `local_ts` | int64 | 本地接收时间戳（纳秒） |
| `px` | float64 | 价格 |
| `qty` | float64 | 数量 (shares) |
| `order_id` | uint64 | 保留（填 0） |
| `ival` | int64 | 保留（填 0） |
| `fval` | float64 | 保留（填 0） |

### 事件类型常量

```python
INIT_CLEAR    = 0xc0000003  # 初始清除
BUY_DEPTH     = 0xe0000001  # bid 增量更新
SELL_DEPTH    = 0xd0000001  # ask 增量更新
BUY_TRADE     = 0xe0000002  # 买方主动成交
SELL_TRADE    = 0xd0000002  # 卖方主动成交
BUY_SNAPSHOT  = 0xe0000004  # bid 快照
SELL_SNAPSHOT = 0xd0000004  # ask 快照
```

### WS 消息 → hbt 事件映射

| WS event_type | hbt 事件 | 映射规则 |
|---|---|---|
| `book` | `INIT_CLEAR` + `BUY/SELL_SNAPSHOT` | 先清旧 book，再逐 level 写快照 |
| `price_change` | `BUY_DEPTH` / `SELL_DEPTH` | side=BUY→BUY_DEPTH, size=绝对量, 0=清空 |
| `last_trade_price` | `BUY_TRADE` / `SELL_TRADE` | side=BUY→买方吃 ask |

时间戳：`int(msg["timestamp"]) * 1_000_000`（ms → ns）

---

## WS 连接规范

```
URL:        wss://ws-subscriptions-clob.polymarket.com/ws/market
订阅消息:   {"assets_ids": ["<YES_TOKEN_ID>"], "type": "market", "custom_feature_enabled": true}
心跳:       每 8 秒发送 "PING"（纯文本），服务端回 "PONG"（10s 超时）
Token 来源: Gamma API /events → market.clobTokenIds[0] = YES, [1] = NO
```

---

## Phase 1: 核心采集器 + 单资产验证

### 1.1 WS 采集器
- [ ] 实现 asyncio WebSocket 客户端（基于 `websockets` 库）
- [ ] 连接 → 订阅 → 心跳（8s PING）→ 消息处理循环
- [ ] 断线自动重连（指数退避 3s → 6s → 12s → 30s max）
- [ ] 消息附加 `local_ts`（time.time_ns()），写入 JSONL 文件
- [ ] 按 token_id + 日期分文件：`data/{asset}_{tf}/{date}/{token_id}.jsonl`
- [ ] 定期 gzip 压缩已完成的文件

### 1.2 市场发现
- [ ] 通过 Gamma API `/events?slug=xxx&closed=false` 获取活跃市场
- [ ] 提取 `conditionId`, `clobTokenIds[0]`(YES), `endDate`, `question`
- [ ] 每小时轮询一次，新市场自动加入订阅
- [ ] 过期市场保存 NPZ 后取消订阅

### 1.3 JSONL 存储
- [ ] 每个市场生命周期结束（结算后 ~1min）→ flush 文件 → gzip 压缩
- [ ] 每个 token 一个 JSONL 文件，只存 YES(UP) 侧
- [ ] 文件命名：`data/{asset}_{tf}/{date}/{slug}.jsonl.gz`

### 1.4 本地验证
- [ ] 在本地 Windows 运行，采集 1 个 BTC 1H 市场完整生命周期
- [ ] 检查 JSONL 完整性：消息类型齐全（book + price_change + last_trade_price）
- [ ] 本地运行 JSONL → NPZ 转换脚本
- [ ] 用 hftbacktest 加载 NPZ 验证：book 能构建、事件类型齐全、时间戳单调

**验收标准**: 采集 1 个 BTC 1H 市场 → JSONL → NPZ → hftbacktest 加载成功

---

## Phase 2: 多资产 + 市场生命周期管理

### 2.1 多市场并发
- [ ] 单 WS 连接订阅多个 token_id（验证连接上限）
- [ ] 如超限，分多个 WS 连接（每连接 20-30 tokens）
- [ ] 4 资产 × 3 时间框架 = ~124 活跃 token

### 2.2 市场生命周期
- [ ] **发现**: Gamma API 轮询，新 candle 通常在整点前 ~30 分钟出现
- [ ] **订阅**: 发现后立即订阅 YES token，抢 `book` 初始快照
- [ ] **采集**: 持续收 `price_change` + `last_trade_price`
- [ ] **归档**: 结算后 1 分钟保存 NPZ 到 `data/{asset}_{tf}/{slug}.npz`
- [ ] **清理**: 释放 buffer 内存

### 2.3 配置化
- [ ] YAML 配置：采集目标（资产/时间框架）、存储路径、WS 参数
- [ ] 支持运行时热加载配置（新增/删除采集目标）

### 2.4 Tick Size 查询
- [ ] 新市场订阅前查询 `GET /tick-size?token_id=xxx`
- [ ] 存入 NPZ 元数据（backtest 需要）

**验收标准**: BTC + ETH 的 1H + 4H 同时采集，运行 4 小时无异常

---

## Phase 3: VPS 部署 + 生产化

### 3.1 部署环境

| 项目 | 推荐 | 说明 |
|---|---|---|
| **位置** | AWS us-east-1 (弗吉尼亚) 或低价 VPS | Polymarket CLOB 后端在 us-east-1，WS 延迟 1-5ms |
| **配置** | 1-2 vCPU, 1-2GB RAM, 40GB SSD | 数据采集不需要大计算 |
| **系统** | Ubuntu 22.04 LTS | Python 3.12 |
| **预算** | 咸鱼 ~20-50 元/月 或 AWS t3.small ~$15/月 | |

### 3.2 部署步骤
- [ ] VPS 初始化脚本（Python 3.12 + venv + 依赖）
- [ ] systemd service 文件（`Restart=always`，崩溃自动重启）
- [ ] 日志配置（`logrotate`）
- [ ] 磁盘空间监控脚本（低于 5GB 告警）

### 3.3 数据同步
- [ ] rsync 定时脚本：VPS → 本地（每小时增量同步）
- [ ] 可选：S3 中转（长期方案）
- [ ] 可选：rclone 上传网盘

### 3.4 运维
- [ ] crontab 每小时执行：市场发现刷新 + buffer flush
- [ ] 简单 HTTP 健康检查端点（端口可选）
- [ ] TODO: 微信/Telegram 告警通知（后续）

**验收标准**: VPS 部署后连续运行 24 小时，4 资产 × 3 时间框架全部稳定采集

---

## Phase 4: 本地 NPZ 转换 + 回测对接

### 4.1 JSONL → NPZ 转换器
- [ ] 解析 JSONL 的 `book` / `price_change` / `last_trade_price` 消息
- [ ] 映射为 hftbacktest event_dtype 行
- [ ] 按 `exch_ts` 排序保证因果性
- [ ] 输出压缩 NPZ：`npz/{asset}_{tf}/{slug}.npz`
- [ ] 批量转换脚本：遍历 `data/` 目录下所有 JSONL

### 4.2 NPZ 格式对齐
- [ ] 确认输出 NPZ 与现有 `06_convert_to_npz.py` 格式一致
- [ ] 数据质量检查脚本（事件类型齐全、时间戳单调、book 可构建）

### 4.3 UP→DOWN 镜像工具
- [ ] 从 UP JSONL/NPZ 生成 DOWN NPZ：`px' = 1 - px`，BUY↔SELL 互换
- [ ] 验证：镜像数据与直接采集的 DOWN 数据一致

### 4.4 回测集成
- [ ] 与 `07_test_backtest.py` 流程打通
- [ ] 批量回测脚本：遍历 `npz/{asset}_{tf}/` 目录

**验收标准**: JSONL → NPZ → hftbacktest 回测流程跑通

---

## 项目文件结构（最终）

```
live_data_collector/
├── README.md
├── PLAN.md
├── config.yaml
├── requirements.txt          # VPS: websockets, requests, pyyaml
│                             # 本地额外: numpy
├── src/
│   ├── __init__.py
│   ├── config.py             # 配置加载
│   ├── constants.py          # WS URL + 采集常量
│   ├── market_discovery.py   # Gamma API 市场发现
│   ├── ws_collector.py       # WebSocket 采集 → JSONL
│   └── main.py               # asyncio 主入口
├── converter/                # 本地转换工具（不部署到 VPS）
│   ├── jsonl_to_npz.py       # JSONL → hftbacktest NPZ
│   ├── mirror.py             # UP → DOWN 镜像转换
│   ├── verify_npz.py         # NPZ 质量检查
│   └── batch_convert.py      # 批量转换脚本
├── scripts/
│   ├── setup_vps.sh          # VPS 初始化
│   └── sync_to_local.sh      # rsync 数据同步
├── deploy/
│   ├── polymarket-collector.service  # systemd
│   └── logrotate.conf        # 日志轮转
└── data/                     # JSONL 原始数据（git ignore）
    ├── btc_1h/{date}/{slug}.jsonl.gz
    ├── btc_4h/
    ├── eth_1h/
    └── ...
```

---

## 风险 & 应对

| 风险 | 影响 | 应对 |
|---|---|---|
| WS 单连接订阅上限 | 无法订阅 124 tokens | 分多个连接，每连接 20-30 tokens |
| WS 消息丢失 | OB 增量不完整 | 定期 REST `GET /book` 拉全量快照校验 |
| 心跳超时断连 | 数据中断 | 8s PING + 自动重连 + 重新获取 book 快照 |
| 新 candle 市场延迟创建 | 漏采前几秒数据 | Gamma API 每 5 分钟轮询，容忍微量丢失 |
| VPS 网络不稳 | 数据中断 | systemd Restart=always + 重连 + REST 补数据 |
| Polymarket API 变更 | 采集中断 | 版本化消息解析 + 监控告警 |
| 磁盘写满 | 进程崩溃 | 定期清理已同步数据 + 磁盘监控 |

---

## API Rate Limits（需验证）

| API | 估计限制 | 用途 | 频率 |
|---|---|---|---|
| Gamma REST | ~60 req/min | 市场发现 | 每小时 ~10 次 |
| CLOB REST `/book` | 未明确 | 全量快照校验 | 每 5 分钟/token |
| CLOB REST `/tick-size` | 未明确 | tick_size 查询 | 每新市场 1 次 |
| CLOB WebSocket | 未明确单连接上限 | 实时 OB + trades | 持续连接 |
