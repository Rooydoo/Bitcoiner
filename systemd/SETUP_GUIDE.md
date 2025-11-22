# VPS上での自動起動設定ガイド

## 方法1: systemd サービス（推奨）

### 特徴
- システム起動時に自動起動
- クラッシュ時の自動再起動
- ログ管理が容易
- サービスとして管理可能

### セットアップ手順

1. **サービスファイルを編集**
```bash
cd ~/Bitcoiner/systemd
nano cryptotrader.service
```

以下を自分の環境に合わせて修正：
- `YOUR_USERNAME` → あなたのユーザー名（例: ubuntu, user など）
- パスが正しいか確認

2. **サービスファイルをシステムにコピー**
```bash
sudo cp cryptotrader.service /etc/systemd/system/
sudo chmod 644 /etc/systemd/system/cryptotrader.service
```

3. **サービスを有効化・起動**
```bash
sudo systemctl daemon-reload
sudo systemctl enable cryptotrader
sudo systemctl start cryptotrader
```

4. **ステータス確認**
```bash
sudo systemctl status cryptotrader
```

5. **ログ確認**
```bash
# リアルタイムでログを確認
sudo journalctl -u cryptotrader -f

# 最新100行を確認
sudo journalctl -u cryptotrader -n 100
```

### サービス管理コマンド

```bash
# 起動
sudo systemctl start cryptotrader

# 停止
sudo systemctl stop cryptotrader

# 再起動
sudo systemctl restart cryptotrader

# 自動起動を無効化
sudo systemctl disable cryptotrader

# ステータス確認
sudo systemctl status cryptotrader
```

---

## 方法2: screen セッション（シンプル）

### 特徴
- セットアップが簡単
- SSH切断後も動き続ける
- デバッグしやすい

### セットアップ手順

1. **screen をインストール（未インストールの場合）**
```bash
sudo apt update
sudo apt install screen -y
```

2. **screen セッションで起動**
```bash
cd ~/Bitcoiner
screen -S cryptotrader
source venv/bin/activate
python main_trader.py --interval 5
```

3. **セッションをデタッチ（バックグラウンド化）**
- `Ctrl+A` を押してから `D` を押す

4. **セッションに再接続**
```bash
screen -r cryptotrader
```

5. **すべてのセッション一覧**
```bash
screen -ls
```

---

## 方法3: tmux セッション

### 特徴
- screenより高機能
- ウィンドウ分割可能

### セットアップ手順

1. **tmux をインストール**
```bash
sudo apt update
sudo apt install tmux -y
```

2. **tmux セッションで起動**
```bash
cd ~/Bitcoiner
tmux new -s cryptotrader
source venv/bin/activate
python main_trader.py --interval 5
```

3. **セッションをデタッチ**
- `Ctrl+B` を押してから `D` を押す

4. **セッションに再接続**
```bash
tmux attach -t cryptotrader
```

---

## 方法4: nohup（最もシンプル）

### 特徴
- 追加ソフト不要
- 最もシンプル

### セットアップ手順

```bash
cd ~/Bitcoiner
nohup ./scripts/start_bot.sh > logs/nohup.log 2>&1 &
```

### プロセス確認と停止

```bash
# プロセス確認
ps aux | grep main_trader

# 停止（PIDを確認してから）
kill <PID>
```

---

## 推奨構成

**本番環境**: systemd（方法1）
- 理由: 自動再起動、ログ管理、システム統合

**開発・テスト**: screen（方法2）
- 理由: 簡単にアタッチ/デタッチできる

---

## トラブルシューティング

### ボットが起動しない場合

1. **環境変数を確認**
```bash
cat .env
```

2. **Python環境を確認**
```bash
source venv/bin/activate
python --version
pip list | grep -E "ccxt|pandas|numpy"
```

3. **ログを確認**
```bash
# systemdの場合
sudo journalctl -u cryptotrader -n 50

# screen/tmuxの場合
cat logs/cryptotrader.log
```

4. **手動実行でテスト**
```bash
cd ~/Bitcoiner
source venv/bin/activate
python main_trader.py --test
```

### クラッシュを繰り返す場合

- セーフモードフラグを確認
- データベースの整合性をチェック
- ディスク容量を確認: `df -h`
- メモリ使用量を確認: `free -h`

---

## 監視設定（オプション）

### ヘルスチェックスクリプト

```bash
#!/bin/bash
# ~/Bitcoiner/scripts/healthcheck.sh

if ! systemctl is-active --quiet cryptotrader; then
    echo "CryptoTrader is down! Restarting..."
    sudo systemctl start cryptotrader
    # Telegram通知なども可能
fi
```

### cronで定期チェック（5分ごと）

```bash
crontab -e
```

以下を追加：
```
*/5 * * * * /home/YOUR_USERNAME/Bitcoiner/scripts/healthcheck.sh
```

