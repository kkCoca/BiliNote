FROM node:22-bookworm-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    python3 \
    socat \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

RUN npm install -g @jackwener/opencli

WORKDIR /srv

COPY start.sh /srv/start.sh
COPY server.py /srv/server.py

RUN chmod +x /srv/start.sh

# Run the daemon on 127.0.0.1:${OPENCLI_DAEMON_PORT} and forward host-facing 19825 to it.
ENV OPENCLI_DAEMON_PORT=19827
ENV OPENCLI_API_PORT=19826

EXPOSE 19825 19826

CMD ["/srv/start.sh"]
