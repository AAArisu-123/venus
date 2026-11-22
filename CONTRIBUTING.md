# Contributing

Venus is a small personal project. If you send a change, keep it focused and
explain what it changes for the user.

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[qq]"
python -m pip install -r requirements-affect.txt   # optional
```

Copy `.env.example` to `.env` only if you need to run the bot manually. Tests do
not need real credentials.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Every behavior change should come with a test. Tests must use local fakes and
temporary databases; they must never call a real model service, QQ API or the
production `data/` directory.

For a single module:

```powershell
python -m unittest tests.test_proactive_runner -v
```

## Code style

- Core chat is standard-library only. Discuss before adding a runtime
  dependency; QQ and AnimaFlux are optional extras on purpose.
- Match the surrounding style: small functions, explicit parameters, no hidden
  clock or environment reads inside decision helpers.
- User-facing text is Chinese; code identifiers and docstrings are English in
  most modules. Keep new code consistent with its file.
- Do not reformat unrelated code in the same pull request.

## Privacy rules

- Never commit `.env`, `data/`, logs, `data/qq-credentials.json`, openids or
  real chat content.
- Use obvious fake values in tests, for example `sk-fake-test-key`.
- Do not add logs that contain message text, prompts, keys or raw openids.
- If a change affects what leaves the machine, update
  [docs/PRIVACY.md](docs/PRIVACY.md) and both README files.

## Pull requests

1. Fork the repository and create a topic branch.
2. Make the smallest change that solves the problem.
3. Add or update tests.
4. Run the full test suite.
5. Update documentation if behavior or configuration changed.
6. Open a pull request describing the problem, the approach and the tests run.

Please avoid mixing refactors, formatting changes and behavior changes in one
pull request.

## Adding a persona

Add a JSON file under `personas/` following [docs/PERSONAS.md](docs/PERSONAS.md).
Do not include private information about real people.

## Reporting bugs

Use the issue template and include:

- Venus version or commit;
- Python and OS version;
- the command you ran;
- the expected and actual behavior;
- relevant status logs with secrets, openids and chat text removed.

Security issues should follow [SECURITY.md](SECURITY.md) instead of a public
issue.
