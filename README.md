# 维纳斯 / Venus

[English](README.en.md) | 简体中文

维纳斯是我自己用的一个聊天机器人。平时在 QQ 私聊里跟她说话，也可以在终端里直接聊。

一开始只是想让模型记住我说过的事，别每次都像第一次见面。后来越加越多：人设、长期记忆、用户画像、主动消息、心情状态，慢慢变成了现在这个样子。她更像一个“记得住你、也有自己说话方式”的聊天对象，而不是什么都能干的助手。

项目还是 0.1 版，很多地方比较粗糙。QQ 私聊在我自己电脑上跑通了，但没有经过大规模或长期验证。它不是托管服务，别直接放到公网上。

## 现在能做什么

- 人设是一个 JSON 文件，可以改名字、性格、说话方式、边界和示例对话。
- 聊久了会记住一些东西：明确的偏好可以自动提取，也可以 `/记住` 手动存。召回只是关键词匹配，不是真的理解。
- 每个人可以单独设置称呼、说话风格和不想聊的话题。
- 晚上可能主动来找你，但一天最多一条，而且要先安静六个小时；七天没说话她也会停下来。
- QQ 端默认不认陌生人，可以配白名单，也可以在本机批准配对码。
- 发出去之前会拦一下密钥、密码、证件号、银行卡、手机号、邮箱。规则拦不干净，别拿它当保险箱。

## 它不是

- 不是网页版 ChatGPT，也不是写代码、查资料的全能助手。
- 不是托管服务：没有账号、没有加密、没有内容审核，也不适合多人共用。
- 不是真的有感情。她会说想你，但那是提示词和模型生成的结果，不是意识。

## 跑起来

需要 Python 3.10 以上；QQ 和心情状态要 3.11 以上，扫码绑定还需要 Node.js 18 以上。模型服务只要是 OpenAI 兼容的 `/chat/completions` 就行，地址、模型名和密钥都用你自己的。

### 安装

