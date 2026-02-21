# 快速开始

## 1. 环境要求

- Python 3.11+
- 可访问大模型提供方（例如 OpenRouter）
- 可选：MQTT Broker（EC600 / generic_mqtt 适配场景）

## 2. 安装

```bash
git clone https://github.com/iflabx/opencane.git
cd opencane
pip install -e .
```

## 3. 初始化配置

```bash
nanobot onboard
```

生成默认配置后，建议直接应用预设模板：

```bash
nanobot config profile apply --profile CONFIG_PROFILE_DEV.json
nanobot config check --strict
```

## 4. 最小可运行闭环（无硬件）

启动 mock 适配器：

```bash
nanobot hardware serve --adapter mock --logs
```

另开终端做健康检查：

```bash
curl http://127.0.0.1:18792/v1/runtime/status
curl http://127.0.0.1:18792/v1/runtime/observability
```

## 5. 切换到 EC600（联调）

```bash
nanobot config profile apply --profile CONFIG_PROFILE_STAGING.json
nanobot config check --strict
nanobot hardware serve --adapter ec600 --logs
```

## 6. 多模组联调（generic_mqtt）

```bash
nanobot config profile apply --profile CONFIG_PROFILE_STAGING.json
nanobot hardware serve --adapter generic_mqtt --logs
```

配置示例（`~/.nanobot/config.json`）：

- `hardware.deviceProfile = ec600mcnle_v1 | a7670c_v1 | sim7600g_h_v1 | ec800m_v1 | ml307r_dl_v1`
- 可选 `hardware.profileOverrides.mqtt.*` 覆盖 topic / qos / keepalive

确认以下配置已替换为真实值：

- `providers.openrouter.apiKey`
- `hardware.mqtt.host`
- `hardware.mqtt.username`
- `hardware.mqtt.password`
- `hardware.auth.token`

## 7. 常用调试命令

```bash
nanobot status
nanobot config check --strict
nanobot hardware serve --adapter mock --logs
```
