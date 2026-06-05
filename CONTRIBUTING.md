# Contributing

Thanks for your interest in improving YouTube Downloader. This project is a
small self-hosted tool, so contributions should stay focused, practical, and
easy to operate in a Docker Compose setup.

## Project Scope

The project is intended for personal or trusted-LAN deployments. Changes should
preserve that default operating model unless the discussion explicitly expands
the scope.

Good contributions include:

- Clear documentation improvements.
- Small UI or API quality-of-life fixes.
- Reliability improvements for downloads, conversions, cleanup, and state
  handling.
- Tests that cover user-facing behavior or important edge cases.
- Deployment improvements that keep the default setup simple.

Before starting larger changes, open an issue to discuss the approach.

## Development Setup

Required tools:

- Docker
- Docker Compose plugin
- Python 3.14
- uv
- Node.js 24
- npm

Clone the repository:

```bash
git clone https://github.com/zients/yt-downloader.git
cd yt-downloader
```

Start the full stack:

```bash
docker compose up --build
```

Open the app:

```text
http://localhost:17291
```

Stop the stack:

```bash
docker compose down
```

## Verification

Run the API test suite:

```bash
(cd api && uv sync && uv run pytest ../tests/api -q)
```

Run frontend checks:

```bash
(cd frontend && npm ci)
(cd frontend && npm run test:format-presets)
(cd frontend && npm run test:recent-jobs)
(cd frontend && npm run lint)
(cd frontend && npm run build)
```

Run Docker checks:

```bash
docker compose config -q
docker compose build
```

Please include the relevant verification results in your pull request.

## Pull Requests

Keep pull requests small and focused. A PR should usually do one thing:

- Fix one bug.
- Add one feature.
- Improve one area of documentation.
- Update one dependency group.

PR checklist:

- Describe the user-facing change.
- Link the related issue when one exists.
- Include test or verification output.
- Update documentation when behavior, setup, or configuration changes.
- Avoid unrelated formatting or refactoring.

## Commit Style

Use concise, descriptive commit messages. Conventional-style prefixes are
welcome but not required:

```text
docs: add security policy
fix: handle expired conversion state
test: cover recent job hydration
```

## Security Issues

Do not report vulnerabilities in public issues. Follow the process in
`SECURITY.md`.
