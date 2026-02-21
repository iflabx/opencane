# 多硬件蜂窝适配技术与使用指南

## 1. 目标

本指南说明如何在同一套后端中接入多种蜂窝模组，并保持语音、图像、记忆与控制 API 的主流程不变。  
实现原则是：核心 Runtime 只处理统一协议，模组差异全部下沉到适配层。

## 2. 实现架构

关键代码位置：

- 适配器工厂：`opencane/api/hardware_server.py` (`create_adapter_from_config`)
- 通用适配器：`opencane/hardware/adapter/generic_mqtt_adapter.py`
- 模组 profile：`opencane/hardware/adapter/device_profiles.py`
- 统一协议：`opencane/hardware/protocol/envelope.py`

数据路径：

1. 模组上行 MQTT 消息进入 `generic_mqtt`。
2. 适配层做 topic/payload 映射，转成 `CanonicalEnvelope`。
3. Runtime 按统一事件处理（语音回合、图像回合、telemetry 可选）。
4. 下行命令按 profile 映射后发布到模组下行 topic。

## 3. 内置模组 Profile（v1）

- `ec600mcnle_v1`
- `a7670c_v1`
- `sim7600g_h_v1`
- `ec800m_v1`
- `ml307r_dl_v1`

可用别名：`ec600`、`a7670c`、`sim7600g_h`、`ec800m`、`ml307r_dl`。

## 4. 配置说明

核心字段：

- `hardware.adapter = "generic_mqtt"`
- `hardware.deviceProfile = "<profile_name>"`
- `hardware.profileOverrides.mqtt.*`（topic/qos/keepalive/重连覆盖）
- `hardware.profileOverrides.packetMagic`（可选）
- `hardware.profileOverrides.audioUpMode = framed_packet | json_b64`（可选）

示例（EC800M）：

```json
{
  "hardware": {
    "adapter": "generic_mqtt",
    "deviceProfile": "ec800m_v1",
    "profileOverrides": {
      "mqtt": {
        "host": "YOUR_MQTT_HOST",
        "port": 1883,
        "upControlTopic": "device/+/up/control",
        "upAudioTopic": "device/+/up/audio"
      }
    }
  }
}
```

## 5. 使用步骤

1. 配置 `hardware.adapter` 与 `hardware.deviceProfile`。
2. 设置真实 MQTT 参数（`host/port/username/password/topic`）。
3. 启动服务：`opencane hardware serve --adapter generic_mqtt --logs`
4. 验证状态：`curl http://127.0.0.1:18792/v1/runtime/status`

## 6. 兼容性与降级

- 旧 `ec600` 适配器仍可直接使用，不受影响。
- 若模组不支持 telemetry/tool_result，系统自动降级，不阻塞主流程。

## 7. 常见问题

- `Unsupported hardware.device_profile`：`deviceProfile` 填写了未注册 profile。
- `invalid control payload`：上行控制 topic 正确但 payload 非合法 JSON。
- 语音无识别结果：检查 `audioUpMode` 是否与固件上行格式一致（帧包/JSON base64）。
