# 安全基线

## 1. 鉴权

生产环境要求：

- `hardware.auth.enabled = true`
- 使用强随机 token
- 禁止在日志和工单中泄漏 token

## 2. 接口防护

建议开启：

- 请求限流
- 防重放（nonce + timestamp）
- 最大请求体限制（`hardware.controlMaxBodyBytes`）

## 3. 密钥管理

- Provider Key 不进仓库
- 使用环境变量或机密管理服务注入
- 配置文件权限最小化

## 4. 数据保护

- Lifelog 图像资产目录加访问控制
- SQLite 文件按主机安全基线加固
- 生产环境定期做数据备份与恢复演练

## 5. 最小权限

- 控制 API 仅对受信网络开放
- 运维账号与应用账号分离
- 设备操作接口按来源进行审计留痕
