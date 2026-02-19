# 架构设计

## 1. 分层视图

1. 接入层：`nanobot/hardware/adapter/*`
2. 运行时层：`nanobot/hardware/runtime/*`
3. Agent 层：`nanobot/agent/*`
4. 服务层：`nanobot/api/*`
5. 数据层：`nanobot/storage/*`
6. 策略层：`nanobot/safety/*`

## 2. 核心模块职责

### 2.1 硬件接入与事件统一

- 适配器将上行协议转换为统一语义事件（Canonical Envelope）
- 运行时负责连接状态、会话上下文、语音管线和下行命令分发

### 2.2 Agent 执行

- `AgentLoop` 负责提示组装、工具调用、回复生成
- 支持 MCP 工具、Web 工具和受限执行工具

### 2.3 Lifelog 与视觉

- 图像入队异步处理（去重、结构化、索引）
- SQLite + 向量索引实现时间线检索和语义检索

### 2.4 Digital Task

- 任务状态机：`pending -> running -> success/failed/timeout/canceled`
- 支持重启恢复、状态推送、设备侧中断旧任务

### 2.5 控制 API

- 提供运行时状态、设备管理、lifelog 查询、任务管理
- 支持鉴权、限流、可选防重放

## 3. 进程入口

主入口命令：

```bash
nanobot hardware serve
```

该入口会组装：

- adapter
- runtime
- control API server
- lifelog / digital task / vision service
