#!/bin/bash
# CryptoTrader 起動スクリプト

# プロジェクトディレクトリに移動
cd "$(dirname "$0")/.." || exit 1

# 仮想環境をアクティベート
source venv/bin/activate

# ログディレクトリの作成
mkdir -p logs

# ボット起動（5分間隔でサイクル実行）
python main_trader.py --interval 5 2>&1 | tee -a logs/bot_$(date +%Y%m%d).log
