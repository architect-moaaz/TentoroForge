# The tunnel service: an SSH server that does ONE thing, accept reverse port forwards from builders' computers.
#
# A builder's connector logs in as "tunnel" with its own key and asks for ONE listening port; the platform backend then reaches
# the builder's localhost through that port. The service has no shell, runs no command, forwards nothing else, and its key list
# is written by the platform (one line per project, each limited to its own port): see services/agent_tunnel.py.
FROM alpine:3.20

RUN apk add --no-cache openssh-server \
 && adduser -D -s /sbin/nologin tunnel \
 && sed -i 's/^tunnel:!/tunnel:*/' /etc/shadow

COPY sshd_config /etc/ssh/sshd_config
COPY authkeys.sh /usr/local/bin/ttf-authkeys
COPY reaper.sh /usr/local/bin/ttf-reaper
COPY entrypoint.sh /entrypoint.sh
RUN chown root:root /etc/ssh/sshd_config /usr/local/bin/ttf-authkeys /usr/local/bin/ttf-reaper /entrypoint.sh \
 && chmod 600 /etc/ssh/sshd_config \
 && chmod 755 /usr/local/bin/ttf-authkeys /usr/local/bin/ttf-reaper /entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
