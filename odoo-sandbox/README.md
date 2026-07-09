# Odoo Community Sandbox

Official Odoo Community Edition stack using the [Odoo Docker image](https://hub.docker.com/_/odoo) and PostgreSQL 16.

## Quick start

```bash
cd odoo-sandbox
cp .env.example .env
docker compose pull
docker compose up -d
```

Open http://localhost:8069 and create a database from the web UI.

> **Important:** `localhost` only works on the machine where Docker is running. If Odoo is started in a remote/cloud environment, open it from that host or use a tunnel — not from your laptop's `localhost` unless you run the stack locally.

> **Note:** This compose file uses `network_mode: host` so Odoo and PostgreSQL can communicate in restricted container environments where Docker bridge networking between services is blocked.

## Defaults

| Setting | Value |
| --- | --- |
| Odoo version | 18.0 (Community) |
| HTTP port | 8069 |
| Longpolling port | 8072 |
| Database user | `odoo` |
| Database password | value in `.env` |
| Master password | `admin` (set in `config/odoo.conf`) |

## Custom addons

Drop modules into `addons/` — they are mounted at `/mnt/extra-addons`.

Installed modules in this sandbox:

- `ebay_au_connector` — eBay Australia (EBAY_AU) marketplace connector

## Commands

```bash
docker compose logs -f web
docker compose down
docker compose down -v   # also removes database and filestore volumes
```
