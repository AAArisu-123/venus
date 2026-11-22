# Security Policy

## Supported versions

Only the latest commit on `main` is supported. This is a pre-1.0 personal
project; there are no long-term security backports.

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Use GitHub's private vulnerability reporting:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Describe the issue and the affected version or commit.

If private reporting is unavailable, contact the maintainer through their
GitHub profile and ask for a private channel before sharing details.

Never include real API keys, QQ AppSecrets, openids, chat transcripts or
database files in a report. Use redacted examples.

## In scope

- Leakage of secrets, chat content or private data through logs, error
  messages, prompts or commits.
- Access-control bypass in the QQ allowlist or pairing flow.
- Privacy-filter bypass that sends a high-confidence secret or identifier to a
  model service.
- Path traversal, unsafe file writes or SQL injection.
- Prompt-injection issues that cross a real security boundary, such as
  extracting credentials or changing access control.

## Out of scope

- Model hallucinations, offensive output or factual errors that do not cross a
  security boundary.
- Issues requiring an already-compromised machine, account or local database.
- QQ platform policy decisions, delivery failures or rate limits.
- Denial of service against your own local process.
- Missing hardening that is already documented as a limitation in
  [docs/PRIVACY.md](docs/PRIVACY.md).

## What to expect

This is a volunteer project. Reports are handled on a best-effort basis:
acknowledgement, reproduction, a fix or documented mitigation, and credit if
you want it. There is no bug bounty.

## Safe configuration reminders

- Keep `.env`, `data/` and logs out of version control.
- Rotate model and QQ credentials immediately if you suspect exposure.
- Do not expose the bot to the public internet or run it for untrusted users.
