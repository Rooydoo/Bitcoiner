"""
CryptoTrader プロジェクト構造自動生成スクリプト

使い方:
1. このファイルを Bitcoiner フォルダに配置
2. コマンドプロンプトまたはPowerShellで実行:
   python setup_project_structure.py
"""

import os
from pathlib import Path

# プロジェクトのベースパス（スクリプトの実行場所を自動取得）
BASE_PATH = Path(__file__).parent.absolute()

# フォルダ構造の定義
FOLDER_STRUCTURE = {
    "config": [],
    "data": {
        "collector": [],
        "processor": [],
        "storage": []
    },
    "ml": {
        "models": [],
        "training": [],
        "prediction": [],
        "backtesting": []
    },
    "trading": {
        "strategy": [],
        "execution": [],
        "risk_management": [],
        "position": []
    },
    "reporting": {
        "telegram_bot": [],
        "report_generator": [],
        "tax_calculator": []
    },
    "ui": {
        "streamlit_app": {
            "pages": [],
            "components": []
        },
        "electron_app": {
            "renderer": []
        }
    },
    "api": [],
    "utils": [],
    "database": [],
    "models": [],
    "logs": [],
    "tests": []
}

# 作成するファイルとその内容
FILES_TO_CREATE = {
    # 設定ファイル
    "config/config.yaml": """# CryptoTrader 設定ファイル

# 取引所設定
exchange:
  name: binance
  use_testnet: false  # 本番運用時はfalse
  
# 取引対象通貨
trading_pairs:
  - symbol: BTC/USDT
    allocation: 0.6  # 60%
  - symbol: ETH/USDT
    allocation: 0.4  # 40%

# リスク管理パラメータ
risk_management:
  max_position_size_pct: 2.0  # 総資産の2%
  stop_loss_pct: 5.0           # 5%損失で強制決済
  take_profit_first: 15.0      # 第1段階利益確定 15%
  take_profit_second: 25.0     # 第2段階利益確定 25%
  max_daily_loss_pct: 5.0      # 日次最大損失
  max_weekly_loss_pct: 10.0    # 週次最大損失
  max_monthly_loss_pct: 15.0   # 月次最大損失
  max_positions: 2             # 最大同時保有数
  consecutive_loss_limit: 5    # 連続損失制限

# ML設定
machine_learning:
  initial_training_days: 730   # 2年分
  retrain_interval_days: 7     # 週次再学習
  lightgbm:
    num_threads: 2
    max_depth: 8
    num_leaves: 31

# レポート設定
reporting:
  morning_report_time: "07:00"
  noon_report_time: "13:00"
  evening_report_time: "22:00"
  
# Streamlit UI設定
ui:
  port: 8501
  host: "0.0.0.0"
  enable_basic_auth: true
""",

    "config/.env.example": """# API Keys（このファイルをコピーして .env を作成し、実際のキーを入力してください）

# Binance API
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here

# Streamlit認証
STREAMLIT_USERNAME=admin
STREAMLIT_PASSWORD=your_secure_password_here

# Google Drive バックアップ（オプション）
GOOGLE_DRIVE_CREDENTIALS_PATH=credentials.json
""",

    "config/risk_params.yaml": """# リスク管理パラメータ詳細設定

position_level:
  stop_loss_pct: 5.0
  take_profit_stage1_pct: 15.0
  take_profit_stage2_pct: 25.0
  trailing_stop_pct: 3.0
  max_hold_time_hours: 72

portfolio_level:
  max_positions: 2
  daily_loss_limit: 5.0
  weekly_loss_limit: 10.0
  monthly_loss_limit: 15.0

system_level:
  circuit_breaker_pct: 10.0
  circuit_breaker_timeframe_min: 5
  max_api_retry: 3
  slippage_tolerance_pct: 3.0
""",

    # データ収集
    "data/collector/binance_api.py": """\"\"\"Binance API接続モジュール\"\"\"

import ccxt
from typing import Dict, List
import pandas as pd

class BinanceDataCollector:
    def __init__(self, api_key: str = None, api_secret: str = None):
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
        })
    
    def fetch_ohlcv(self, symbol: str, timeframe: str = '1m', limit: int = 1000) -> pd.DataFrame:
        \"\"\"ローソク足データ取得\"\"\"
        ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    
    def fetch_ticker(self, symbol: str) -> Dict:
        \"\"\"現在価格取得\"\"\"
        return self.exchange.fetch_ticker(symbol)
""",

    "data/collector/__init__.py": "",
    "data/processor/__init__.py": "",
    "data/storage/__init__.py": "",

    # データベース
    "data/storage/sqlite_manager.py": """\"\"\"SQLiteデータベース管理モジュール\"\"\"

import sqlite3
import pandas as pd
from pathlib import Path
from typing import Optional

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
    
    def connect(self):
        \"\"\"データベース接続\"\"\"
        self.conn = sqlite3.connect(self.db_path)
        return self.conn
    
    def close(self):
        \"\"\"接続クローズ\"\"\"
        if self.conn:
            self.conn.close()
    
    def execute(self, query: str, params: tuple = None):
        \"\"\"クエリ実行\"\"\"
        cursor = self.conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        self.conn.commit()
        return cursor
    
    def fetch_df(self, query: str, params: tuple = None) -> pd.DataFrame:
        \"\"\"クエリ結果をDataFrameで取得\"\"\"
        return pd.read_sql_query(query, self.conn, params=params)
""",

    # ML関連
    "ml/models/__init__.py": "",
    "ml/training/__init__.py": "",
    "ml/prediction/__init__.py": "",
    "ml/backtesting/__init__.py": "",

    # トレーディング
    "trading/strategy/__init__.py": "",
    "trading/execution/__init__.py": "",
    "trading/risk_management/__init__.py": "",
    "trading/position/__init__.py": "",

    # レポーティング
    "reporting/telegram_bot/__init__.py": "",
    "reporting/report_generator/__init__.py": "",
    "reporting/tax_calculator/__init__.py": "",

    # UI
    "ui/streamlit_app/app.py": """\"\"\"Streamlit メインアプリケーション\"\"\"

import streamlit as st

st.set_page_config(
    page_title="CryptoTrader Dashboard",
    page_icon="📊",
    layout="wide"
)

st.title("🚀 CryptoTrader Dashboard")
st.write("暗号資産自動売買システム")

# サイドバー
st.sidebar.title("ナビゲーション")
page = st.sidebar.radio("ページ選択", 
    ["ダッシュボード", "レポート", "Telegram", "設定", "システム"])

if page == "ダッシュボード":
    st.header("📈 ダッシュボード")
    st.info("実装予定: ポジション一覧、損益グラフ、リスク指標")
    
elif page == "レポート":
    st.header("📄 レポート閲覧")
    st.info("実装予定: 朝・昼・夜レポート、月次レポート")
    
elif page == "Telegram":
    st.header("💬 Telegramメッセージ")
    st.info("実装予定: メッセージ履歴、フィルター機能")
    
elif page == "設定":
    st.header("⚙️ 設定・操作")
    st.info("実装予定: リスクパラメータ調整、緊急停止")
    
elif page == "システム":
    st.header("🖥️ システム監視")
    st.info("実装予定: CPU/メモリ使用率、エラーログ")
""",

    "ui/streamlit_app/__init__.py": "",
    "ui/streamlit_app/pages/__init__.py": "",
    "ui/streamlit_app/components/__init__.py": "",

    # ユーティリティ
    "utils/__init__.py": "",
    
    "utils/logger.py": """\"\"\"ロギング設定\"\"\"

import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

def setup_logger(name: str, log_file: str, level=logging.INFO):
    \"\"\"ロガーセットアップ\"\"\"
    log_path = Path("logs") / log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    handler = RotatingFileHandler(
        log_path, 
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    handler.setFormatter(formatter)
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    
    return logger
""",

    # メインスクリプト
    "main.py": """\"\"\"CryptoTrader メインエントリーポイント\"\"\"

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

def main():
    print("🚀 CryptoTrader システム起動")
    print("開発中...")
    
if __name__ == "__main__":
    main()
""",

    "scheduler.py": """\"\"\"タスクスケジューラー\"\"\"

from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime

scheduler = BlockingScheduler()

@scheduler.scheduled_job('cron', hour=7, minute=0)
def morning_report():
    print(f"[{datetime.now()}] 朝レポート生成")

@scheduler.scheduled_job('cron', hour=13, minute=0)
def noon_report():
    print(f"[{datetime.now()}] 昼レポート生成")

@scheduler.scheduled_job('cron', hour=22, minute=0)
def evening_report():
    print(f"[{datetime.now()}] 夜レポート生成")

if __name__ == "__main__":
    print("スケジューラー開始")
    scheduler.start()
""",

    # Streamlit起動スクリプト
    "run_streamlit.sh": """#!/bin/bash
# Streamlit起動スクリプト

cd "$(dirname "$0")"
streamlit run ui/streamlit_app/app.py --server.port 8501 --server.address 0.0.0.0
""",

    "run_streamlit.bat": """@echo off
REM Streamlit起動スクリプト（Windows用）

cd /d %~dp0
streamlit run ui/streamlit_app/app.py --server.port 8501
""",

    # README
    "README.md": """# CryptoTrader - 暗号資産自動売買システム

## 概要
機械学習を用いたBitcoin/Ethereum自動売買システム

## 環境構築

### 1. 依存パッケージのインストール
```bash
pip install -r requirements.txt
```

### 2. 環境変数の設定
```bash
cp config/.env.example config/.env
# .env ファイルを編集してAPI Keyを設定
```

### 3. データベースの初期化
```bash
python scripts/init_database.py
```

## 実行方法

### メインBot起動
```bash
python main.py
```

### Streamlit UI起動
```bash
# Windows
run_streamlit.bat

# Linux/Mac
bash run_streamlit.sh
```

## プロジェクト構造
```
crypto_trader/
├── config/          # 設定ファイル
├── data/            # データ収集・処理
├── ml/              # 機械学習モデル
├── trading/         # 取引ロジック
├── reporting/       # レポート・通知
├── ui/              # UIダッシュボード
├── utils/           # ユーティリティ
└── database/        # SQLiteデータベース
```

## 開発フェーズ
- Phase 1: データ基盤構築（2週間）
- Phase 2: MLモデル開発（3週間）
- Phase 3: 売買エンジン実装（2週間）
- Phase 4: レポート・UI実装（2週間）
- Phase 5: 統合テスト（1週間）

## ライセンス
Private Project
""",

    # requirements.txt
    "requirements.txt": """# CryptoTrader 依存パッケージ

# 基本ライブラリ
numpy==1.24.3
pandas==2.0.3
python-dateutil==2.8.2

# 取引所API
ccxt==4.1.40

# 機械学習
scikit-learn==1.3.2
lightgbm==4.1.0
hmmlearn==0.3.0

# データベース
# sqlite3は標準ライブラリ

# 通知
python-telegram-bot==20.6

# スケジューリング
APScheduler==3.10.4

# UI
streamlit==1.28.2
plotly==5.18.0
matplotlib==3.8.2

# 技術指標
pandas-ta==0.3.14b

# 設定ファイル
PyYAML==6.0.1
python-dotenv==1.0.0

# ユーティリティ
requests==2.31.0
tqdm==4.66.1

# バックアップ（オプション）
# google-auth==2.23.4
# google-auth-oauthlib==1.1.0
# google-api-python-client==2.108.0

# 開発用
pytest==7.4.3
pytest-cov==4.1.0
black==23.11.0
flake8==6.1.0
""",

    ".gitignore": """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# 環境
.env
.venv
env/
venv/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# データベース
database/*.db
database/*.db-journal

# ログ
logs/*.log

# モデル
models/*.pkl
models/*.joblib

# OS
.DS_Store
Thumbs.db

# 機密情報
config/.env
config/*_key.json
credentials.json

# Streamlit
.streamlit/secrets.toml
""",
}


