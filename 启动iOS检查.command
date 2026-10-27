#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo '请先按 docs/iOS准备与验证.md 创建 .venv 并安装依赖。'
  exit 1
fi
exec .venv/bin/python -m studio.ios "${@:-doctor}"
