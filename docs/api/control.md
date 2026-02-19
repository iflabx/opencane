# 控制 API

## 1. 基础信息

- Base URL: `http://<host>:<control_port>`
- 默认端口：`18792`
- 内容类型：`application/json`

## 2. 鉴权与安全头

当 `hardware.auth.enabled=true` 时，任选一种：

- `Authorization: Bearer <token>`
- `X-Auth-Token: <token>`

可选防重放（启用时必填）：

- `X-Request-Nonce`
- `X-Request-Timestamp`

## 3. 运行时接口

- `GET /v1/runtime/status`
- `GET /v1/runtime/observability`
- `GET /v1/runtime/observability/history`

## 4. 设备管理接口

- `POST /v1/device/register`
- `POST /v1/device/bind`
- `POST /v1/device/activate`
- `POST /v1/device/revoke`
- `GET /v1/device/binding`
- `GET /v1/device/{device_id}/status`

## 5. 设备操作接口

- `POST /v1/device/ops/dispatch`
- `POST /v1/device/ops/{operation_id}/ack`
- `GET /v1/device/ops`

快捷路径（等价于 dispatch）：

- `POST /v1/device/{device_id}/set_config`
- `POST /v1/device/{device_id}/tool_call`
- `POST /v1/device/{device_id}/ota_plan`

## 6. 示例

```bash
curl -X POST http://127.0.0.1:18792/v1/device/register \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"dev-001"}'
```

```bash
curl http://127.0.0.1:18792/v1/device/ops?device_id=dev-001
```
