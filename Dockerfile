ARG SINGBOX_VERSION=v1.13.7
FROM ghcr.io/sagernet/sing-box:${SINGBOX_VERSION} AS core
FROM debian:bookworm-slim
ARG INSTALL_WARP=false
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl jq openssl iproute2 procps util-linux tini supervisor gnupg python3 python3-venv \
    && if [ "$INSTALL_WARP" = true ]; then \
      curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --dearmor -o /usr/share/keyrings/cloudflare-warp.gpg; \
      echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp.gpg] https://pkg.cloudflareclient.com/ bookworm main" > /etc/apt/sources.list.d/cloudflare-warp.list; \
      apt-get update && apt-get install -y --no-install-recommends cloudflare-warp; \
    fi && rm -rf /var/lib/apt/lists/*
COPY --from=core /usr/local/bin/sing-box /usr/local/bin/sing-box
COPY upstream /opt/singdock/upstream
COPY docker /opt/singdock/docker
COPY web /opt/singdock/web
COPY requirements.txt /opt/singdock/requirements.txt
RUN python3 -m venv /opt/singdock/venv \
    && /opt/singdock/venv/bin/pip install --no-cache-dir -r /opt/singdock/requirements.txt
RUN chmod +x /opt/singdock/docker/*.sh \
    && ln -s /opt/singdock/docker/manage.sh /usr/local/bin/singdock
WORKDIR /opt/sing-box
ENV ENABLE_WARP=false
VOLUME ["/opt/sing-box", "/var/lib/cloudflare-warp"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD /opt/singdock/docker/healthcheck.sh
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/singdock/docker/entrypoint.sh"]
CMD ["serve"]