def create_folder_structure(base_path: Path, structure: dict, current_path: Path = None):
    """フォルダ構造を再帰的に作成"""
    if current_path is None:
        current_path = base_path
    
    for name, children in structure.items():
        folder_path = current_path / name
        folder_path.mkdir(parents=True, exist_ok=True)
        print(f"✓ フォルダ作成: {folder_path.relative_to(base_path)}")
        
        if isinstance(children, dict):
            create_folder_structure(base_path, children, folder_path)


def create_files(base_path: Path, files: dict):
    """ファイルを作成"""
    for file_path, content in files.items():
        full_path = base_path / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✓ ファイル作成: {full_path.relative_to(base_path)}")


def main():
    """メイン処理"""
    print("=" * 60)
    print("CryptoTrader プロジェクト構造セットアップ")
    print("=" * 60)
    print(f"\nベースパス: {BASE_PATH}")
    print()
    
    # ベースディレクトリの確認
    if not BASE_PATH.exists():
        print(f"エラー: {BASE_PATH} が存在しません")
        print("フォルダを作成してから再実行してください")
        return
    
    # フォルダ構造作成
    print("📁 フォルダ構造を作成中...")
    create_folder_structure(BASE_PATH, FOLDER_STRUCTURE)
    print()
    
    # ファイル作成
    print("📄 ファイルを作成中...")
    create_files(BASE_PATH, FILES_TO_CREATE)
    print()
    
    print("=" * 60)
    print("✅ セットアップ完了！")
    print("=" * 60)
    print("\n次のステップ:")
    print("1. config/.env.example を config/.env にコピー")
    print("2. config/.env にBinance APIキーとTelegram Bot Tokenを設定")
    print("3. pip install -r requirements.txt を実行")
    print("4. 開発を開始！")
    print()


if __name__ == "__main__":
    main()