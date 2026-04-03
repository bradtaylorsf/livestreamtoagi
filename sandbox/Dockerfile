# Sandbox image for isolated code execution.
# Python 3.12 + Node.js 20 on slim base.
# No pip packages — standard library only.

FROM python:3.12-slim AS base

# Install Node.js 20 from nodesource
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for sandbox execution
RUN useradd --create-home --shell /bin/false sandbox
USER sandbox
WORKDIR /tmp
