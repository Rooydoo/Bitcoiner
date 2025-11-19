# CryptoTrader - 暗号資産自動売買システム

## 概要
機械学習を用いたBitcoin/Ethereum半自動売買システム

**初期運用資金**: 20万円（BTC:ETH = 6:4）
**リスク管理**: 段階的利益確定（+15%で50%、+25%で残り50%）
**環境**: Hostinger VPS（CPU 2コア、メモリ8GB）

---

## 開発状況

### ✅ Phase 1: データ基盤構築（完了）

**実装済みコンポーネント**:
- ✅ SQLiteデータベーススキーマ（price_data.db, trades.db, ml_models.db）
- ✅ bitFlyer API連携モジュール（ccxt）- 円建て取引対応
- ✅ 技術指標計算モジュール（20種類以上）
  - トレンド系: SMA, EMA, MACD, ADX
  - オシレーター系: RSI, Stochastic, CCI
  - ボラティリティ系: Bollinger Bands, ATR
  - 出来高系: OBV, VWAP
- ✅ データ収集オーケストレーター
- ✅ タスクスケジューラー（APScheduler）
- ✅ ロギングシステム（7日ローテーション）
- ✅ リソース監視システム

**パフォーマンス**:
- メモリ使用量: 153 MB（1.15%）- 非常に効率的
- 技術指標計算: 1000行を0.14秒で処理
- リソース警告: なし（全て正常範囲内）

### 🚧 Phase 2: MLモデル開発（次のステップ）
- HMM（Hidden Markov Model）実装
- LightGBM実装
- 特徴量エンジニアリング
- バックテストエンジン構築

### 📋 Phase 3: 売買エンジン実装
- 注文実行モジュール
- ポジション管理システム
- リスク管理ロジック

### 📋 Phase 4: レポート・UI実装
- Telegram Bot
- Streamlit Webダッシュボード
- 税務処理モジュール

### 📋 Phase 5: 統合テスト・デプロイ

---

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
データベースは自動的に初期化されます。初めて実行時に3つのDBファイルが作成されます。

---

## 実行方法

### テストの実行
```bash
# データベーステスト
python tests/test_database.py

# 技術指標テスト
python tests/test_indicators.py

# Phase 1統合テスト
python tests/test_phase1_integration.py
```

### スケジューラー起動（データ収集）
```bash
python scheduler.py
```

### Streamlit UI起動（Phase 4で実装予定）
```bash
# Windows
run_streamlit.bat

# Linux/Mac
bash run_streamlit.sh
```

---

## プロジェクト構造
```
crypto_trader/
├── config/                      # 設定ファイル
│   ├── config.yaml              # メイン設定
│   ├── .env.example             # 環境変数テンプレート
│   └── risk_params.yaml         # リスク管理パラメータ
├── data/                        # データ収集・処理
│   ├── collector/               # データ収集
│   │   ├── bitflyer_api.py      # bitFlyer API連携（円建て）
│   │   └── data_orchestrator.py # データ収集統合
│   ├── processor/               # データ処理
│   │   └── indicators.py        # 技術指標計算
│   └── storage/                 # データベース
│       └── sqlite_manager.py    # SQLite管理
├── ml/                          # 機械学習モデル（Phase 2で実装）
│   ├── models/
│   ├── training/
│   ├── prediction/
│   └── backtesting/
├── trading/                     # 取引ロジック（Phase 3で実装）
│   ├── strategy/
│   ├── execution/
│   ├── risk_management/
│   └── position/
├── reporting/                   # レポート・通知（Phase 4で実装）
│   ├── telegram_bot/
│   ├── report_generator/
│   └── tax_calculator/
├── ui/                          # UIダッシュボード（Phase 4で実装）
│   └── streamlit_app/
├── utils/                       # ユーティリティ
│   ├── logger.py                # ロギング
│   └── resource_monitor.py      # リソース監視
├── database/                    # SQLiteファイル格納
├── models/                      # 学習済みモデル（Phase 2で使用）
├── logs/                        # ログファイル
├── tests/                       # テストコード
├── scheduler.py                 # タスクスケジューラー
└── main.py                      # メインエントリーポイント
```

---

## 技術スタック

- **言語**: Python 3.10+
- **データベース**: SQLite 3.x
- **取引所API**: ccxt（bitFlyer）- 円建て取引
- **機械学習**: scikit-learn, LightGBM, hmmlearn（Phase 2）
- **通知**: python-telegram-bot（Phase 4）
- **UI**: Streamlit（Phase 4）
- **スケジューリング**: APScheduler
- **リソース監視**: psutil

---

## テスト結果

### Phase 1統合テスト（2025-11-19）
- ✅ データベース: 50件のデータ取得成功
- ✅ 技術指標計算: 0.14秒で1000行処理
- ✅ メモリ効率: 153.07 MB使用（1.15%）
- ✅ リソース警告: なし

---

## ライセンス
Private Project
