# CryptoTrader - 暗号資産自動売買システム

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
