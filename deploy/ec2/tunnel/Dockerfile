# The tunnel service: an SSH server that does ONE thing, accept reverse port forwards from builders' computers.
#
# A builder's connector logs in as "tunnel" with its own key and asks for ONE listening port; the platform backend then reaches
# the builder's localhost through that port. The service has no shell, runs no command, forwards nothing else, and its key list
# is written by the platform (one line per project, each limited to its own port): see services/agent_tunnel.py.
#
# The forwarded ports listen on 127.0.0.1 inside this container only. A small gateway (Caddy, gateway.Caddyfile) is the one
# thing the rest of the network can reach, on :8080, and it passes on only the live-run and insights routes.
#
# Four users, each with one job:
#   tunnel    the only account that can log in (key only, no shell)
#   ttf-keys  runs the AuthorizedKeysCommand: reads the public key list, writes per-connection notes, nothing else
#   ttf-gw    runs the gateway: reads the list of connected ports, nothing else
#   root      sshd itself and the reaper (which ends connections the platform has removed)
FROM alpine:3.20

RUN apk add --no-cache openssh-server caddy su-exec \
 && adduser -D -s /sbin/nologin tunnel \
 && sed -i 's/^tunnel:!/tunnel:*/' /etc/shadow \
 && adduser -D -H -h /nonexistent -s /sbin/nologin ttf-keys \
 && adduser -D -H -h /nonexistent -s /sbin/nologin ttf-gw

COPY sshd_config /etc/ssh/sshd_config
COPY gateway.Caddyfile /etc/ttf-gateway.Caddyfile
COPY authkeys.sh /usr/local/bin/ttf-authkeys
COPY reaper.sh /usr/local/bin/ttf-reaper
COPY listening.sh /usr/local/bin/ttf-listening
COPY entrypoint.sh /entrypoint.sh
RUN chown root:root /etc/ssh/sshd_config /etc/ttf-gateway.Caddyfile /usr/local/bin/ttf-authkeys /usr/local/bin/ttf-reaper /usr/local/bin/ttf-listening /entrypoint.sh \
 && chmod 600 /etc/ssh/sshd_config \
 && chmod 644 /etc/ttf-gateway.Caddyfile \
 && chmod 755 /usr/local/bin/ttf-authkeys /usr/local/bin/ttf-reaper /usr/local/bin/ttf-listening /entrypoint.sh \
 && caddy validate --config /etc/ttf-gateway.Caddyfile --adapter caddyfile

EXPOSE 22 8080
ENTRYPOINT ["/entrypoint.sh"]
