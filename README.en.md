# Venus

English | [简体中文](README.md)

Venus is a chat bot I run for myself. Most of the time I talk to her in a QQ private chat; sometimes I just use the terminal.

It started with one small wish: I wanted the model to remember what I had already told it, instead of meeting me for the first time every session. Then personas, long-term memory, profiles, proactive messages and mood state piled up. She is meant to feel like someone who remembers you and has her own way of talking, not a general-purpose assistant.

This is still a 0.1 project and some parts are rough. QQ chat works on my machine, but it has not been tested at scale or over a long period. It is not a hosted service; please do not put it on the public internet.

## What it does

- A persona is just a JSON file. You can change the name, personality, speaking style, boundaries and example dialogue.
- She remembers some of what you tell her: explicit preferences can be extracted automatically, or saved by hand with `/remember`. Recall is keyword matching, not real understanding.
- Each user can set their own preferred name, communication style and topics to avoid.
- She may reach out in the evening, but at most once a day and only after six quiet hours. If you have not spoken for seven days, she stops.
- On QQ, strangers are ignored by default. Use an allowlist, or approve a pairing code locally.
- Messages are screened for keys, passwords, ID numbers, bank cards, phone numbers and email addresses before they are sent. The rules are not perfect; do not treat this as a vault.

## What it is not

- It is not a web version of ChatGPT, and not an all-purpose coding or research assistant.
- It is not a hosted service: no accounts, no encryption, no moderation, no multi-user isolation.
- It is not actually in love. When she says she misses you, that is the prompt and the model talking, not consciousness.

## Getting started

You need Python 3.10+; QQ and mood state need 3.11+, and QR onboarding needs Node.js 18+. The model backend just has to be OpenAI-compatible at `/chat/completions`; the URL, model name and key are yours.

### Install

