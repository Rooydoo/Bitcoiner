# CryptoTrader - 暗号資産自動売買システム

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

円建て（JPY）での暗号資産自動売買システム。BTC/JPY・ETH/JPYの取引に対応し、機械学習による価格予測と段階的な利益確定・リスク管理機能を実装。

## 📋 目次

- [特徴](#特徴)
- [システム構成](#システム構成)
- [必要要件](#必要要件)
- [セットアップ](#セットアップ)
- [設定](#設定)
- [使い方](#使い方)
- [リスク管理](#リスク管理)
- [トラブルシューティング](#トラブルシューティング)
- [開発](#開発)

## ✨ 特徴

### 📊 Phase 1: データインフラ
- **bitFlyer API統合** - 円建て取引（BTC/JPY, ETH/JPY）
- **SQLite データベース** - 3DB構成（価格・取引・MLモデル）
- **テクニカル指標** - 20種類以上の指標を自動計算
- **タスクスケジューラー** - APSchedulerによる自動実行

### 🤖 Phase 2: ML予測モデル
- **特徴量エンジニアリング** - 107種類の特徴量を生成
- **HMMモデル** - 市場状態分類（Bear/Range/Bull）
- **LightGBMモデル** - 価格方向予測（3クラス分類）
- **アンサンブルモデル** - HMM+LightGBMで信号統合
- **バックテストエンジン** - 手数料・スリッページ考慮

### 💹 Phase 3: 取引エンジン
- **注文実行** - 成行/指値注文、テストモード対応
- **ポジション管理** - エントリー/エグジット、損益計算
- **リスク管理**
  - ストップロス: -10%
  - 第1段階利確: +15%で50%決済
  - 第2段階利確: +25%で全決済
  - 最大ドローダウン: -20%

### 📈 Phase 4: レポート・通知
- **Telegram Bot通知** - 取引通知、日次サマリー、アラート
- **Telegram Botコマンド** - 双方向制御（/status, /pause, /resume等）
- **レポート生成** - 日次3回 + 週次 + 月次レポート
- **税務処理** - CSVエクスポート、年間損益計算

### 🚀 Phase 5: 統合・デプロイ
- **メイントレーダー** - 全コンポーネント統合
- **設定管理** - YAML + 環境変数
- **起動スクリプト** - 仮想環境自動セットアップ
- **統合テスト** - エンドツーエンドテスト

### 🤖 Phase 6: AI戦略最適化（New!）
- **LLM戦略アドバイザー** - Claude Sonnet 4.5による高度な分析
- **自動パラメータ調整提案** - 損切/利確ライン、資産配分の最適化
- **週次・月次パフォーマンス分析** - 勝率、PF、Sharpe Ratio等
- **ルールベースフォールバック** - API障害時も安全動作

### 🛡️ 高度なリスク管理（New!）
- **部分決済** - +15%で50%決済、+25%で全決済（MUST機能）
- **連続損失制限** - 5連敗で自動一時停止
- **期間別損失制限** - 日次5%, 週次10%, 月次15%
- **ポジション数制限** - 最大1ポジション（相関リスク低減）
- **API障害検知** - 3連続エラーで安全停止
- **Telegram経由制御** - 外出先から一時停止/再開可能

## 🏗 システム構成

```
CryptoTrader/
├── data/                   # データ収集・処理
│   ├── collector/         # bitFlyer API
│   ├── processor/         # テクニカル指標
│   └── storage/           # SQLite DB管理
├── ml/                     # 機械学習
│   ├── models/            # HMM, LightGBM, Ensemble
│   └── training/          # 特徴量生成、バックテスト
├── trading/                # 取引エンジン
│   ├── order_executor.py  # 注文実行
│   ├── position_manager.py # ポジション管理
│   └── risk_manager.py    # リスク管理
├── notification/           # Telegram通知
├── reporting/              # レポート生成
├── utils/                  # ユーティリティ
├── tests/                  # テストコード
├── config/                 # 設定ファイル
├── main_trader.py          # メインプログラム
└── start.sh                # 起動スクリプト
```

## 💻 必要要件

### ハードウェア
- **CPU**: 2コア以上
- **RAM**: 8GB以上
- **ストレージ**: 10GB以上の空き容量

### ソフトウェア
- **Python**: 3.11以上
- **OS**: Linux / macOS / Windows（WSL推奨）
- **Git**: バージョン管理

### 取引所アカウント
- **bitFlyer**アカウント
  - API Key / API Secret の取得
  - 取引権限の有効化

### オプション（推奨）
- **Telegram Bot**: 通知機能
- **VPS**: Hostinger等（24時間稼働）

## 🚀 セットアップ

### 1. リポジトリのクローン

```bash
git clone https://github.com/yourusername/Bitcoiner.git
cd Bitcoiner
```

### 2. 仮想環境の作成と依存パッケージのインストール

```bash
# Python仮想環境作成
python3 -m venv venv

# 仮想環境有効化（Linux/macOS）
source venv/bin/activate

# 仮想環境有効化（Windows）
venv\Scripts\activate

# 依存パッケージインストール
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. ディレクトリ作成

```bash
mkdir -p database logs ml_models tax_reports
```

### 4. 環境変数の設定

```bash
# .envファイルを編集
nano .env
```

```.env
# bitFlyer API（本番運用時に設定）
BITFLYER_API_KEY=your_api_key_here
BITFLYER_API_SECRET=your_api_secret_here

# Telegram Bot（通知機能を使う場合）
# ボット作成: @BotFather で新規Bot作成
# Chat ID取得: @userinfobot でChat ID確認
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Anthropic API（LLM戦略アドバイザーを使う場合 - オプション）
# https://console.anthropic.com/ でAPIキー取得
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

**⚠️ 重要:** 本番運用時は必ず以下を設定してください：
- `BITFLYER_API_KEY` / `BITFLYER_API_SECRET` （必須）
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` （強く推奨 - 緊急通知用）
- `ANTHROPIC_API_KEY` （オプション - LLM戦略分析を使う場合）
```

**Telegram Bot設定手順:**
1. [@BotFather](https://t.me/BotFather) にアクセス
2. `/newbot` でBot作成 → トークン取得
3. [@userinfobot](https://t.me/userinfobot) でChat ID確認

### 5. パッケージインストール確認

以下のコマンドで必須パッケージがインストールされているか確認：

```bash
# 仮想環境が有効化されていることを確認
source venv/bin/activate  # Linux/macOS
# または
venv\Scripts\activate  # Windows

# 重要パッケージの確認
pip list | grep -E "anthropic|python-telegram-bot|ccxt|lightgbm"
```

**期待される出力:**
```
anthropic          0.40.0以上
ccxt               4.1.40以上
lightgbm           4.1.0以上
python-telegram-bot 20.6
```

**パッケージが見つからない場合:**
```bash
pip install -r requirements.txt
```

### 6. 設定ファイルの確認

`config/config.yaml` を確認・必要に応じて編集:

```yaml
trading:
  initial_capital: 200000      # 初期資本（円）
  min_confidence: 0.6          # 最小シグナル信頼度
  trading_interval_minutes: 5  # 取引サイクル間隔

risk_management:
  stop_loss_pct: 10.0          # ストップロス
  take_profit_first: 15.0      # 第1段階利確
  take_profit_second: 25.0     # 第2段階利確
```

## 🔧 設定

### bitFlyer API取得方法

1. [bitFlyer](https://bitflyer.com/)にログイン
2. 「API」→「新しいAPIキーを追加」
3. 権限設定:
   - 資産残高を取得: ✓
   - 新規注文を出す: ✓
   - 注文をキャンセルする: ✓
4. APIキー・シークレットをコピーして`.env`に設定

### リスク管理パラメータ

| パラメータ | デフォルト | 説明 |
|----------|---------|------|
| `stop_loss_pct` | 10.0% | ストップロス（損切り） |
| `take_profit_first` | +15.0% | 第1段階利確（50%決済） |
| `take_profit_second` | +25.0% | 第2段階利確（全決済） |
| `max_drawdown_pct` | 20.0% | 最大ドローダウン |
| `max_position_size` | 0.95 | ポジションサイズ上限 |

## 📖 使い方

### 起動スクリプト（推奨）

```bash
./start.sh
```

モード選択:
1. **テストモード** - APIキーなし、モック動作
2. **本番モード** - bitFlyer API使用
3. **モデル学習のみ** - HMM + LightGBM学習
4. **Phase 5統合テスト** - 全機能テスト

### 手動起動

#### 1. モデル学習

```bash
# BTC/JPYモデル学習
python ml/training/train_models.py --symbol BTC/JPY

# ETH/JPYモデル学習
python ml/training/train_models.py --symbol ETH/JPY
```

#### 2. テストモード（APIキーなし）

```bash
python main_trader.py --test --interval 1
```

#### 3. 本番モード

```bash
# .envにAPIキー設定済みであることを確認
python main_trader.py --interval 5
```

### コマンドラインオプション

```bash
python main_trader.py --help

オプション:
  --config PATH    設定ファイルパス（デフォルト: config/config.yaml）
  --test           テストモード（APIキーなし）
  --interval N     取引サイクル間隔（分、デフォルト: 5）
```

### Telegram Botコマンド（リモート制御）

システム稼働中、Telegramアプリから以下のコマンドでシステムを制御できます：

```
📊 情報取得
/status          - システム状態（稼働中/停止、残高、ポジション）
/positions       - 保有ポジション詳細
/config          - 現在の設定表示

⚙️ 制御
/pause           - 取引一時停止（新規エントリー停止）
/resume          - 取引再開（連続損失カウントリセット）

🔧 設定変更
/set_stop_loss 8.0   - 損切ラインを8.0%に変更
                       (config.yaml自動更新 + バックアップ作成)

❓ その他
/commands        - コマンド一覧（簡潔版）
/help            - 詳細ヘルプ
```

**使用例:**
```
あなた: /status

Bot: 📊 システム状態
     🟢 稼働中
     ▶️ アクティブ
     💰 残高: ¥200,000
     📈 ポジション: 1件
     • BTC/JPY LONG: +5.2%

あなた: /pause

Bot: ⏸️ 取引を一時停止しました
     再開するには: /resume
```

**💡 ヒント:** チャット入力欄で「/」を入力すると、コマンド候補が自動表示されます

## ⚠️ リスク管理

### 段階的利益確定

```
エントリー価格: ¥12,000,000

+15% (¥13,800,000) → 50%決済（第1段階利確）
+25% (¥15,000,000) → 残り全決済（第2段階利確）

-10% (¥10,800,000) → 全決済（ストップロス）
```

### ポジションサイズ計算

```
総資産: ¥200,000
BTC配分: 60% → ¥120,000
ETH配分: 40% → ¥80,000

最大ポジション: 資産の95%まで
```

### 推奨設定

- **初期資本**: 最低20万円以上
- **取引サイクル**: 5分間隔（デフォルト）
- **最小信頼度**: 60%以上（低すぎると頻繁に取引）
- **監視**: 定期的にログ・Telegram通知を確認

## 🐛 トラブルシューティング

### よくある問題

#### 1. データ収集エラー

```
bitflyer fetchOHLCV() is not supported yet
```

**原因**: bitFlyerはfetchOHLCV()未サポート
**解決**: 自動的にfetch_trades()からOHLCVを構築（実装済み）

#### 2. モデル読み込みエラー

```
モデルファイルが見つかりません
```

**原因**: モデル未学習
**解決**: `./start.sh` → 3) モデル学習のみ

#### 3. API接続エラー

```
Authentication failed
```

**原因**: APIキーの設定ミス
**解決**: `.env`の`BITFLYER_API_KEY`/`BITFLYER_API_SECRET`を確認

#### 4. Telegram通知が届かない

```
Telegram通知が無効です
```

**原因**: Token/Chat ID未設定
**解決**: `.env`で`TELEGRAM_BOT_TOKEN`と`TELEGRAM_CHAT_ID`を設定

### ログ確認

```bash
# メインログ
tail -f logs/main_trader.log

# テストログ
tail -f logs/test_phase5.log
```

### データベース確認

```bash
# SQLiteでDB確認
sqlite3 database/trades.db "SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;"
```

## 🔧 開発

### テスト実行

```bash
# Phase 5統合テスト
python tests/test_phase5_integration.py

# Phase 4レポートテスト
python tests/test_phase4_integration.py

# Phase 3取引エンジンテスト
python tests/test_phase3_integration.py
```

### コード品質

```bash
# フォーマット
black .

# リント
flake8 .

# カバレッジ
pytest --cov=. tests/
```

## 📊 パフォーマンス

### バックテスト結果（Phase 2）

```
期間: 2年分のデータ
総リターン: +53.49%
勝率: 71.43%
最大ドローダウン: -12.3%
```

### リソース使用量

```
メモリ使用量: ~150MB（8GBの1.9%）
CPU使用率: 平均5-10%（2コア）
ディスク: ~500MB（データベース + ログ）
```

## 📝 ライセンス

MIT License - 詳細は[LICENSE](LICENSE)を参照

## ⚡ 注意事項

1. **投資は自己責任**: 本システムは予測の正確性を保証しません
2. **少額から開始**: 初めは少額資本でテスト運用を推奨
3. **定期監視**: Telegram通知・ログを定期的に確認
4. **API制限**: bitFlyerのレート制限（0.5秒間隔）に注意
5. **税務処理**: 年間損益の計算・確定申告は各自で実施

## 🤝 サポート

- **Issues**: [GitHub Issues](https://github.com/yourusername/Bitcoiner/issues)
- **ドキュメント**: [Wiki](https://github.com/yourusername/Bitcoiner/wiki)

## 📚 参考リンク

- [bitFlyer API ドキュメント](https://lightning.bitflyer.com/docs)
- [ccxt ドキュメント](https://docs.ccxt.com/)
- [LightGBM ドキュメント](https://lightgbm.readthedocs.io/)
- [hmmlearn ドキュメント](https://hmmlearn.readthedocs.io/)

---

**免責事項**: このソフトウェアは教育目的で提供されています。暗号資産取引には大きなリスクが伴います。損失の可能性を理解した上で、自己責任でご使用ください。
