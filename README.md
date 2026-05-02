# YouTube Downloader

Dockerized YouTube downloader for personal or trusted-LAN use.

This repository is in its initial setup stage. The Docker Compose stack, service Dockerfiles, API, frontend, and Redis wiring described below are planned architecture for later implementation tasks and are not shipped yet.

## Architecture

- `gateway`: planned nginx reverse proxy and the only host-exposed service.
- `frontend`: planned React SPA served internally on Docker network.
- `api`: planned FastAPI backend for source downloads, conversions, and cleanup.
- `redis`: planned API-only task state store with 24-hour TTL.

When implemented, Redis will be attached only to `data_net`. The browser, `gateway`, and `frontend` will not directly reach Redis; only `api` will connect to `redis:6379`.

## Network Model

The planned Compose stack publishes only the gateway host port:

```yaml
ports:
  - "17291:80"
```

This will bind to `0.0.0.0:17291`, so trusted LAN devices will be able to access:

```text
http://<host-ip>:17291
```

After the application is implemented, any device that can reach this LAN port can create download and conversion jobs, which can consume CPU, network bandwidth, and disk space. Do not port-forward this service to the public internet unless authentication and rate limiting are added.

Planned internal Docker networks:

- `frontend_net`: `gateway <-> frontend`
- `api_net`: `gateway <-> api`
- `data_net`: `api <-> redis`

## API Flow

Source download:

```text
source_pending -> source_processing -> source_ready / failed
```

Conversion:

```text
conversion_pending -> conversion_processing -> conversion_ready / failed
```

The planned frontend will call the API with relative paths such as `/api/tasks`; it will never call an API host port directly.
