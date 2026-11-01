#!/usr/bin/env bash
# Unpacks the code, writes the secrets, builds the images (in the background, logged) and starts the stack when built.
set -euo pipefail
mkdir -p /home/ec2-user/ttf && cd /home/ec2-user/ttf
mkdir -p data/pg data/output data/tunnel data/tunnel-host data/caddy-data
rm -rf src && mkdir src && tar -xzf /home/ec2-user/ttf-upload/src.tar.gz -C src
cp /home/ec2-user/ttf-upload/docker-compose.yml /home/ec2-user/ttf-upload/Caddyfile /home/ec2-user/ttf-upload/build.sh /home/ec2-user/ttf-upload/make-env.sh .
chmod +x build.sh make-env.sh
bash make-env.sh
[ -f keys.env ] || { echo "keys.env missing"; exit 2; }
chmod 600 keys.env
# the backend runs as uid 1000 and writes the generated apps here
sudo chown -R 1000:1000 data/output
# ...and the tunnel registry and key list here. The tunnel container's unprivileged key-reading user (ttf-keys) has to be able to
# enter this folder and read the key list (0644), so the folder is 755; the registry beside it (each project's debug secret) is 0600.
sudo chown -R 1000:1000 data/tunnel
sudo chmod 755 data/tunnel
# the tunnel's SSH host key (private half) is created here by the container, as root: nobody else needs to see it
sudo chmod 700 data/tunnel-host
du -sh src | sed 's/^/source unpacked: /'
nohup sg docker -c "bash /home/ec2-user/ttf/build.sh" > /home/ec2-user/ttf/build.log 2>&1 &
echo "build started in the background (log: /home/ec2-user/ttf/build.log)"
