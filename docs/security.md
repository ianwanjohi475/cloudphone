# Security hardening

Phones run **privileged** (Redroid requires it for binder/namespaces), so treat
the host as the trust boundary.

## Host

- Dedicated user in the `docker` group; don't run the stack as root.
- `ufw default deny incoming`; allow only your reverse-proxy port.
- Keep the kernel + docker patched. Privileged containers share the host kernel.
- Put `data/` on an encrypted volume if phone state is sensitive.

## Network

- **Never** publish adb ports (5555+) beyond localhost / the docker network.
  The base compose maps them to `localhost` only.
- Remote access only via TLS reverse proxy + auth ([remote-access.md](remote-access.md)).
- Per-phone egress proxies keep phone traffic off your host IP.

## Secrets

- `.env`, `config/proxies.yaml`, and `data/*.fingerprint.json` are gitignored.
- Rotate `DASHBOARD_SECRET`; don't commit proxy credentials.
- The dashboard mounts the docker socket — protect dashboard access accordingly
  (socket access ≈ host root).

## Containers

- Resource limits (`mem_limit`, `nano_cpus`) cap blast radius and noisy
  neighbours.
- `restart: unless-stopped` for resilience without masking crash loops — watch
  `cloudphone health` crash counts.
- Rebuild images regularly to pick up base-image CVE fixes (`make up` rebuilds).

## Operational

- Scope: only run/manage phones you're authorized to. Respect the ToS of any
  service you automate.
- Audit: container logs + `data/` are your record; ship logs off-host if needed.

## Threat notes

- A compromised app inside a phone is contained by the container + host kernel,
  but a kernel escape from a privileged container reaches the host — keep the
  host minimal and patched.
