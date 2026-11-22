# QQ 私聊接入

QQ 部分是可选的，使用腾讯官方 `qq-botpy`。接入后，机器人在私聊中回复，并支持斜杠命令和主动消息。

## 前置条件

- Python 3.11+（QQ 依赖与可选心情状态都要求 3.11+）。
- Node.js 18+（仅扫码绑定需要）。
- 一个可用的模型服务：`VENUS_API_KEY`、`VENUS_BASE_URL`、`VENUS_MODEL`。
- 一个 QQ 机器人应用，或通过扫码绑定自动创建。

## 1. 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[qq]"
```

如需心情状态：

```powershell
python -m pip install -r requirements-affect.txt
```

## 2. 配置模型

复制示例配置并填写：

```powershell
Copy-Item .env.example .env
notepad .env
```

至少填写：

```dotenv
VENUS_API_KEY=sk-...
VENUS_BASE_URL=https://你的供应商/v1
VENUS_MODEL=你的模型名
```

`.env` 已被 `.gitignore` 忽略，不要提交或分享。

## 3. 获取 QQ 凭据

### 方式 A：扫码绑定（推荐）

```powershell
npm install
npm run qq:connect
```

按提示用手机 QQ 打开链接或扫码确认。成功后凭据写入 `data/qq-credentials.json`（已忽略，不会打印 secret）。

### 方式 B：手动填写

在 `.env` 中填写：

```dotenv
QQ_APP_ID=你的AppID
QQ_APP_SECRET=你的AppSecret
```

环境变量优先于 `data/qq-credentials.json`。

## 4. 允许谁使用

默认拒绝所有未知用户，二选一：

### 静态白名单

```dotenv
QQ_ALLOWED_OPENIDS=openid1,openid2
```

### 本地配对审批（不暴露 openid）

1. 用户先给机器人发消息，会收到一个 6 位配对码。
2. 机主在本机运行：

```powershell
python -m venus.pair_cli --list
python -m venus.pair_cli --approve CODE
```

3. 撤销某个用户：

```powershell
python -m venus.pair_cli --revoke OPENID
```

配对码默认 10 分钟有效。命令行里的 openid 会被遮住中间部分。

## 5. 启动与自检

先跑自检：

```powershell
python -m venus.doctor
python -m venus.doctor --api
python -m venus.doctor --send-test
```

- `--api`：发一句很短的模型请求。
- `--send-test`：直接调用 QQ HTTPS 接口发一条测试私聊；不建立网关连接。
- 只有一个服务用户时自动使用；多个时用 `--openid` 指定。

手动启动：

```powershell
python -m venus.qq_bot
```

同一时间只运行一个实例。后台任务运行时不要同时手动启动。

## 6. Windows 后台常驻

注册计划任务：

```powershell
powershell.exe -NoProfile -File .\scripts\install_qq_task.ps1
```

脚本要求：

- `.venv\Scripts\pythonw.exe` 存在；
- 项目根目录存在 `.env`；
- 没有同名 `Venus QQ` 任务；
- 当前没有手动运行的 `venus.qq_bot` / `venus.qq_service` 进程。

任务特性：

- 登录 Windows 后自动启动，使用当前用户普通权限；
- 失败后 1 分钟重试，另有每 5 分钟一次的补启动触发器；
- 任务已运行时不会重复启动；
- 锁屏可继续运行；注销、睡眠、关机或断网时不能保持在线；
- 不修改电源设置，不保存 Windows 密码。

停止或卸载：在任务计划程序中先**禁用**再**结束** `Venus QQ`，否则补启动触发器可能把它拉起。需要恢复时重新**启用**并**运行**。

## 7. 日志

状态日志默认位于：

```text
%LOCALAPPDATA%\Venus\logs\qq-service.log
```

如果该目录不可写，会回退到系统临时目录下的 `Venus\logs`，再回退到项目 `logs\`。日志只记录启动、连接状态和错误类别，不记录聊天正文或密钥。

## 常见问题

**机器人不回复私聊？**

- 确认用户已加入 `QQ_ALLOWED_OPENIDS` 或已通过配对审批；
- 确认只有一个机器人实例在运行；
- 查看 `qq-service.log` 是否有 READY / RESUMED / 错误类别。

**收不到主动消息？**

- `/主动` 是否被关闭；
- 当天是否已经发过；
- 最近 6 小时内是否聊过；
- 是否超过 7 天完全沉默；
- QQ 平台是否允许该机器人主动发消息。

**扫码绑定失败？**

- 确认 Node.js 版本和网络；
- 二维码过期会自动刷新；
- 失败不会打印 secret，也不会写入不完整凭据。
