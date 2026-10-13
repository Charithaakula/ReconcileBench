# Episode image for running ReconcileBench episodes in the Codex CLI harness.
# Base: the same pinned image the paper's mini-swe-agent config uses for its Docker mode.
FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285

# Userland the agent can use (comparable to the macOS shell the local-mode runs had), plus
# Node for the Codex CLI. No Python packages beyond the standard library, as in the paper runs.
RUN apt-get update \
 && apt-get install -y --no-install-recommends bash git curl ca-certificates procps nodejs npm \
 && rm -rf /var/lib/apt/lists/*

# The Codex CLI version used for the paper's runs.
RUN npm install -g @openai/codex@0.157.1 && codex --version

# Unprivileged user; the episode workspace and the Codex home are mounted at run time.
RUN useradd -m -u 1000 agent
USER agent
ENV CODEX_HOME=/codex-home
WORKDIR /workspace
