# 单容器容量分析（语音 500 回合 + 图像 100 次 / 设备 / 天）

更新时间：2026-02-21

## 1. 结论

在当前项目实现下（单进程事件循环 + SQLite 持久化 + 外部模型 API），单容器可支撑多设备并发接入。  
按每台设备每天语音 500 回合、图像 100 次估算：

- 生产推荐规格 `4 vCPU / 8GB RAM / 100GB NVMe`：建议 `20-40` 台设备
- 上限冲刺规格 `8 vCPU / 16GB RAM / 200GB NVMe`：约 `50-80` 台设备
- 超过 `80` 台不建议继续单容器 + 单 SQLite 架构

## 2. 推荐硬件配置

| 档位 | 推荐配置 | 适用规模 |
|---|---|---|
| 最低可用 | 2 vCPU / 4GB RAM / 50GB NVMe | 1-5 台 |
| 生产推荐 | 4 vCPU / 8GB RAM / 100GB NVMe | 20-40 台 |
| 上限冲刺 | 8 vCPU / 16GB RAM / 200GB NVMe | 50-80 台 |

## 3. 推导依据（代码）

1. 系统具备多设备会话能力  
   会话由 `(device_id, session_id)` 作为 key 管理：`opencane/hardware/runtime/session_manager.py:56`。

2. 图像链路有异步削峰能力  
   默认有 ingest queue 与 workers：`opencane/config/schema.py:381`、`opencane/config/schema.py:382`；实际入队与 worker 处理在 `opencane/api/lifelog_service.py:498`、`opencane/api/lifelog_service.py:504`、`opencane/api/lifelog_service.py:573`。

3. 主要瓶颈在 SQLite 写入并发  
   当前存储为单连接 + 高频 commit：`opencane/storage/sqlite_lifelog.py:25`、`opencane/storage/sqlite_lifelog.py:321`、`opencane/storage/sqlite_lifelog.py:348`、`opencane/storage/sqlite_lifelog.py:389`、`opencane/storage/sqlite_lifelog.py:583`。

4. 每个上行事件都会触发会话序号落盘  
   在事件处理时进行 `check_and_commit_seq`：`opencane/hardware/runtime/connection.py:169`，最终会触发会话 upsert（含 commit），增加写放大。

5. 模型调用以外部 API 为主  
   语音 STT、图像理解、LLM 主要通过外部 API 调用，容器侧偏编排与持久化：`opencane/cli/commands.py:1506`、`opencane/cli/commands.py:1512`、`opencane/api/vision_server.py:78`、`opencane/providers/litellm_provider.py:156`。

## 4. 估算口径

按每设备每天语音 500 回合、图像 100 次：

- 语音回合约产生 `STT + LLM` 两次核心模型请求
- 图像回合约产生 `图像入库分析 + 视觉问答` 两次核心模型请求

粗略模型请求量约：`(500 x 2) + (100 x 2) = 1200 次/设备/天`。  
因此在 40 台规模下约 `4.8 万次/天`，除了本地 SQLite 写入并发，外部模型服务限流与延迟也会成为关键约束。

## 5. 容量结论成立前提

- 使用 `tts_mode=device_text`（不启用服务端音频合成）
- `hardware.telemetry.persistSamplesEnabled=false`
- STT/VLM/LLM 走云端 API
- MQTT Broker 不与应用争抢过小规格资源
- 数据目录挂载到本机 NVMe（非低速网络盘）

## 6. 扩容触发点

出现以下任一信号时，应从单容器升级架构：

- 持续出现 SQLite lock/busy、写入排队明显
- 运行观测中的 ingest queue 利用率长期高位
- 外部模型 API 的限流/超时频繁
- 设备规模接近或超过 80 台

建议升级方向：优先做 SQLite 参数与写路径优化，再迁移 PostgreSQL，并将异步任务与主运行时拆分。
