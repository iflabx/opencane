# 运维手册

## 1. 启停

启动：

```bash
nanobot hardware serve --adapter ec600 --logs
```

停止：

- 前台进程：`Ctrl+C`
- 进程托管模式：按 systemd/supervisor 策略停止

## 2. 日常检查

1. 运行时健康：`GET /v1/runtime/status`
2. 指标健康：`GET /v1/runtime/observability`
3. 队列趋势：`GET /v1/runtime/observability/history`
4. 任务积压：`GET /v1/digital-task?status=pending`

## 3. 常见故障

### 3.1 启动失败

排查：

- `nanobot config check --strict`
- Provider API key 是否有效
- MQTT 地址/账号密码是否可达

### 3.2 控制 API 401

排查：

- token 是否一致
- Header 是否使用 `Authorization: Bearer` 或 `X-Auth-Token`

### 3.3 图像处理延迟升高

排查：

- `ingest_queue_utilization`
- `ingest_queue_depth`
- `ingest_queue_rejected_total`

措施：

- 增大 `lifelog.ingestQueueMaxSize`
- 增加 `lifelog.ingestWorkers`
- 调整 overflow policy

## 4. 变更发布建议

1. 先在 staging 验证
2. 观察 24h 核心指标
3. 再发布到 prod

## 5. 数据治理基线

### 5.1 运行中清理 retention

手动触发：

```bash
curl -X POST http://127.0.0.1:18792/v1/lifelog/retention/cleanup \
  -H 'Content-Type: application/json' \
  -d '{"runtime_events_days":30,"thought_traces_days":30,"device_sessions_days":30,"device_operations_days":30,"telemetry_samples_days":7}'
```

### 5.2 本地备份与恢复

备份：

```bash
python scripts/lifelog_backup_restore.py backup \
  --sqlite ~/.nanobot/data/lifelog/lifelog.db \
  --images ~/.nanobot/data/lifelog/images \
  --out ./lifelog-backup-$(date +%Y%m%d).tar.gz
```

恢复：

```bash
python scripts/lifelog_backup_restore.py restore \
  --archive ./lifelog-backup-20260220.tar.gz \
  --dest ~/.nanobot/restore/lifelog \
  --overwrite
```
