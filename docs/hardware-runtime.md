# 硬件运行时

## 1. 启动命令

```bash
nanobot hardware serve --adapter <mock|websocket|ec600|generic_mqtt> --logs
```

常用参数：

- `--adapter`: 覆盖适配器类型
- `--host` / `--port`: 适配器监听地址
- `--mqtt-host` / `--mqtt-port`: EC600 / generic_mqtt MQTT 覆盖
- `--control-port`: 控制 API 端口（默认 18792）
- `--strict-startup`: 依赖降级时失败退出
- `--logs`: 打开运行日志

## 2. 运行模式建议

- 本地开发：`mock`
- 协议联调：`ec600` + staging 配置
- 多模组联调：`generic_mqtt` + `hardware.deviceProfile`（推荐）
- 上线环境：`ec600` 或 `generic_mqtt` + prod 配置 + 鉴权开启

`generic_mqtt` 内置 profile（v1）：

- `ec600mcnle_v1`
- `a7670c_v1`
- `sim7600g_h_v1`
- `ec800m_v1`
- `ml307r_dl_v1`

## 3. 启动前检查

1. `nanobot config check --strict` 通过
2. Provider API Key 已配置
3. MQTT 连接参数正确（EC600 场景）
4. `hardware.auth.enabled=true` 且 token 已配置（非开发环境）

## 4. 核心运行指标

通过接口查看：

- `GET /v1/runtime/status`
- `GET /v1/runtime/observability`
- `GET /v1/runtime/observability/history`

重点关注：

- `voice_turn_failure_rate`
- `voice_turn_avg_latency_ms`
- `ingest_queue_utilization`
- `device_offline_rate`

## 5. 可选能力开关

- `hardware.toolResult.enabled`: 消费设备 `tool_result` 回执并写入运行事件
- `hardware.toolResult.markDeviceOperationEnabled`: 将 `tool_result` 回写到 `device_operation` 状态
- `hardware.telemetry.normalizeEnabled`: 启用 telemetry/IMU 结构化
- `hardware.telemetry.persistSamplesEnabled`: 将结构化 telemetry 样本入库

相关查询接口：

- `GET /v1/lifelog/telemetry_samples`
- `POST /v1/lifelog/retention/cleanup`