```powershell
git clone https://github.com/Arisu-Arisu/venus.git venus
cd venus
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

要接 QQ 的话再装一个附加依赖：

```powershell
python -m pip install -e ".[qq]"
```

想要模拟心情，再装 AnimaFlux：

```powershell
python -m pip install -r requirements-affect.txt
```

### 配置

```powershell
Copy-Item .env.example .env
notepad .env
```

至少填这三个：

```dotenv
VENUS_API_KEY=sk-your-key-here
VENUS_BASE_URL=https://api.example.com/v1
VENUS_MODEL=your-model-name
```

`.env` 和 `data/` 都已经被 Git 忽略。别把它们发出去，也别提交。

### 命令行

```powershell
python -m venus
```

只想说一句就退出：

```powershell
python -m venus --message "你好"
```

几个参数：

```text
--persona personas/venus.json   换一个人设
--db data/venus.sqlite3         换一个数据库
--user local                    本地数据分组，不是登录账号
```

### QQ

1. 装好 QQ 依赖，配好模型。
2. `npm install`，然后 `npm run qq:connect` 扫码拿 AppID / AppSecret；也可以直接在 `.env` 里填。
3. 配 `QQ_ALLOWED_OPENIDS`，或者用本地配对码审批。
4. 启动：

```powershell
python -m venus.qq_bot
```

扫码、配对、后台常驻和常见问题都写在 [docs/QQ_SETUP.md](docs/QQ_SETUP.md) 里了。

### 自检

```powershell
python -m venus.doctor
python -m venus.doctor --api
python -m venus.doctor --send-test
```

`--api` 会真的发一句很短的模型请求，`--send-test` 会直接发一条 QQ 私聊（不连网关）。检查失败时退出码是 1，不会把密钥或响应正文打出来。自检也会看 QQ 凭据；如果你只用命令行、还没接 QQ，这项可以先跳过。

## 常用命令

QQ 私聊里可以直接发这些：

| 命令 | 作用 |
| --- | --- |
| `/记住 我喜欢红茶` | 存一条长期记忆 |
| `/记忆` | 看最近 20 条记忆 |
| `/忘记 1` | 删掉第 1 号记忆 |
| `/修改记忆 1 我喜欢绿茶` | 改一条记忆 |
| `/自动记忆 开启` / `/自动记忆 关闭` | 自动记偏好，默认开着 |
| `/称呼 狸花猫` | 让她怎么叫你 |
| `/风格 短句，少用表情` | 说话偏好 |
| `/边界 不聊工作压力` | 不想聊的话题 |
| `/画像` / `/画像 清除` | 看或清空这些设置 |
| `/心情` / `/心情 关闭` / `/心情 重置` | 看、关掉或重置心情 |
| `/联网 开启` / `/联网 关闭` | 联网搜索，默认关着 |
| `/主动 开启` / `/主动 关闭` | 主动消息，默认开着 |
| `/关于` / `/帮助` | 数据说明或命令列表 |

## 配置项

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `VENUS_API_KEY` | 是 | 模型服务密钥 |
| `VENUS_BASE_URL` | 是 | OpenAI 兼容 API 根地址，必须 HTTPS；本机回环可以用 HTTP |
| `VENUS_MODEL` | 是 | 模型名 |
| `QQ_APP_ID` | 接 QQ 时 | 机器人 AppID，扫码绑过就可以不填 |
| `QQ_APP_SECRET` | 接 QQ 时 | 机器人 AppSecret，扫码绑过就可以不填 |
| `QQ_ALLOWED_OPENIDS` | 否 | 逗号分隔的白名单，留空就用配对审批 |
| `QQ_PAIRING_DB` | 否 | 配对数据库，默认 `data/pairing.sqlite3` |
| `QQ_CREDENTIALS_FILE` | 否 | 扫码凭据，默认 `data/qq-credentials.json` |

## 目录大概是这样

| 路径 | 放什么 | 提交吗 |
| --- | --- | --- |
| `venus/` | 主要代码：聊天、记忆、画像、隐私、主动消息、QQ | 是 |
| `personas/` | 人设 JSON；`venus.json` 是默认示例，复制一份改成自己的 | 是 |
| `tests/` | 487 项测试 | 是 |
| `docs/` | 架构、隐私、QQ 接入、人设格式 | 是 |
| `scripts/` | QQ 扫码、Windows 计划任务、头像生成 | 是 |
| `.github/` | CI、issue / PR 模板、Dependabot | 是 |
| `pyproject.toml` / `package.json` | Python 打包和 QQ 扫码依赖 | 是 |
| `.env` | 本地密钥和配置，从 `.env.example` 复制 | 否 |
| `data/` | SQLite 数据库、扫码凭据、本地人设备份 | 否 |
| `logs/` | 运行日志 | 否 |
| `.venv/` / `node_modules/` | 本地依赖，删了可以重装 | 否 |

私人人设可以放在 `data/personas/`，那里不会进仓库。`.venv/`、`node_modules/`、`__pycache__/` 随便删；`data/`、`logs/`、`.env` 删了会丢数据或配置。

更细的模块说明在 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 数据都放在哪

聊天记录、长期记忆、画像和主动计划都在 `data/venus.sqlite3` 里，**明文**。人设、当前消息、选中的历史、记忆和画像会发给你配置的模型服务；开了联网还会经过 DeepSeek 和它的搜索服务。项目本身没有遥测，也没有云端同步。

发送前会做敏感信息拦截，但规则不保证拦全。别发密码、密钥，也别发别人的私人信息。完整的说明和加固建议在 [docs/PRIVACY.md](docs/PRIVACY.md)。

## 测试

```powershell
python -m unittest discover -s tests -v
```

测试用的是本地临时 HTTP 替身和临时 SQLite，不会访问真实模型，也不需要真密钥。

## 一些毛病

- 没有登录、加密、内容审核，也没有公网隔离。别拿它做公开服务。
- 聊天导出、按条删除、云端常驻都还没做。
- QQ 主动消息要看平台脸色，发失败就失败了，不会重试也不会提醒你。
- 电脑睡眠、关机、断网的时候，主动消息不会发。
- 模型会理解错，也会编。她说的“今天去干了什么”不是真实经历。
- 记忆召回是文字匹配，会漏，也会认错。
- 心情状态依赖 AnimaFlux，那个是 PolyForm Noncommercial 许可，不能商用。

## 贡献

有问题可以直接开 issue，想改就提 PR，先看一下 [CONTRIBUTING.md](CONTRIBUTING.md)。安全相关的问题按 [SECURITY.md](SECURITY.md) 私下说，别在公开 issue 里贴密钥或聊天记录。

## 许可证

代码用 [MIT License](LICENSE)。

`requirements-affect.txt` 里的 AnimaFlux 是单独的可选依赖，遵循它自己的 PolyForm Noncommercial 1.0.0，不跟着这个项目一起授权。
