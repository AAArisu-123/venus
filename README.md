# Venus 维纳斯

[English](README.en.md) | 简体中文

Venus 是一个**本地优先、可自定义人格**的 AI 聊天伴侣。它支持命令行文字聊天和 QQ 私聊，角色由 JSON 人设定义，聊天记录、长期记忆、用户画像和主动消息计划都保存在本机 SQLite 中。模型通过任意 OpenAI 兼容的 `/chat/completions` 接口接入。

> **项目状态**：v0.1.0，个人项目。QQ 私聊已在本机跑通，但尚未做大规模或长期稳定性验证。这不是托管服务，请不要直接暴露到公网或多租户环境。

## 功能

- **可自定义人设**：名字、自我描述、表达风格、边界、关系节奏、示例对话和本轮提醒。
- **长期记忆**：显式 `/记住`、自动偏好提取、分类 / 重要性 / 使用次数，以及关键词 + 重要性 + 新近度召回。
- **用户画像**：按人设与用户隔离的称呼、交流风格和话题边界。
- **自然的主动消息**：只在北京时间 19:00–21:00 随机出现，每天最多 1 条；需要至少 6 小时静默，超过 7 天无互动会自动安静。
- **情绪表达**：可选的 AnimaFlux 心情状态，缺少依赖时自动跳过。
- **隐私拦截**：发送模型前拦截密钥、密码、验证码、证件号、银行卡号、手机号和邮箱；命中时不发送、不保存、不回显。
- **QQ 私聊**：默认拒绝未知用户，支持白名单或本地配对审批；可注册 Windows 计划任务后台运行。
- **自检工具**：一条命令检查配置、人设、数据库、日志、模型接口和 QQ 发送。
- **仅标准库核心**：普通聊天不需要第三方 Python 依赖；QQ 和心情状态是可选扩展。

## 快速开始

### 环境

- Python 3.10+（核心聊天）。
- Python 3.11+（QQ 机器人与 AnimaFlux 心情状态）。
- 一个提供 OpenAI 兼容 `/chat/completions` 的模型服务，以及可用的 API 密钥和模型名。

### 安装

