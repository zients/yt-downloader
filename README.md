# YouTube Downloader

Dockerized YouTube downloader for personal or trusted-LAN use.

This project is intended for developers who want to self-host a small downloader
tool on their own machine or trusted home network.

## Features

- Single exposed gateway port for the web UI and API.
- FastAPI backend for source downloads, conversions, file downloads, and cleanup.
- React frontend with recent job cards, refresh restore, format selection, and
  explicit `Convert` / `Download file` flow.
- Redis-backed task and conversion state with a default 24-hour TTL.
- Source and conversion progress reporting.
- ffmpeg-based conversion with MP3-first default format selection.
- Automatic cleanup for expired files under `/app/downloads`.

## Architecture

Docker Compose starts four services:

| Service | Purpose | Host exposure |
| --- | --- | --- |
| `gateway` | nginx reverse proxy for frontend and API | `17291:80` |
| `frontend` | React SPA served by nginx | internal only |
| `api` | FastAPI backend, yt-dlp, ffmpeg, cleanup loop | internal only |
| `redis` | Task/conversion state store | internal only |

Network model:

```text
browser -> gateway:17291
gateway -> frontend:80
gateway -> api:8000
api -> redis:6379
```

Only `gateway` publishes a host port. `frontend`, `api`, and `redis` use Docker
internal networking. Redis is attached to an internal-only data network.

## Requirements

- Docker
- Docker Compose plugin
- Git

For local development:

- Python 3.14
- uv
- Node.js 24
- npm

## Quick Start

Clone the repository and start the stack:

```bash
git clone git@github.com:zients/yt-downloader.git
cd yt-downloader
docker compose up --build
```

Open the app:

```text
http://localhost:17291
```

To run in the background:

```bash
docker compose up --build -d
```

To stop:

```bash
docker compose down
```

## LAN Access

The compose file publishes:

```yaml
ports:
  - "17291:80"
```

Docker binds this to `0.0.0.0:17291`, so trusted LAN devices can use the host
machine's LAN IP.

On macOS, get the Wi-Fi IP:

```bash
ipconfig getifaddr en0
```

Then open from another LAN device:

```text
http://<host-ip>:17291
```

For internet-facing deployments, add gateway authentication, authorization, and
rate limiting before opening the port.

## How to Use

1. Paste a YouTube URL and click `Download`.
2. Wait for the source progress to finish.
3. Choose a conversion format from the dropdown.
4. Click `Convert`.
5. Wait for conversion progress to finish.
6. The browser downloads the completed file and keeps a `Download file` link.

The frontend keeps the latest five job cards. Existing cards remain visible when
you submit another URL. Refreshing the page restores the saved cards from
`localStorage` and resumes polling while backend state is available.

## Manual Test Checklist

After starting the stack, use this checklist for a practical smoke test:

1. Open `http://localhost:17291`.
2. Submit a YouTube URL.
3. Confirm source progress appears and eventually reaches ready state.
4. Confirm the format dropdown appears with a default selection, usually
   `MP3 audio`.
5. Change the dropdown value and confirm conversion waits for the `Convert` click.
6. Click `Convert`.
7. Confirm conversion progress appears only after `Convert`.
8. Wait for completion and confirm the browser downloads the file.
9. Submit several more URLs and confirm the UI keeps at most five cards.
10. Refresh the page and confirm recent cards are restored.
11. Stop and restart the stack, then refresh the page. The default Redis setup
    uses in-memory state, so restored cards can show a removable state message.

Useful log command:

```bash
docker compose logs -f api gateway frontend redis
```

## Data and Cleanup

The API container stores downloaded and converted files under:

```text
/app/downloads
```

Docker maps that to the repository directory:

```text
./downloads
```

Typical layout:

```text
downloads/
  <task_id>/
    <task_id>.<source_ext>
    outputs/
      <conversion_id>/
        <task_id>.<target_ext>
```

Cleanup behavior:

- `FILE_TTL_HOURS` defaults to `24`.
- `CLEANUP_INTERVAL_MINUTES` defaults to `60`.
- The API starts an async cleanup loop when it boots.
- Each cleanup pass deletes regular files under `/app/downloads` whose mtime is
  older than the TTL.
- That includes both source files and converted output files.
- Empty expired directories are removed after old files are deleted.

Redis state also uses the same default 24-hour TTL. The default Redis container
stores state in memory; a container restart starts a fresh task/conversion state
store while files remain managed under `./downloads`.

## Configuration

The default Docker Compose setup keeps runtime values directly in
`docker-compose.yml`:

```yaml
ports:
  - "17291:80"

environment:
  REDIS_URL: redis://redis:6379/0
  DOWNLOAD_DIR: /app/downloads
  FILE_TTL_HOURS: "24"
  CLEANUP_INTERVAL_MINUTES: "60"
  MAX_CONCURRENT_CONVERSIONS: "1"
```

To change the host port, edit the gateway port mapping. For example:

```yaml
ports:
  - "18080:80"
```

To change cleanup or conversion settings, edit the API environment values in
`docker-compose.yml`, then restart:

```bash
docker compose up --build
```

`DOWNLOAD_DIR` is intentionally fixed to `/app/downloads` inside the API
container because Compose mounts the host `./downloads` directory there.

## Developer Verification

API tests:

```bash
(cd api && uv sync && uv run pytest ../tests/api -q)
```

Frontend setup and checks:

```bash
(cd frontend && npm ci)
(cd frontend && npm run test:format-presets)
(cd frontend && npm run test:recent-jobs)
(cd frontend && npm run lint)
(cd frontend && npm run build)
```

Docker checks:

```bash
docker compose config -q
docker compose build
```

## Operations

### Inspect port 17291

Find the process/container using the gateway port:

```bash
lsof -nP -iTCP:17291 -sTCP:LISTEN
docker ps --format 'table {{.ID}}\t{{.Names}}\t{{.Ports}}\t{{.Status}}'
```

Stop old project containers:

```bash
docker compose down --remove-orphans
```

For containers started with a different project name, use that name:

```bash
docker compose -p <project-name> down --remove-orphans
```

### Restore state after Redis reset

The frontend stores recent cards in browser `localStorage`. Backend state lives
in Redis. After a Redis restart or TTL expiry, restored cards can show a
removable state message. Remove the card from the UI and submit a new URL.

### Conversion errors

Check API logs:

```bash
docker compose logs -f api
```

Common causes:

- Source file aged out of `./downloads`.
- ffmpeg support for the selected input/format.
- yt-dlp hit an access or download issue for the source URL.

### Clear local downloaded files

Stop the stack and remove the downloads directory:

```bash
docker compose down
rm -rf ./downloads
```

`./downloads` is the host directory mounted into the API container as
`/app/downloads`. The directory will be recreated when the API runs again.

## Security Notes

This app can consume network bandwidth, CPU, and disk space. Run it on a trusted
machine or trusted LAN where users are allowed to create download and conversion
jobs.
