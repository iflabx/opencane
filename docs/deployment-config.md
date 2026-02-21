# 部署与配置

## 1. 配置模板

仓库提供三套模板：

- `CONFIG_PROFILE_DEV.json`
- `CONFIG_PROFILE_STAGING.json`
- `CONFIG_PROFILE_PROD.json`

应用模板：

```bash
opencane config profile apply --profile CONFIG_PROFILE_STAGING.json
opencane config check --strict
```

## 2. 关键配置项

### 2.1 模型与提供方

- `providers.*.apiKey`
- `agents.defaults.model`

### 2.2 硬件与网络

- `hardware.adapter`
- `hardware.deviceProfile`（`generic_mqtt` 时生效）
- `hardware.profileOverrides.*`（按模组覆盖 topic/qos/心跳参数）
- `hardware.controlHost/controlPort`
- `hardware.mqtt.*`（EC600 / generic_mqtt）
- `hardware.strictStartup`
- `hardware.toolResult.enabled`
- `hardware.telemetry.normalizeEnabled`
- `hardware.telemetry.persistSamplesEnabled`

### 2.3 Lifelog / Digital Task

- `lifelog.sqlitePath`
- `lifelog.chromaPersistDir`
- `lifelog.vectorBackend` / `lifelog.qdrant*`
- `lifelog.embeddingEnabled` / `lifelog.embeddingModel`
- `lifelog.retention*`
- `digitalTask.sqlitePath`
- `digitalTask.maxConcurrentTasks`

### 2.4 安全

- `hardware.auth.enabled`
- `hardware.auth.token`
- `safety.*`
- `interaction.*`

## 3. 环境建议

- `dev`：mock 适配器、本地数据库
- `staging`：真实协议联调、严格启动
- `prod`：鉴权开启、TLS MQTT、容量参数调优

## 4. 环境变量兼容说明

- 当前配置模型仍兼容 `NANOBOT_` 前缀环境变量（用于历史部署平滑迁移）
- 新部署建议优先使用配置文件（`~/.opencane/config.json`）统一管理