```powershell
git clone <你的仓库地址> venus
cd venus
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

QQ 附加依赖：

```powershell
python -m pip install -e ".[qq]"
```

可选心情状态：

```powershell
python -m pip install -r requirements-affect.txt
```

### 配置

```powershell
Copy-Item .env.example .env
notepad .env
```

至少填写：

```dotenv
VENUS_API_KEY=sk-your-key-here
VENUS_BASE_URL=https://api.example.com/v1
VENUS_MODEL=your-model-name
```

`.env`、`data/` 和日志都已被 `.gitignore` 忽略。不要提交或分享它们。

### 命令行聊天

```powershell
python -m venus
```

发送一条后退出：

```powershell
python -m venus --message "你好"
```

常用参数：

```text
--persona personas/venus.json   指定人设
--db data/venus.sqlite3         指定数据库
--user local                    本地数据分组（不是身份认证）
```

### QQ 私聊

1. 安装 QQ 依赖并配置模型。
2. 运行 `npm install` 和 `npm run qq:connect` 扫码获取 AppID / AppSecret，或在 `.env` 手动填写。
3. 配置 `QQ_ALLOWED_OPENIDS`，或使用本地配对审批。
4. 启动：

```powershell
python -m venus.qq_bot
```

完整的扫码、配对、后台常驻和排错步骤见 [docs/QQ_SETUP.md](docs/QQ_SETUP.md)。

### 自检

```powershell
python -m venus.doctor
python -m venus.doctor --api
python -m venus.doctor --send-test
```

`--api` 检查模型接口，`--send-test` 直接发一条 QQ 测试私聊（不建立网关连接）。任一检查失败时退出码为 1，不会打印密钥或响应正文。

## 常用命令

在已批准的 QQ 私聊中：

| 命令 | 作用 |
| --- | --- |
| `/记住 我喜欢红茶` | 保存一条长期记忆 |
| `/记忆` | 查看最近 20 条记忆 |
| `/忘记 1` | 删除第 1 号记忆 |
| `/修改记忆 1 我喜欢绿茶` | 修改指定记忆 |
| `/自动记忆 开启` / `/自动记忆 关闭` | 自动偏好提取开关，默认开启 |
| `/称呼 狸花猫` | 设置角色对你的称呼 |
| `/风格 短句，少用表情` | 设置交流偏好 |
| `/边界 不聊工作压力` | 设置需要避开的话题 |
| `/画像` / `/画像 清除` | 查看或清除画像 |
| `/心情` / `/心情 关闭` / `/心情 重置` | 查看、关闭或重置心情状态 |
| `/联网 开启` / `/联网 关闭` | 联网搜索开关，默认关闭 |
| `/主动 开启` / `/主动 关闭` | 主动消息开关，默认开启 |
| `/关于` / `/帮助` | 查看数据说明或命令列表 |

## 配置项

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `VENUS_API_KEY` | 是 | 模型服务密钥 |
| `VENUS_BASE_URL` | 是 | OpenAI 兼容 API 根地址，必须为 HTTPS（本机回环可用 HTTP） |
| `VENUS_MODEL` | 是 | 模型名称 |
| `QQ_APP_ID` | QQ | 机器人 AppID；可省略并使用扫码凭据 |
| `QQ_APP_SECRET` | QQ | 机器人 AppSecret；可省略并使用扫码凭据 |
| `QQ_ALLOWED_OPENIDS` | 否 | 逗号分隔的 openid 白名单；留空则使用配对审批 |
| `QQ_PAIRING_DB` | 否 | 配对数据库路径，默认 `data/pairing.sqlite3` |
| `QQ_CREDENTIALS_FILE` | 否 | 扫码凭据路径，默认 `data/qq-credentials.json` |

## 项目结构

```text
venus/              核心 Python 包
  __main__.py       命令行入口与模型请求
  prompt.py         分层提示词组装
  persona.py        人设读取与校验
  memory.py         对话历史
  long_memory.py    长期记忆
  memory_recall.py  记忆召回
  profile.py        用户画像
  privacy.py        隐私拦截
  proactive*.py     主动消息
  qq_*.py           QQ 接入
  doctor.py         自检
personas/           人设 JSON
scripts/            QQ 扫码与 Windows 任务脚本
tests/              487 项单元与集成测试
docs/               架构、隐私、QQ 接入、人设说明
```

更完整的模块说明见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 数据与隐私

- 聊天记录、长期记忆、画像和主动计划保存在 `data/venus.sqlite3`，**明文存储**。
- 人设、当前消息、选中的历史、记忆和画像会发送给你配置的模型服务商。
- 开启联网后，相关内容还会发送给 DeepSeek 及其搜索服务。
- 项目本身没有遥测、统计或云端同步。
- 发送前会做敏感信息拦截，但规则过滤不保证完整；不要发送密码、密钥或他人的私人信息。

完整说明、数据位置和加固建议见 [docs/PRIVACY.md](docs/PRIVACY.md)。

## 测试

```powershell
python -m unittest discover -s tests -v
```

测试使用本地临时 HTTP 替身和临时 SQLite，不访问真实模型服务，也不需要真实密钥。

## 已知限制

- 没有账户认证、加密存储、内容审核或公网隔离；不要公开运营。
- 聊天导出、细粒度删除和云端常驻尚未实现。
- QQ 主动消息受平台策略限制，失败不会重试或提醒。
- 主动消息依赖本机在线；睡眠、关机或断网时不会发送。
- 模型输出可能理解有误或编造细节，不代表真实经历或主观意识。
- 记忆召回是文字匹配，不是语义理解，可能漏召回或误召回。
- AnimaFlux 是可选依赖，采用 PolyForm Noncommercial 1.0.0，不授予商业使用权。

## 贡献

欢迎 issue 和 pull request。开始前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全相关问题请按 [SECURITY.md](SECURITY.md) 私下报告，不要在公开 issue 中贴密钥或聊天记录。

## 许可证

本项目采用 [MIT License](LICENSE)。

`requirements-affect.txt` 中的 AnimaFlux 是独立的可选依赖，遵循其自身的 PolyForm Noncommercial 1.0.0 许可，不随本项目授权。
