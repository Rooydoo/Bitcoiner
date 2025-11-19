# systemd サービス設定

CryptoTraderを系systemdサービスとして登録し、VPS起動時に自動実行・異常時の自動再起動を実現します。

## セットアップ手順

### 1. サービスファイルの編集

`cryptotrader.service`を編集し、パスとユーザー名を実際の環境に合わせて変更してください:

```bash
cd /path/to/Bitcoiner/systemd
nano cryptotrader.service
```

変更箇所:
- `User=your_username` → 実際のユーザー名
- `/path/to/Bitcoiner` → 実際のプロジェクトパス（3箇所）

### 2. サービスファイルのコピー

```bash
sudo cp cryptotrader.service /etc/systemd/system/
```

### 3. サービスの有効化と起動

```bash
# systemd設定をリロード
sudo systemctl daemon-reload

# サービス有効化（起動時に自動実行）
sudo systemctl enable cryptotrader

# サービス起動
sudo systemctl start cryptotrader
```

## 管理コマンド

### サービスの状態確認

```bash
sudo systemctl status cryptotrader
```

### サービスの停止

```bash
sudo systemctl stop cryptotrader
```

### サービスの再起動

```bash
sudo systemctl restart cryptotrader
```

### ログ確認

```bash
# リアルタイムログ
sudo journalctl -u cryptotrader -f

# 最新100行
sudo journalctl -u cryptotrader -n 100

# 特定期間のログ
sudo journalctl -u cryptotrader --since "2025-01-01" --until "2025-01-31"
```

### サービスの無効化

```bash
sudo systemctl disable cryptotrader
```

## トラブルシューティング

### サービスが起動しない

1. パスの確認
```bash
# サービスファイルの確認
cat /etc/systemd/system/cryptotrader.service

# Pythonパスの確認
which python3
```

2. 権限の確認
```bash
# 実行権限があるか
ls -l /path/to/Bitcoiner/main_trader.py

# 必要に応じて実行権限付与
chmod +x /path/to/Bitcoiner/main_trader.py
```

3. ログの確認
```bash
# systemdログ
sudo journalctl -u cryptotrader -xe

# アプリケーションログ
tail -f /path/to/Bitcoiner/logs/main_trader.log
```

### 自動再起動の設定

サービスファイルに以下の設定があります:
- `Restart=on-failure` - 異常終了時のみ再起動
- `RestartSec=30` - 30秒待機してから再起動

より頻繁に再起動したい場合:
```ini
Restart=always
RestartSec=10
```

## リソース制限

デフォルトの制限:
- メモリ: 1GB
- CPU: 50%

変更する場合:
```ini
MemoryLimit=2G
CPUQuota=75%
```

## セキュリティ設定

現在の設定:
- `PrivateTmp=true` - 独立した/tmpディレクトリ
- `NoNewPrivileges=true` - 権限昇格を禁止

より厳格な設定:
```ini
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/path/to/Bitcoiner/database /path/to/Bitcoiner/logs
```

## VPS起動時の自動実行

`systemctl enable cryptotrader`を実行済みであれば、VPS再起動時に自動的にサービスが起動します。

確認:
```bash
# 有効化されているか確認
systemctl is-enabled cryptotrader
# → enabled なら自動起動ON
```
