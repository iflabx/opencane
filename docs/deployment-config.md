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

## 5. 真实硬件生产 Docker（单容器）

推荐模式：

- 单容器运行 `opencane hardware serve`
- 配置、数据、工作区全部外置到宿主机
- 控制 API 仅内网暴露 + token 鉴权

已提供模板：

- Compose：`deploy/docker-compose.prod.yml`
- 环境变量模板：`deploy/runtime.env.example`
- 落地步骤：`deploy/README.md`

核心外置目录（示例）：

- `/srv/opencane/config/config.json`
- `/srv/opencane/workspace`
- `/srv/opencane/data`
- `/srv/opencane/runtime.env`

启动：

```bash
docker compose -f deploy/docker-compose.prod.yml up -d
```

健康检查：

```bash
curl http://127.0.0.1:18792/v1/runtime/status
curl http://127.0.0.1:18792/v1/runtime/observability
```