```powershell
git clone https://github.com/AAArisu-123/venus.git venus
cd venus
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

For QQ, add the extra:

```powershell
python -m pip install -e ".[qq]"
```

For the optional mood state:

```powershell
python -m pip install -r requirements-affect.txt
```

### Configure

```powershell
Copy-Item .env.example .env
notepad .env
```

At minimum:

```dotenv
VENUS_API_KEY=sk-your-key-here
VENUS_BASE_URL=https://api.example.com/v1
VENUS_MODEL=your-model-name
```

`.env` and `data/` are already ignored by Git. Do not commit or share them.

### Terminal chat

```powershell
python -m venus
```

Send one message and exit:

```powershell
python -m venus --message "Hello"
```

A few options:

```text
--persona personas/venus.json   use another persona
--db data/venus.sqlite3         use another database
--user local                    local data group, not a login
```

### QQ

1. Install the QQ extra and configure the model.
2. Run `npm install`, then `npm run qq:connect` to get AppID / AppSecret by QR code. You can also put them in `.env`.
3. Set `QQ_ALLOWED_OPENIDS`, or use local pairing approval.
4. Start:

```powershell
python -m venus.qq_bot
```

QR onboarding, pairing, the background task and troubleshooting are in [docs/QQ_SETUP.md](docs/QQ_SETUP.md).

### Self-check

```powershell
python -m venus.doctor
python -m venus.doctor --api
python -m venus.doctor --send-test
```

`--api` sends one tiny model request. `--send-test` sends one QQ private message directly, without opening a gateway connection. Failures exit with code 1 and never print keys or response bodies. The doctor also checks QQ credentials; if you only use the terminal and have not set up QQ yet, you can skip that part.

## Commands

Inside an approved QQ private chat:

| Command | What it does |
| --- | --- |
| `/记住 我喜欢红茶` | Save a long-term memory |
| `/记忆` | Show the 20 most recent memories |
| `/忘记 1` | Delete memory number 1 |
| `/修改记忆 1 我喜欢绿茶` | Edit a memory in place |
| `/自动记忆 开启` / `/自动记忆 关闭` | Automatic preference extraction, on by default |
| `/称呼 狸花猫` | Set what she calls you |
| `/风格 短句，少用表情` | Set your communication preferences |
| `/边界 不聊工作压力` | Set topics to avoid |
| `/画像` / `/画像 清除` | Show or clear these settings |
| `/心情` / `/心情 关闭` / `/心情 重置` | Inspect, disable or reset mood state |
| `/联网 开启` / `/联网 关闭` | Web search, off by default |
| `/主动 开启` / `/主动 关闭` | Proactive messages, on by default |
| `/关于` / `/帮助` | Data notes or the command list |

## Configuration

| Variable | Required | Meaning |
| --- | --- | --- |
| `VENUS_API_KEY` | Yes | Model service key |
| `VENUS_BASE_URL` | Yes | OpenAI-compatible API root; HTTPS required, HTTP only for loopback |
| `VENUS_MODEL` | Yes | Model name |
| `QQ_APP_ID` | For QQ | Bot AppID; can be omitted after QR onboarding |
| `QQ_APP_SECRET` | For QQ | Bot AppSecret; can be omitted after QR onboarding |
| `QQ_ALLOWED_OPENIDS` | No | Comma-separated allowlist; empty means pairing approval |
| `QQ_PAIRING_DB` | No | Pairing database, default `data/pairing.sqlite3` |
| `QQ_CREDENTIALS_FILE` | No | QR credentials, default `data/qq-credentials.json` |

## Project layout

| Path | What is in it | Committed |
| --- | --- | --- |
| `venus/` | Main code: chat, memory, profile, privacy, proactive messages, QQ | Yes |
| `personas/` | Persona JSON; `venus.json` is the default example to copy and edit | Yes |
| `tests/` | 487 tests | Yes |
| `docs/` | Architecture, privacy, QQ setup and persona format | Yes |
| `scripts/` | QQ onboarding, Windows task setup, avatar generators | Yes |
| `.github/` | CI, issue/PR templates and Dependabot | Yes |
| `pyproject.toml` / `package.json` | Python packaging and the QQ onboarding dependency | Yes |
| `.env` | Local keys and settings, copied from `.env.example` | No |
| `data/` | SQLite databases, QR credentials, local persona backups | No |
| `logs/` | Runtime logs | No |
| `.venv/` / `node_modules/` | Local dependencies, safe to reinstall | No |

Private personas can live in `data/personas/`, which never enters the repository. `.venv/`, `node_modules/` and `__pycache__/` can be deleted at any time; deleting `data/`, `logs/` or `.env` loses local data or configuration.

The module map is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Where the data lives

Chat history, long-term memory, profiles and proactive schedules are in `data/venus.sqlite3`, in **plaintext**. The persona, current message, selected history, memories and profile are sent to your model provider; with web search enabled, related content also goes through DeepSeek and its search provider. There is no telemetry and no cloud sync.

Sensitive content is screened before sending, but the rules are not complete. Do not send passwords, keys or other people's private information. The full notes and hardening advice are in [docs/PRIVACY.md](docs/PRIVACY.md).

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests use a local fake HTTP server and temporary SQLite databases. They never call a real model service and never need real keys.

## Rough edges

- No login, encryption, moderation or public-internet isolation. Do not run it as a public service.
- Chat export, per-message deletion and cloud hosting are not implemented.
- QQ proactive delivery depends on platform policy. If it fails, it fails: no retry and no notification.
- Proactive messages stop when the machine sleeps, shuts down or loses the network.
- The model gets things wrong and makes things up. Her “what I did today” is not a real experience.
- Memory recall is lexical matching. It misses things and sometimes picks the wrong ones.
- Mood state depends on AnimaFlux, which is under PolyForm Noncommercial and cannot be used commercially.

## Contributing

Open an issue if something is broken, or send a pull request if you want to change something. Read [CONTRIBUTING.md](CONTRIBUTING.md) first. For security issues, follow [SECURITY.md](SECURITY.md) and report privately; do not paste keys or chat logs into a public issue.

## License

The code is under the [MIT License](LICENSE).

AnimaFlux in `requirements-affect.txt` is a separate optional dependency under its own PolyForm Noncommercial 1.0.0 license. This project's MIT grant does not cover it.
