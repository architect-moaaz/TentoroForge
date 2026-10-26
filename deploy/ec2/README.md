# TentoroForge on a single EC2 box (test setup)

A complete stack on one machine: Postgres, Redis, the backend, the frontend, a proxy, and the **tunnel service** that lets
Watch live reach the app running on a builder's own computer.

| Machine | Minimum | Used for the first setup |
|---|---|---|
| CPU / RAM | 4 vCPU / 16 GB | `t3.xlarge` (4 vCPU, 15.8 GB) + 4 GB swap |
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
   Set `PUBLIC_HOST` in `.env` to the address builders reach this server on (public IP or name).
4. `bash build.sh` builds the images (`ttf-frontend`, `ttf-backend`, `ttf-tunnel`) with a throw-away builder and a disk watchdog.
5. `sudo chown -R 1000:1000 data/tunnel data/output` (the backend runs as uid 1000), then `docker compose up -d`.

The only published ports: `127.0.0.1:3100` (the website and API, through the proxy; reach it with an SSH tunnel or put TLS in front)
and `2222` (the tunnel service). **Open TCP 2222 in the security group** to the computers that will use Watch live.

## Watch live: how a builder's computer connects

```
builder's computer                          this server
[app :3001] <-- ssh -R 0.0.0.0:P:localhost:3001 -- [tunnel :2222] <-- [backend]  http://tunnel:P
```

In Watch live the builder presses **Connect your computer**: a one-time code (10 minutes, one use) and one command appear.
The command downloads the connector (`/api/tunnel/connector.mjs`) and runs it in the app's folder. The connector, in order:
checks the app answers on its port, resolves the server's name and checks it can reach the SSH port, swaps the code for a
connection (sending only its own *public* key and a fresh debug secret), writes that secret where the app reads it, and
keeps the tunnel up (reconnecting with a growing wait; stopping, with a reason, when retrying cannot help).

Security: the tunnel service has one user (`tunnel`), key login only, no shell, no commands. Each project's key is limited to
**its own** port (`permitlisten`) and the key list is written by the platform from a registry it keeps in `data/tunnel`. The
listeners are bound inside the tunnel container's network, so only the backend reaches them. The SSH host key is created
once (`data/tunnel-host`) and pinned by the connector, so it cannot be led to another server.

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
* To remove everything: `docker compose down`, then delete this folder and the three `ttf-*:1` images.
