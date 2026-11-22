# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Planned

- Message export and finer-grained deletion.
- More automated tests against a real QQ sandbox account.
- Optional embeddings-based memory recall.

## [0.1.0] - 2026-11-22

### Added

- Local command-line chat with an OpenAI-compatible model endpoint.
- JSON personas with style, boundaries, relationship pace, examples and
  post-history instructions.
- Per-user profile commands (`/称呼`, `/风格`, `/边界`, `/画像`).
- Long-term memory with categories, importance, recall scoring and automatic
  preference extraction.
- QQ C2C bot with openid allowlist, local pairing codes and a Windows
  Task Scheduler entry point.
- Gentle proactive messages: one evening window per day, six quiet hours
  required, no automatic follow-ups.
- Privacy filter for credentials and high-confidence identifiers before any
  model call.
- Optional AnimaFlux mood state, disabled gracefully when the dependency is
  absent.
- Doctor CLI (`python -m venus.doctor`) for configuration, model and QQ checks.
- 487 unit and integration tests that use local fakes and never call a real
  model service.
