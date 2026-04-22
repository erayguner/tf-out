#!/usr/bin/env bash
# End-to-end pipeline runner. Use in CI with AI_TF_APPROVE=yes for auto-apply.
set -euo pipefail

CONFIG="${1:-config/settings.yaml}"
cd "$(dirname "$0")/.."

if ! command -v terraform >/dev/null; then
  echo "terraform CLI not found on PATH" >&2
  exit 127
fi

# Prefer uv when available (fast path, respects uv.lock). Fall back to whichever
# python is on PATH so the script also works in minimal CI runners.
if command -v uv >/dev/null; then
  uv run tf-out run --config "$CONFIG" --non-interactive
else
  python -m src.main run --config "$CONFIG" --non-interactive
fi
