# SPDX-FileCopyrightText: Copyright (C) 2026 Renegade Penguin LLC
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Hammunition Bunker: a verified LAN mirror of Hammunition's offline data.
#
# Debian 13 slim, a non-root `bunker` user, and nothing from a Python package
# index: Python and the engine's two dependencies (pydantic, PyYAML) come from
# Debian's archive, the engine from its release archive verified against a
# pinned sha256, and the Bunker from this build context. The volume is the
# only writable path the Bunker uses.
#
#   docker build -t hammunition-bunker .
#
# The build REFUSES until ENGINE_SHA256 below is the real digest of the
# engine release archive (docs/guide.md, "Building the image"). That is on
# purpose: the alternative is an unverified engine.

FROM debian:trixie-slim

# The Hammunition release this image asks and imports. The floor in
# src/bunker/__init__.py and the pin in pyproject.toml say the same;
# tests/test_repo_hygiene.py holds the three together.
ARG ENGINE_VERSION=0.19.0
ARG ENGINE_URL=https://github.com/ChiefGyk3D/Hammunition/archive/refs/tags/v${ENGINE_VERSION}.tar.gz
# Filled at the first release: sha256 of ENGINE_URL's bytes.
ARG ENGINE_SHA256=9d35c28f01c86b6a6dea6c9e05edf9bdea6eaf65d42081fd80f769ca00b81a7a

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates python3 python3-venv python3-setuptools python3-wheel \
        python3-pydantic python3-yaml \
    && rm -rf /var/lib/apt/lists/*

# The engine: fetched, verified, unpacked. Its tree stays at /opt/hammunition
# because its wheel carries no catalog; HAMMUNITION_CATALOG points the engine
# at the catalog of exactly the release that was verified.
COPY packaging/fetch_engine.py /usr/local/lib/bunker-build/fetch_engine.py
RUN python3 /usr/local/lib/bunker-build/fetch_engine.py \
        "${ENGINE_URL}" "${ENGINE_SHA256}" /opt/hammunition \
    && python3 -m venv --system-site-packages /opt/bunker \
    && /opt/bunker/bin/pip install --no-index --no-deps --no-build-isolation \
        --disable-pip-version-check /opt/hammunition

# The Bunker itself, from this context.
COPY pyproject.toml README.md LICENSE /usr/local/src/bunker/
COPY src /usr/local/src/bunker/src
RUN /opt/bunker/bin/pip install --no-index --no-deps --no-build-isolation \
        --disable-pip-version-check /usr/local/src/bunker \
    && rm -rf /usr/local/src/bunker

RUN useradd --system --uid 10001 --user-group --no-create-home \
        --home-dir /tmp --shell /usr/sbin/nologin bunker \
    && mkdir -p /data /etc/bunker \
    && chown bunker:bunker /data

ENV PATH=/opt/bunker/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    HAMMUNITION_CATALOG=/opt/hammunition/catalog \
    HOME=/tmp \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER bunker
VOLUME /data
EXPOSE 8080

# The server answers /index.json from the first second (an empty index
# before the first run). The port is the image default; a config that moves
# it needs the healthcheck moved too.
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/index.json', timeout=5)"]

# No shell wrapper: SIGTERM reaches the process and `docker stop` is clean.
ENTRYPOINT ["bunker"]
CMD ["schedule", "--config", "/etc/bunker/bunker.toml"]
