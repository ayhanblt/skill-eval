#!/usr/bin/env bash
set -euo pipefail

# Copy OAuth auth material from read-only volume into ephemeral per-run tmp directory
# so runs NEVER persist session history or mutate shared state across containers.
EPHEMERAL_CLAUDE_DIR="/tmp/claude-ephemeral-$$"
mkdir -p "${EPHEMERAL_CLAUDE_DIR}"
if [ -d "/claude-auth-ro" ]; then
  cp -a /claude-auth-ro/. "${EPHEMERAL_CLAUDE_DIR}/" 2>/dev/null || true
fi

export CLAUDE_CONFIG_DIR="${EPHEMERAL_CLAUDE_DIR}"
export HOME="/tmp/home-ephemeral-$$"
mkdir -p "${HOME}"
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_NOSYSTEM=1

# Provide pre-baked offline Node dependencies when a task workspace contains package.json
if [ -f /workspace/package.json ] && [ ! -e /workspace/node_modules ] && [ -d /opt/skilleval-node/node_modules ]; then
  ln -s /opt/skilleval-node/node_modules /workspace/node_modules
fi

# Feed prompt via stdin to the Claude Code CLI arguments passed to entrypoint
exec "$@" < /control/prompt.txt
