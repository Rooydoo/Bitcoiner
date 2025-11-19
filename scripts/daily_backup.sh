#!/bin/bash

# CryptoTrader 日次バックアップスクリプト
# cron設定例: 0 3 * * * /path/to/Bitcoiner/scripts/daily_backup.sh

set -e

# プロジェクトルートに移動
cd "$(dirname "$0")/.."

# 仮想環境アクティベート
source venv/bin/activate

# バックアップ実行
echo "========================================" python scripts/backup_database.py --action backup --retention 30
echo "=========================================="
echo

# 終了
deactivate
