#!/bin/bash

# CryptoTrader 起動スクリプト

set -e  # エラー時に停止

# カラー定義
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=====================================${NC}"
echo -e "${GREEN}  CryptoTrader 起動スクリプト${NC}"
echo -e "${GREEN}=====================================${NC}"
echo

# プロジェクトルートに移動
cd "$(dirname "$0")"

# Python仮想環境の確認
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}[警告] 仮想環境が見つかりません${NC}"
    echo -e "仮想環境を作成しますか？ (y/n)"
    read -r create_venv

    if [ "$create_venv" = "y" ] || [ "$create_venv" = "Y" ]; then
        echo -e "${GREEN}[1/3] Python仮想環境作成中...${NC}"
        python3 -m venv venv
        echo -e "${GREEN}✓ 仮想環境作成完了${NC}"

        echo -e "${GREEN}[2/3] 依存パッケージインストール中...${NC}"
        source venv/bin/activate
        pip install --upgrade pip
        pip install -r requirements.txt
        echo -e "${GREEN}✓ パッケージインストール完了${NC}"
    else
        echo -e "${RED}仮想環境が必要です。セットアップを終了します。${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}[1/2] 仮想環境アクティベート${NC}"
    source venv/bin/activate
fi

# .envファイルの確認
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}[警告] .envファイルが見つかりません${NC}"
    echo ".env.exampleをコピーして.envを作成します"
    cp config/.env.example .env
    echo -e "${YELLOW}✓ .envファイルを作成しました${NC}"
    echo -e "${YELLOW}  APIキーを設定する場合は .env を編集してください${NC}"
fi

# データベースディレクトリ作成
echo -e "${GREEN}[2/2] データベースディレクトリ確認${NC}"
mkdir -p database
mkdir -p logs
mkdir -p ml_models
mkdir -p tax_reports
echo -e "${GREEN}✓ ディレクトリ準備完了${NC}"
echo

# 起動モード選択
echo -e "${GREEN}起動モードを選択してください:${NC}"
echo "  1) テストモード（APIキーなし、モック動作）"
echo "  2) 本番モード（bitFlyer API使用）"
echo "  3) モデル学習のみ"
echo "  4) Phase 5統合テスト"
echo

read -p "選択 [1-4]: " mode

case $mode in
    1)
        echo -e "${GREEN}テストモードで起動します${NC}"
        python main_trader.py --test --interval 1
        ;;
    2)
        echo -e "${YELLOW}本番モードで起動します${NC}"
        echo -e "${YELLOW}APIキーが.envに設定されていることを確認してください${NC}"
        read -p "起動してよろしいですか？ (y/n): " confirm
        if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
            python main_trader.py --interval 5
        else
            echo "起動をキャンセルしました"
            exit 0
        fi
        ;;
    3)
        echo -e "${GREEN}モデル学習を開始します${NC}"
        echo "取引ペアを選択してください:"
        echo "  1) BTC/JPY"
        echo "  2) ETH/JPY"
        echo "  3) 両方"
        read -p "選択 [1-3]: " pair_choice

        case $pair_choice in
            1)
                python ml/training/train_models.py --symbol BTC/JPY
                ;;
            2)
                python ml/training/train_models.py --symbol ETH/JPY
                ;;
            3)
                python ml/training/train_models.py --symbol BTC/JPY
                python ml/training/train_models.py --symbol ETH/JPY
                ;;
            *)
                echo -e "${RED}無効な選択です${NC}"
                exit 1
                ;;
        esac
        ;;
    4)
        echo -e "${GREEN}Phase 5統合テストを実行します${NC}"
        python tests/test_phase5_integration.py
        ;;
    *)
        echo -e "${RED}無効な選択です${NC}"
        exit 1
        ;;
esac

echo
echo -e "${GREEN}=====================================${NC}"
echo -e "${GREEN}  処理が完了しました${NC}"
echo -e "${GREEN}=====================================${NC}"
