# 测试清单

这是最快的三条工作流检查方式。

## 1. 总体烟雾测试

先跑这个：

```bash
scripts/check
```

预期结果：

- 单元测试通过
- 源码编译通过

## 2. 分析检查

修改历史表现逻辑时跑这些：

```bash
scripts/analyze --symbols BB,QNT,CBRS --dex xyz --output-dir reports/test_windows
scripts/analyze-xyz --resume
scripts/analyze-xyz-stocks --resume
```

预期结果：

- 写出 `listing_performance.csv`
- 写出 `data_quality.csv`
- `summary_performance.csv` 包含收益和成交量字段

## 3. 监听检查

修改发现、评分或告警时跑这些：

```bash
scripts/monitor --dex xyz --state-dir state/monitor --init-baseline
scripts/monitor --dex xyz --state-dir state/monitor --once
scripts/monitor --dex xyz --state-dir state/monitor --verify xyz:BB
```

可选的 WebSocket 检查：

```bash
scripts/monitor --dex xyz --state-dir state/monitor --poll-interval 2 --with-ws
```

预期结果：

- baseline 初始化时不刷告警
- 稳定 baseline 下，diff 结果显示 `new_assets=0`
- verifier 会打印状态和分数

## 4. 交易检查

修改 preflight、风控或执行代码时跑这些：

```bash
scripts/trade preflight BTC
scripts/trade --simulate-order TEST --simulate-market perp --simulate-asset-id 999
```

可选的实盘账户检查：

```bash
scripts/trade preflight BTC
```

预期结果：

- dry-run 模拟会写审计事件
- preflight 会打印账户和市场状态，但不会下单

## 5. 常用命令速查

```bash
scripts/analyze --help
scripts/monitor --help
scripts/trade --help
scripts/test
```
