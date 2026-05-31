# 云服务器部署

目标：把监听模块部署到云服务器上常驻运行，避免本地电脑关机后监听中断。

默认只部署监听服务，不部署自动交易服务。交易相关命令仍然需要人工手动执行。

## 一、服务器建议

推荐环境：

```text
Ubuntu 22.04 或 24.04
1 vCPU / 1GB RAM 起步
Python 3.11+
只需要出站访问 api.hyperliquid.xyz
```

安全建议：

- 只开放 SSH 入站。
- 不把私钥写入仓库。
- 默认不在服务器上配置实盘交易密钥。
- 常驻服务只运行 `monitor`，不运行 `trade buy`。

## 二、准备服务器用户

在服务器上执行：

```bash
sudo adduser --system --group --home /opt/trade_xyz_listing_agent tradexyz
sudo mkdir -p /opt/trade_xyz_listing_agent
sudo chown -R tradexyz:tradexyz /opt/trade_xyz_listing_agent
```

## 三、上传代码

在本地项目目录执行，把代码同步到服务器：

```bash
rsync -av \
  --exclude .venv \
  --exclude __pycache__ \
  --exclude reports \
  --exclude logs \
  --exclude state \
  ./ YOUR_SERVER:/opt/trade_xyz_listing_agent/
```

然后在服务器上修正属主：

```bash
sudo chown -R tradexyz:tradexyz /opt/trade_xyz_listing_agent
```

## 四、安装依赖

在服务器上执行：

```bash
sudo -u tradexyz bash -lc '
  cd /opt/trade_xyz_listing_agent
  python3 -m venv .venv
  . .venv/bin/activate
  python -m pip install -U pip
  python -m pip install -e ".[monitor]"
  scripts/check
'
```

如果 `scripts/check` 通过，说明代码和基础依赖正常。

## 五、初始化监听 baseline

第一次启动常驻服务前，先初始化当前 XYZ 资产 baseline，避免对历史资产刷告警：

```bash
sudo -u tradexyz bash -lc '
  cd /opt/trade_xyz_listing_agent
  scripts/monitor-xyz --init-baseline
  scripts/monitor-xyz --once
'
```

预期：

```text
Initialized xyz monitor baseline at state/monitor
Checked xyz; new_assets=0
```

## 六、安装 systemd 服务

在服务器上执行：

```bash
sudo cp /opt/trade_xyz_listing_agent/deploy/systemd/trade-xyz-monitor.service /etc/systemd/system/trade-xyz-monitor.service
sudo cp /opt/trade_xyz_listing_agent/deploy/systemd/trade-xyz-monitor.env.example /etc/trade-xyz-monitor.env
sudo systemctl daemon-reload
sudo systemctl enable --now trade-xyz-monitor
```

查看状态：

```bash
systemctl status trade-xyz-monitor
```

查看实时日志：

```bash
journalctl -u trade-xyz-monitor -f
```

停止服务：

```bash
sudo systemctl stop trade-xyz-monitor
```

重启服务：

```bash
sudo systemctl restart trade-xyz-monitor
```

## 七、运行中的数据

监听数据写在：

```text
state/monitor/assets.json
state/monitor/asset_events.jsonl
state/monitor/asset_snapshots.jsonl
state/monitor/alerts.jsonl
```

这些文件需要定期备份。最重要的是：

```text
state/monitor/assets.json
state/monitor/asset_events.jsonl
```

## 八、更新代码

更新时：

```bash
sudo systemctl stop trade-xyz-monitor
```

从本地重新同步：

```bash
rsync -av \
  --exclude .venv \
  --exclude __pycache__ \
  --exclude reports \
  --exclude logs \
  --exclude state \
  ./ YOUR_SERVER:/opt/trade_xyz_listing_agent/
```

服务器上执行：

```bash
sudo chown -R tradexyz:tradexyz /opt/trade_xyz_listing_agent
sudo -u tradexyz bash -lc '
  cd /opt/trade_xyz_listing_agent
  . .venv/bin/activate
  python -m pip install -e ".[monitor]"
  scripts/check
'
sudo systemctl start trade-xyz-monitor
```

## 九、告警

当前 service 默认不带 webhook。需要 webhook 时，可以先手动测试：

```bash
scripts/monitor-xyz --verify xyz:BB --webhook-url YOUR_WEBHOOK_URL
```

确认可用后，再把 `deploy/systemd/trade-xyz-monitor.service` 里的 `ExecStart` 改成带 `--webhook-url` 的版本。

## 十、不要把交易模块做成常驻服务

当前建议：

```text
监听：可以常驻
分析：按需执行
交易：人工确认后手动执行
```

如果未来要做半自动交易，应当单独设计服务、审批流程、风险限额和紧急停机方案。
