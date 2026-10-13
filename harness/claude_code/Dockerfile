# Episode image for running ReconcileBench episodes in the Claude Code harness.
# Base: the same pinned image the paper's mini-swe-agent config uses for its Docker mode.
FROM python:3.13-slim@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285

# Userland comparable to the other harness images, plus Node for Claude Code and
# bubblewrap/socat for Claude Code's Linux command sandbox. Standard library Python only.
RUN apt-get update \
 && apt-get install -y --no-install-recommends bash git curl ca-certificates procps nodejs npm bubblewrap socat ripgrep \
 && rm -rf /var/lib/apt/lists/*

# The Claude Code version used for the paper's run.
RUN npm install -g @anthropic-ai/claude-code@2.1.289 && claude --version

# Unprivileged user (Claude Code refuses to bypass permissions as root). HOME is a fresh
# per-episode mount; the episode workspace is mounted at /workspace.
RUN useradd -m -u 1000 agent
USER agent
WORKDIR /workspace
