# CodeChecker server (VM-hosted)

This directory contains the docker-compose stack that runs the self-hosted
CodeChecker server CTIT pushes its nightly diagnostic reports to.

The stack has three containers behind a Traefik reverse proxy:

- `postgres` — persistent report database (named volume `codechecker_db`)
- `codechecker` — official `codechecker/codechecker-web` server on port 8001
- `traefik` — public HTTPS termination via Let's Encrypt (auto-renewing).
  Routes are wired up via Docker labels on the `codechecker` service, so
  adding more services later (e.g. a metrics dashboard) is just a few more
  labels.

## One-time VM bootstrap

Tested on Ubuntu 24.04.

```sh
# Install Docker Engine + compose plugin (skip if already present).
curl -fsSL https://get.docker.com | sudo sh
sudo systemctl enable --now docker

# Copy this directory to /opt/codechecker on the VM.
sudo mkdir -p /opt/codechecker
sudo rsync -a /path/to/CTIT/codechecker/ /opt/codechecker/
cd /opt/codechecker
sudo cp .env.example .env
sudo chmod 600 .env
sudo $EDITOR .env             # fill in domain, passwords

# Make sure the entrypoint is executable on the host so the bind-mount works.
sudo chmod +x entrypoint.sh

# Install the systemd unit so the stack starts on boot.
sudo cp systemd/codechecker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now codechecker.service
```

DNS: point an `A` (and optionally `AAAA`) record for `CODECHECKER_DOMAIN` at the
VM's public IP **before** starting the stack. Traefik obtains a Let's Encrypt
certificate on first run and will fail loudly if the domain doesn't resolve.

Ports `80` and `443` on the VM must be reachable from the public internet for
ACME HTTP-01 validation and for the GitHub Actions runner to reach the server.

> Traefik mounts `/var/run/docker.sock` read-only to discover the `codechecker`
> service via labels. This is the standard Traefik pattern but it does expose
> the Docker API to one container — fine for a single-tenant VM, worth
> revisiting if you ever add untrusted workloads to the host.

## Verify the stack

```sh
sudo systemctl status codechecker.service    # should be active (exited)
sudo docker compose ps                       # all three services Up
curl -I https://your.codechecker.domain      # 200 / 302 from CodeChecker
```

## Create the GitHub Actions service account and API token

1. Open `https://<CODECHECKER_DOMAIN>` and sign in with the superuser
   credentials from `.env`.
2. In the top-right user menu choose **Show personal access tokens** and create
   a token. Description: `ctit-nightly-runner`.
3. Paste the token into the `CODECHECKER_API_TOKEN` repository secret in
   GitHub. Set `CODECHECKER_URL` to `https://<CODECHECKER_DOMAIN>/Default`
   (the `/Default` product is created automatically on first boot).

## Reboot survival

Two layers of protection keep the stack running across reboots:

1. **`restart: unless-stopped`** on every service in `docker-compose.yml` — the
   Docker daemon brings containers back up after `dockerd` itself restarts.
2. **`codechecker.service`** systemd unit — runs `docker compose up -d` on
   boot, making the intent explicit and surviving unusual states where
   restart policies alone aren't enough (e.g. compose was previously `down`'d
   manually before a reboot).

Verify by running `sudo reboot` and confirming `https://<CODECHECKER_DOMAIN>`
serves within ~60 seconds.

## Upgrading

```sh
cd /opt/codechecker
sudo docker compose pull
sudo systemctl restart codechecker.service
```

The Postgres volume is preserved across upgrades; CodeChecker runs its own DB
schema migrations on startup.

## Backups

The only stateful volumes are `codechecker_db` (Postgres) and
`traefik_letsencrypt` (ACME account + issued certs). Back up `codechecker_db`
regularly with `pg_dump`:

```sh
sudo docker compose exec -T postgres \
  pg_dump -U codechecker codechecker | gzip > codechecker-$(date +%F).sql.gz
```
