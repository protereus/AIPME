# AIPME — Automated Infrastructure Provisioning & Monitoring Engine

A Python CLI that provisions a cloud Linux server via API, configures it end-to-end (Docker + Apache), and leaves behind a background job that watches CPU and memory and pushes an alert to your phone the moment either breaches a threshold.

> Status: 🚧 early development — infrastructure and monitoring logic in progress.

## What it does

Run one command and AIPME will:

1. **Provision** — spin up a new server on [Hetzner Cloud](https://www.hetzner.com/cloud) via their API (region, server type and image are configurable).
2. **Configure** — connect over SSH and install Docker and Apache, applying a minimal, repeatable base configuration.
3. **Monitor** — deploy a lightweight background job on the server that samples CPU and memory usage on an interval.
4. **Alert** — when usage crosses a configured threshold, push a notification straight to your phone via [ntfy](https://ntfy.sh/), no app-specific setup required.

The goal is a single, auditable command that takes you from "no server" to "server running, configured, and watching itself" — the kind of workflow you'd want for a small self-hosted project or a throwaway environment you don't want to babysit.

## Tech stack

| Layer | Tool |
|---|---|
| CLI / orchestration | Python |
| Provisioning target | [Hetzner Cloud API](https://docs.hetzner.cloud/) |
| Server configuration | Bash (remote setup scripts) |
| Containerisation | Docker |
| Web server | Apache |
| Push alerts | [ntfy](https://ntfy.sh/) |

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

- [ ] Hetzner Cloud provisioning (create/destroy servers via API)
- [ ] SSH-based configuration of Docker and Apache
- [ ] Background CPU/memory monitoring job
- [ ] Threshold-based ntfy push alerts
- [ ] Configurable thresholds and polling interval
- [ ] Teardown / cleanup command
- [ ] Tests and CI

## License

MIT
