# 快速开始

## 1. 环境要求

- Python 3.11+
- 可访问大模型提供方（例如 OpenRouter）
- 可选：MQTT Broker（EC600 适配场景）

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

确认以下配置已替换为真实值：

- `providers.openrouter.apiKey`
- `hardware.mqtt.host`
- `hardware.mqtt.username`
- `hardware.mqtt.password`
- `hardware.auth.token`

## 6. 常用调试命令

```bash
nanobot status
nanobot config check --strict
nanobot hardware serve --adapter mock --logs
```
