#!/bin/zsh
cd -- "$(dirname -- "$0")"
if [[ -x .venv-studio/bin/python ]]; then
  exec .venv-studio/bin/python studio.py
fi
print '运行环境尚未准备好，请使用完整环境包。'
read -k 1
