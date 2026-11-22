# Venus

English | [简体中文](README.md)

Venus is a **local-first, persona-driven AI chat companion**. It supports command-line chat and QQ private messages, defines each character with a JSON persona, and keeps conversation history, long-term memories, user profiles and proactive-message schedules in a local SQLite database. Any OpenAI-compatible `/chat/completions` endpoint can be used as the model backend.

> **Status**: v0.1.0, a personal project. QQ private chat works in a local setup, but has not been validated at scale or over long periods. This is not a hosted service; do not expose it directly to the public internet or use it as a multi-tenant service.

## Features

- **Custom personas**: name, self-description, style, boundaries, relationship pace, example dialogue and per-turn reminders.
- **Long-term memory**: explicit `/remember`, automatic preference extraction, categories, importance, usage counts, and recall by keyword relevance + importance + recency.
- **User profile**: per-persona, per-user preferred name, communication style and topic boundaries.
- **Gentle proactive messages**: one randomized window per evening (19:00–21:00 Beijing time), at most one message per day, at least six quiet hours required, and automatic silence after seven days without interaction.
- **Emotional expression**: optional AnimaFlux mood state, skipped gracefully when the dependency is absent.
- **Privacy filter**: blocks keys, passwords, verification codes, ID numbers, bank cards, phone numbers and email addresses before a model call; blocked content is not sent, stored or echoed.
- **QQ private chat**: denies unknown users by default, supports an openid allowlist or local pairing approval, and can run as a Windows scheduled task.
- **Self-check CLI**: validates configuration, persona, database, logs, model endpoint and QQ delivery in one command.
- **Standard-library core**: ordinary chat needs no third-party Python package; QQ and mood state are optional extras.

## Quick start

### Requirements

- Python 3.10+ (core chat).
- Python 3.11+ (QQ bot and AnimaFlux mood state).
- An OpenAI-compatible `/chat/completions` service with an API key and model name.

### Install

```powershell
git clone <your-repository-url> venus
cd venus
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

QQ extra:

```powershell
python -m pip install -e ".[qq]"
```

Optional mood state:

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

`.env`, `data/` and logs are ignored by `.gitignore`. Never commit or share them.

### Command-line chat

```powershell
python -m venus
```

Send one message and exit:

```powershell
python -m venus --message "Hello"
```

Common options:

```text
--persona personas/venus.json   persona file
--db data/venus.sqlite3         database path
--user local                    local data group (not authentication)
```

### QQ private chat

1. Install the QQ extra and configure the model.
2. Run `npm install` and `npm run qq:connect` to obtain AppID / AppSecret by QR code, or enter them in `.env`.
3. Set `QQ_ALLOWED_OPENIDS`, or use local pairing approval.
4. Start:

```powershell
python -m venus.qq_bot
```

See [docs/QQ_SETUP.md](docs/QQ_SETUP.md) for QR onboarding, pairing, background tasks and troubleshooting.

### Self-check

```powershell
python -m venus.doctor
python -m venus.doctor --api
python -m venus.doctor --send-test
```

`--api` checks the model endpoint; `--send-test` sends one QQ test message without opening a gateway connection. Any failure exits with code 1 and never prints secrets or response bodies.

## Commands

Inside an approved QQ private chat:

| Command | Purpose |
| --- | --- |
| `/记住 我喜欢红茶` | Save a long-term memory |
| `/记忆` | Show the 20 most recent memories |
| `/忘记 1` | Delete memory number 1 |
| `/修改记忆 1 我喜欢绿茶` | Edit a memory in place |
| `/自动记忆 开启` / `/自动记忆 关闭` | Toggle automatic preference extraction (on by default) |
| `/称呼 狸花猫` | Set how the character addresses you |
| `/风格 短句，少用表情` | Set communication preferences |
| `/边界 不聊工作压力` | Set topics to avoid |
| `/画像` / `/画像 清除` | Show or clear the profile |
| `/心情` / `/心情 关闭` / `/心情 重置` | Inspect, disable or reset mood state |
| `/联网 开启` / `/联网 关闭` | Toggle web search (off by default) |
| `/主动 开启` / `/主动 关闭` | Toggle proactive messages (on by default) |
| `/关于` / `/帮助` | Data notes or command list |

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `VENUS_API_KEY` | Yes | Model service API key |
| `VENUS_BASE_URL` | Yes | OpenAI-compatible API root; HTTPS required (HTTP only for loopback) |
| `VENUS_MODEL` | Yes | Model name |
| `QQ_APP_ID` | QQ | Bot AppID; may be omitted when QR credentials exist |
| `QQ_APP_SECRET` | QQ | Bot AppSecret; may be omitted when QR credentials exist |
| `QQ_ALLOWED_OPENIDS` | No | Comma-separated openid allowlist; empty means pairing approval |
| `QQ_PAIRING_DB` | No | Pairing database path, default `data/pairing.sqlite3` |
| `QQ_CREDENTIALS_FILE` | No | QR credential path, default `data/qq-credentials.json` |

## Project layout

```text
venus/              core Python package
  __main__.py       CLI entry point and model requests
  prompt.py         layered prompt assembly
  persona.py        persona loading and validation
  memory.py         conversation history
  long_memory.py    long-term memories
  memory_recall.py  memory recall
  profile.py        user profile
  privacy.py        privacy guard
  proactive*.py     proactive messages
  qq_*.py           QQ integration
  doctor.py         self-check
personas/           persona JSON files
scripts/            QQ onboarding and Windows task scripts
tests/              487 unit and integration tests
docs/               architecture, privacy, QQ setup, persona guide
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the module map.

## Data and privacy

- Chat history, long-term memories, profiles and proactive schedules live in `data/venus.sqlite3` and are stored **in plaintext**.
- Persona text, the current message, selected history, memories and profile are sent to your configured model provider.
- With web search enabled, related content is also sent to DeepSeek and its search provider.
- The project itself has no telemetry, analytics or cloud sync.
- Sensitive-data filtering is rule-based and cannot be complete; never send passwords, keys or other people's private information.

See [docs/PRIVACY.md](docs/PRIVACY.md) for data locations and hardening advice.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests use local fake HTTP servers and temporary SQLite databases. They never call a real model service and never need real credentials.

## Known limitations

- No account authentication, encrypted storage, content moderation or public-internet isolation. Do not run it as a public service.
- Chat export, fine-grained deletion and cloud hosting are not implemented.
- QQ proactive delivery depends on platform policy; failures are not retried or surfaced to the user.
- Proactive messages require the machine to be online; sleep, shutdown or network loss stops them.
- Model output can be wrong or fabricated and does not represent real experience or consciousness.
- Memory recall is lexical matching, not semantic understanding; it can miss or mis-rank memories.
- AnimaFlux is an optional dependency under PolyForm Noncommercial 1.0.0 and does not grant commercial rights.

## Contributing

Issues and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first. For security issues, follow [SECURITY.md](SECURITY.md) and report privately; never post keys or chat logs in a public issue.

## License

This project is released under the [MIT License](LICENSE).

AnimaFlux in `requirements-affect.txt` is a separate optional dependency under its own PolyForm Noncommercial 1.0.0 license and is not covered by this project's MIT grant.
