# 项目结构

这个项目围绕三条主流程组织：分析、监听、交易。

## 一、分析

用途：研究资产上线后的历史表现。

主模块：

```text
src/listing_agent/listing_analysis.py
```

快捷入口：

```bash
scripts/analyze --dex xyz --output-dir reports/xyz_tradefi --resume
```

输出：

```text
reports/*/listing_performance.csv
reports/*/data_quality.csv
reports/*/summary_performance.csv
```

## 二、监听

用途：发现 XYZ 新资产、验证市场状态、给机会打分并发送告警。

主包：

```text
src/listing_agent/monitor/
```

关键文件：

```text
metadata_watcher.py   REST 元数据差异检测
all_mids_watcher.py   WebSocket allMids 新 key 检测
verifier.py           市场上下文、盘口、成交、状态推断
scoring.py            机会评分和推荐动作
storage.py            本地 JSON/JSONL 事件与快照存储
runner.py             监听 CLI
```

快捷入口：

```bash
scripts/monitor --dex xyz --state-dir state/monitor --init-baseline
scripts/monitor --dex xyz --state-dir state/monitor --poll-interval 2 --with-ws
```

输出：

```text
state/monitor/assets.json
state/monitor/asset_events.jsonl
state/monitor/asset_snapshots.jsonl
state/monitor/alerts.jsonl
```

## 三、交易

用途：执行 preflight 检查、dry-run 下单意图，以及经过明确确认的小额实盘订单。

主模块：

```text
src/listing_agent/main.py
src/listing_agent/risk.py
src/listing_agent/validator.py
src/listing_agent/execution.py
```

快捷入口：

```bash
scripts/trade preflight BTC
scripts/trade buy BTC --notional 5 --yes
scripts/trade close BTC --yes
```

实盘交易受配置限制、环境变量密钥、显式确认和 `state/STOP` kill switch 保护。

## 四、统一入口

安装后的统一命令是：

```bash
trade-xyz analyze ...
trade-xyz monitor ...
trade-xyz trade ...
```

本地脚本会自动设置 `PYTHONPATH=src`，用法更短。
