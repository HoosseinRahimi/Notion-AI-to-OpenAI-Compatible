# Contributing

Thanks for helping improve the Notion AI → OpenAI-compatible proxy.

## Development setup

Requires Python 3.11+ and `uv` (or a standard venv with pip).

```bash
git clone https://github.com/HoosseinRahimi/Notion-AI-to-OpenAI-Compatible.git
cd Notion-AI-to-OpenAI-Compatible
uv venv && uv pip install -e ".[test]"
```

Copy `.env.example` to `.env` and fill in your own Notion cookie and API key. Never commit real credentials.

## Checks before opening a pull request

Run all four gates locally:

```bash
uv run ruff check .
uv run pyright
uv run pytest
uv run pytest --cov=notionchat --cov-report=term-missing
```

CI runs the same commands on Python 3.11–3.13, plus CodeQL and dependency review.

## What we accept

- Bug fixes with a regression test.
- Endpoint contract changes must keep `/v1/chat/completions` and `/v1/responses` OpenAI-compatible.
- Security changes (auth, cookie handling, bind checks) need a clear threat model in the PR description.
- Cosmetic changes are welcome but keep the README's cross-platform quickstart working.

## Pull request expectations

1. One logical change per PR.
2. Use conventional commit-style PR titles (`fix:`, `feat:`, `docs:`, `ci:`).
3. Describe what you tested and on which OS/Python version.
4. Do not include real Notion cookies, API keys, or workspace data in tests, logs, or screenshots.

## Reporting security issues

Please open a private security advisory rather than a public issue.

## Upstream

This is a maintained continuation of `mughu-id/Notion-AI-to-OpenAI-Compatible` (MIT). Preserve upstream attribution in derived work.
