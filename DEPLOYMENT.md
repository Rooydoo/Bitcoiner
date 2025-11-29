# CryptoTrader デプロイガイド

## 概要

BTC/JPY自動売買システムのデプロイ手順書です。
1時間足スイングトレード戦略で、HMM + LightGBM のアンサンブルモデルを使用します。

---

## 1. 前提条件

### システム要件
- Python 3.9以上
- メモリ: 2GB以上推奨
- ディスク: 1GB以上の空き容量
- 常時稼働環境（VPS推奨）

### 必要なアカウント
- **bitFlyer**: API キーとシークレット
- **Telegram**（任意）: 通知用のBot Token と Chat ID

---

## 2. インストール

### 2.1 リポジトリのクローン

```bash
git clone <repository-url> Bitcoiner
cd Bitcoiner
```

### 2.2 仮想環境の作成

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# または
venv\Scripts\activate  # Windows
```

### 2.3 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

---

## 3. 設定

### 3.1 環境変数ファイルの作成

```bash
cp .env.example .env
```

`.env` を編集:

```env
# bitFlyer API
BITFLYER_API_KEY=your_api_key_here
BITFLYER_API_SECRET=your_api_secret_here

# Telegram通知（任意）
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# 環境設定
ENVIRONMENT=production
LOG_LEVEL=INFO
```

### 3.2 設定ファイルの確認

`config/settings.yaml` を確認・編集:

```yaml
trading:
  symbol: "BTC/JPY"
  timeframe: "1h"
  position_size: 0.5          # 資金の50%をポジションに
  max_position_value: 100000  # 最大ポジション額（円）

  # Wait-for-Dip設定
  wait_for_dip: true
  dip_threshold: 0.02         # 2%の押し目で買い
  dip_timeout_hours: 48       # 48時間でタイムアウト

  # モデル設定
  confidence_threshold: 0.6   # シグナル確信度閾値
  model_exit_threshold: 0.7   # モデル予測反転で決済する閾値

risk:
  stop_loss_pct: 0.05         # 5%で損切り
  take_profit_pct: 0.10       # 10%で利確
  max_drawdown_pct: 0.15      # 最大ドローダウン15%
```

---

## 4. 初回セットアップ

### 4.1 データベース初期化

```bash
python scripts/init_database.py
```

### 4.2 モデルの学習

初回は過去データでモデルを学習させます:

```bash
python scripts/train_models.py --symbol BTC/JPY --days 365
```

### 4.3 ウォークフォワード検証（推奨）

デプロイ前に戦略を検証:

```bash
python scripts/run_walk_forward.py \
  --symbol BTC/JPY \
  --train-days 180 \
  --test-days 30 \
  --step-days 7
```

**確認ポイント:**
- 累積リターンがプラス
- 一貫性比率（Consistency Ratio）が60%以上
- 最大ドローダウンが許容範囲内

---

## 5. 起動

### 5.1 通常起動

```bash
python main_trader.py
```

### 5.2 バックグラウンド起動（本番用）

```bash
# nohupを使用
nohup python main_trader.py > logs/trader.log 2>&1 &

# または systemd サービスとして（推奨）
sudo cp scripts/cryptotrader.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cryptotrader
sudo systemctl start cryptotrader
```

### 5.3 systemd サービスファイル例

`/etc/systemd/system/cryptotrader.service`:

```ini
[Unit]
Description=CryptoTrader BTC/JPY Auto Trading
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/Bitcoiner
Environment=PATH=/path/to/Bitcoiner/venv/bin
ExecStart=/path/to/Bitcoiner/venv/bin/python main_trader.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

---

## 6. 監視・運用

### 6.1 ログの確認

```bash
# リアルタイムログ
tail -f logs/trader.log

# エラーログのみ
grep -i error logs/trader.log
```

### 6.2 ダッシュボード起動

```bash
streamlit run dashboard/app.py --server.port 8501
```

ブラウザで `http://localhost:8501` にアクセス

### 6.3 ポジション確認

```bash
python scripts/check_position.py
```

### 6.4 サービス状態確認

```bash
sudo systemctl status cryptotrader
```

---

## 7. 定期メンテナンス

### 7.1 モデル再学習（週次推奨）

```bash
# cronに追加
0 0 * * 0 /path/to/Bitcoiner/venv/bin/python /path/to/Bitcoiner/scripts/train_models.py --symbol BTC/JPY --days 365
```

### 7.2 ログローテーション

`/etc/logrotate.d/cryptotrader`:

