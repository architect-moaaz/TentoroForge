# TentoroForge on a single EC2 box (test setup)

A complete stack on one machine: Postgres, Redis, the backend, the frontend, a proxy, and the **tunnel service** that lets
Watch live reach the app running on a builder's own computer.

| Machine | Minimum | Used for the first setup |
|---|---|---|
| CPU / RAM | 2 vCPU / 4 GB | `t3.medium` (2 vCPU, 3.8 GB) + 4 GB swap |
| Disk | 30 GB | 30 GB; the images are ~3 GB, and a build needs ~8 GB of scratch space that is given back |

Amazon Linux 2023. Nothing outside this folder is touched.

## Set up

1. `setup.sh`-style prerequisites (done once): swap file, Docker, the compose and buildx plugins.
2. Put the code in `/home/ec2-user/ttf/src` (`git archive`, or a tarball of the working tree).
   **Include the compiled engine packages** (`packages/{schema,engine,library,renderer,patches}/dist`). They are gitignored, so a
   plain `git archive` leaves them out; the server mounts `src/packages` read-only and cannot compile them, and without them every
   generated app fails to build with "Can't resolve '@tentoroforge/engine'". Build them first (`npm run build` in each package)
   and add `packages/*/dist` to the tarball.
3. `bash make-env.sh` writes `.env` (fresh random secrets). Put the model key in `keys.env` (`ANTHROPIC_API_KEY=...`, mode 600).
   Set `PUBLIC_HOST` in `.env` to the address builders reach this server on (public IP or name). To turn HTTPS on, also set
   `PUBLIC_DOMAIN` (see "WARNING: cleartext logins" below).
4. `bash build.sh` builds the images (`ttf-frontend`, `ttf-backend`, `ttf-tunnel`) with a throw-away builder and a disk watchdog.
5. `bash install.sh` does the folder setup (`data/output` and `data/tunnel` are given to uid 1000, the backend's user); if you start the
   stack by hand instead: `sudo chown -R 1000:1000 data/tunnel data/output && sudo chmod 755 data/tunnel`, then `docker compose up -d`.

## Ports this stack publishes

| Port | What | Safe? |
|---|---|---|
| `127.0.0.1:3100` | the website and API, through the proxy, on this machine only | yes: reach it with an SSH tunnel |
| `80` | the same website on the server's **public** address, plain HTTP | **no: cleartext** (see the warning below) |
| `443` | HTTPS for `PUBLIC_DOMAIN` | only answers once `PUBLIC_DOMAIN` is set; until then it refuses connections |
| `2222` | the tunnel service (SSH, key login, no shell) | yes. **Open TCP 2222 in the security group** to the computers that will use Watch live |

Nothing else is published (Postgres, Redis, the backend and the frontend are only reachable inside the stack).

## WARNING: cleartext logins (test data only)

By default the site is also served on port **80 over plain HTTP** (`auto_https` is not used). Anyone on the path between a
browser and this server can read the logins, session cookies and chats that cross it. So, until HTTPS is on:

* use **test data only** (no real customer data, no real passwords reused from anywhere else), and
* prefer the encrypted way in: keep the security group closed for port 80 and open the site through an SSH tunnel to
  `127.0.0.1:3100` (`ssh -L 3100:127.0.0.1:3100 ec2-user@<server>`, then browse `http://localhost:3100`).

### Turning HTTPS on

1. Make a DNS record (`A`) for a name you own, say `ttf-test.example.com`, that points at this server's public IP.
2. Open TCP **80 and 443** in the security group (80 is needed once, for the certificate check and the redirect).
3. In `.env` set `PUBLIC_DOMAIN=ttf-test.example.com` (the name only, no `https://`) and append `,https://ttf-test.example.com` to
   `ALLOWED_ORIGINS`.
4. `docker compose up -d proxy backend`. Caddy fetches and renews the certificate by itself (kept in `data/caddy-data`) and sends
   `http://ttf-test.example.com` to `https://`. Check: `curl -I http://ttf-test.example.com` answers a redirect to https, and
   `curl -I https://ttf-test.example.com` answers 200.
5. Once it works, close port 80 in the security group again (the SSH tunnel to `127.0.0.1:3100` keeps working; the bare IP address
   on port 80 is still plain HTTP, so do not use it).

To switch it off again, empty `PUBLIC_DOMAIN` and `docker compose up -d proxy`.

## Watch live: how a builder's computer connects

```
builder's computer                          this server
[app :3001] <-- ssh -R 0.0.0.0:P:localhost:3001 -- [tunnel :2222] <-- [backend]  http://tunnel:8080/t/P/api/agent/debug
                                                     (sshd listens on 127.0.0.1:P, the gateway on :8080 passes on the two routes)
```

In Watch live the builder presses **Connect your computer**: a one-time code (10 minutes, one use) and one command appear.
The command downloads the connector (`/api/tunnel/connector.mjs`) and runs it in the app's folder. The connector, in order:
checks the app answers on its port, resolves the server's name and checks it can reach the SSH port, swaps the code for a
connection (sending only its own *public* key and a fresh debug secret), writes that secret where the app reads it, and
keeps the tunnel up (reconnecting with a growing wait; stopping, with a reason, when retrying cannot help).

Security: the tunnel service has one user (`tunnel`), key login only, no shell, no commands. Each project's key is limited to
**its own** port (`permitlisten`) and the key list is written by the platform from a registry it keeps in `data/tunnel`. The
forwarded ports listen on `127.0.0.1` **inside the tunnel container only** (`GatewayPorts no`), so no other container can open
them. That matters because the backend container also runs generated apps' code: it reaches a builder's computer only through a small
gateway (Caddy, `tunnel/gateway.Caddyfile`, port 8080 inside the stack, not published) that forwards just
`GET /api/agent/debug` and `GET /api/agent/insights` of ports 22000-22999 and refuses everything else. Those two routes need the
app's debug secret, which only the platform holds. The backend needs `FORGE_TUNNEL_GATEWAY=http://tunnel:8080` (set in
`docker-compose.yml`) for this; the SSH host key is created once (`data/tunnel-host`) and pinned by the connector, so it cannot be
led to another server.

Inside the tunnel container three accounts do the work, none of them root except sshd and the reaper: `tunnel` (the only login), `ttf-keys`
(runs the key command: reads the public key list, writes the per-connection notes, cannot read `registry.json`), `ttf-gw` (runs the gateway).

To check all of this on a machine with Docker: `bash src/deploy/ec2/check-tunnel-isolation.sh` from `/home/ec2-user/ttf` (best with one
computer connected through Watch live).

## Operations

```bash
docker compose ps                         # state
docker compose logs -f backend tunnel     # logs
docker compose restart backend            # after a config change
docker compose down                       # stop (data stays in ./data)
```

* The public address changes if the instance is stopped and started without an Elastic IP: update `PUBLIC_HOST` in `.env`
  and `docker compose up -d backend`.
* Tunnel key list: `data/tunnel/authorized_keys`; registry (private, holds each project's debug secret): `data/tunnel/registry.json`.
* After changing anything under `tunnel/`: `bash build.sh tunnel`, then `docker compose up -d tunnel backend` (the backend restarts too, so it sees the new gateway).
* To remove everything: `docker compose down`, then delete this folder and the three `ttf-*:1` images.
