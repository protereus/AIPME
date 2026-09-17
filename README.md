# AIPME — Automated Infrastructure Provisioning & Monitoring Engine

[![CI](https://github.com/protereus/AIPME/actions/workflows/ci.yml/badge.svg)](https://github.com/protereus/AIPME/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A Python CLI that provisions a cloud Linux server via API, configures it end-to-end (Docker + Apache), and leaves behind a background job that watches CPU and memory and pushes an alert to your phone the moment either breaches a threshold.

> Status: 🚧 early development — infrastructure and monitoring logic in progress.

## What it does

Run one command and AIPME will:

1. **Provision** — spin up a new server on [Hetzner Cloud](https://www.hetzner.com/cloud) via their API (region, server type and image are configurable).
2. **Configure** — the server bootstraps itself on first boot via [cloud-init](https://cloudinit.readthedocs.io/): Docker installed, Apache running in a container, minimal and repeatable.
3. **Monitor** — deploy a lightweight background job on the server that samples CPU and memory usage on an interval.
4. **Alert** — when usage crosses a configured threshold, push a notification straight to your phone via [ntfy](https://ntfy.sh/), no app-specific setup required.

The goal is a single, auditable command that takes you from "no server" to "server running, configured, and watching itself" — the kind of workflow you'd want for a small self-hosted project or a throwaway environment you don't want to babysit.

## Tech stack

| Layer | Tool |
|---|---|
| CLI / orchestration | Python |
| Provisioning target | [Hetzner Cloud API](https://docs.hetzner.cloud/) |
| Server configuration | cloud-init + Bash |
| Containerisation | Docker |
| Web server | Apache |
| Push alerts | [ntfy](https://ntfy.sh/) |

## Usage

```bash
cp aipme.example.toml aipme.toml   # then edit the values
cp .env.example .env               # then add your Hetzner API token

uv run --env-file .env aipme up       # create the server
uv run --env-file .env aipme status   # show what is running
uv run --env-file .env aipme down     # delete it again
```

`up` is safe to re-run: if a server with that name already exists, it reports it and changes nothing.

## Architecture (planned)

```
┌─────────────┐      ┌──────────────────┐      ┌─────────────────────┐
│  AIPME CLI   │ ───▶ │  Hetzner Cloud   │ ───▶ │   Provisioned VM     │
│  (Python)    │      │  API             │      │                      │
└─────────────┘      └──────────────────┘      │  ┌────────────────┐  │
                                                 │  │ Docker + Apache│  │
                                                 │  └────────────────┘  │
                                                 │  ┌────────────────┐  │
                                                 │  │ Monitor job    │──┼──▶ ntfy ──▶ 📱
                                                 │  │ (CPU / memory) │  │
                                                 │  └────────────────┘  │
                                                 └─────────────────────┘
```

## Roadmap

- [x] Hetzner Cloud provisioning (create/destroy servers via API)
- [ ] cloud-init bootstrap of Docker and Apache
- [ ] Background CPU/memory monitoring job
- [ ] Threshold-based ntfy push alerts
- [ ] Configurable thresholds and polling interval
- [x] Teardown / cleanup command
- [ ] Tests and CI

## Development

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # create .venv and install dependencies
uv run aipme --version       # run the CLI
uv run pytest                # run the tests
uv run ruff check .          # lint
uv run ruff format .         # format
```

## License

MIT