```
/path/to/Bitcoiner/logs/*.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
}
```

---

## 8. トラブルシューティング

### 8.1 API接続エラー

```
原因: APIキーが無効、またはIP制限
対処:
1. bitFlyerでAPIキーを確認
2. IP制限がある場合は許可リストに追加
3. APIキーの権限を確認（トレード権限が必要）
```

### 8.2 モデル読み込みエラー

```
原因: モデルファイルが存在しない
対処:
python scripts/train_models.py --symbol BTC/JPY --days 365
```

### 8.3 ポジション不整合

```
原因: 手動取引または通信エラー
対処:
python scripts/reconcile_position.py --symbol BTC/JPY
```

### 8.4 メモリ不足

```
原因: 長時間稼働によるメモリリーク
対処:
sudo systemctl restart cryptotrader
```

---

## 9. 緊急停止

### 9.1 システム停止

```bash
# サービスの場合
sudo systemctl stop cryptotrader

# nohupの場合
pkill -f main_trader.py
```

### 9.2 全ポジション決済

```bash
python scripts/emergency_close.py --symbol BTC/JPY
```

---

## 10. 注意事項

1. **本番稼働前に必ずウォークフォワード検証を実行**
2. **初期は少額（10万円程度）でテスト運用推奨**
3. **APIキーは絶対にGitにコミットしない**
4. **定期的にログとパフォーマンスを確認**
5. **急激な相場変動時は手動介入を検討**

---

## 11. サポート

問題が発生した場合:
1. `logs/` ディレクトリのログを確認
2. `docs/` ディレクトリのドキュメントを参照
3. GitHubのIssueで報告

---

## 12. 本番サーバーデプロイ

### 12.1 サーバー接続情報

```
ホスト: 72.60.208.158
ユーザー: root
接続コマンド: ssh root@72.60.208.158
```

### 12.2 初回セットアップ手順

```bash
# 1. サーバーに接続
ssh root@72.60.208.158

# 2. 作業ディレクトリ作成
mkdir -p /opt/cryptotrader
cd /opt/cryptotrader

# 3. リポジトリをクローン
git clone <repository-url> .

# 4. Python仮想環境のセットアップ
python3 -m venv venv
source venv/bin/activate

# 5. 依存パッケージのインストール
pip install --upgrade pip
pip install -r requirements.txt

# 6. 環境変数の設定
cp config/.env.example config/.env
nano config/.env  # APIキーを設定

# 7. ディレクトリの作成
mkdir -p logs database models
```

### 12.3 systemd サービス設定

```bash
# サービスファイルを作成
cat > /etc/systemd/system/cryptotrader.service << 'EOF'
[Unit]
Description=CryptoTrader BTC/JPY Auto Trading
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/cryptotrader
Environment=PATH=/opt/cryptotrader/venv/bin
ExecStart=/opt/cryptotrader/venv/bin/python main_trader.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# サービスを有効化・起動
systemctl daemon-reload
systemctl enable cryptotrader
systemctl start cryptotrader
```

### 12.4 デプロイ更新手順

```bash
# サーバーに接続
ssh root@72.60.208.158

# サービス停止
systemctl stop cryptotrader

# 最新コードを取得
cd /opt/cryptotrader
git pull origin main

# 依存パッケージ更新（必要に応じて）
source venv/bin/activate
pip install -r requirements.txt

# サービス再開
systemctl start cryptotrader

# ログ確認
journalctl -u cryptotrader -f
```

### 12.5 リモート監視コマンド

```bash
# サービス状態確認
ssh root@72.60.208.158 "systemctl status cryptotrader"

# 最新ログ確認
ssh root@72.60.208.158 "tail -50 /opt/cryptotrader/logs/trader.log"

# ポジション確認
ssh root@72.60.208.158 "cd /opt/cryptotrader && source venv/bin/activate && python scripts/check_position.py"

# 緊急停止
ssh root@72.60.208.158 "systemctl stop cryptotrader"
```

### 12.6 ファイアウォール設定（推奨）

```bash
# SSH以外のポートを制限
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 8501/tcp  # Streamlit ダッシュボード（必要な場合）
ufw enable
```

---

## 更新履歴

- 2025-11-29: 本番サーバーデプロイセクション追加
  - SSH接続情報（72.60.208.158）
  - リモートデプロイ手順
  - 監視コマンド
- 2025-11-27: 初版作成
  - ウォークフォワード検証機能追加
  - Wait-for-Dip戦略対応
  - モデルベース決済機能追加
