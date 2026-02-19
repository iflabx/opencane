# 硬件联调暂存清单（Deferred）

## 1. 目的

记录当前暂不执行的三项硬件联调前置事项，避免遗漏并支持后续恢复执行。

## 2. 暂存项（2026-02-17）

1. MQTT/Broker 联调信息
- 所需：`host/port/topic/token` 与可用环境说明
- 状态：`Deferred`

2. EC600 协议样例
- 所需：上/下行协议文档或抓包样例（control/audio）
- 状态：`Deferred`

3. 最小设备联调路径
- 所需：可触发 `hello/listen/audio/listen_stop` 的真机或脚本方式
- 状态：`Deferred`

## 3. 恢复条件

当以上三项任意补齐后，即可恢复推进：
1. HW-07 协议冻结
2. HW-08 音频包头实机核验
3. HW-09 蜂窝参数实网定版
