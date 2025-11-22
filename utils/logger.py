"""ロギング設定モジュール"""

import logging
import re
import os
import sys
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler, RotatingFileHandler
from typing import Optional, List


class SecretFilter(logging.Filter):
    """ログからAPIキーや機密情報をマスクするフィルター"""

    # マスク対象のパターン
    PATTERNS = [
        # API キー（英数字20文字以上）
        (r'([A-Za-z0-9]{20,})', r'***MASKED***'),
        # Telegram Bot Token（数字:英数字形式）
        (r'(\d{8,}:[A-Za-z0-9_-]{30,})', r'***BOT_TOKEN***'),
        # 環境変数名で検出
        (r'(BITFLYER_API_KEY\s*[=:]\s*)([^\s"\']+)', r'\1***MASKED***'),
        (r'(BITFLYER_API_SECRET\s*[=:]\s*)([^\s"\']+)', r'\1***MASKED***'),
        (r'(TELEGRAM_BOT_TOKEN\s*[=:]\s*)([^\s"\']+)', r'\1***MASKED***'),
    ]

    def __init__(self, additional_secrets: List[str] = None):
        """
        Args:
            additional_secrets: 追加でマスクする文字列のリスト
        """
        super().__init__()
        self.additional_secrets = additional_secrets or []

        # 環境変数から機密値を取得
        self._load_secrets_from_env()

    def _load_secrets_from_env(self):
        """環境変数から機密値を読み込み"""
        secret_env_vars = [
            'BITFLYER_API_KEY',
            'BITFLYER_API_SECRET',
            'TELEGRAM_BOT_TOKEN',
            'TELEGRAM_CHAT_ID'
        ]

        for var in secret_env_vars:
            value = os.environ.get(var)
            if value and len(value) > 8:
                self.additional_secrets.append(value)

    def filter(self, record: logging.LogRecord) -> bool:
        """ログレコードをフィルタリング"""
        if hasattr(record, 'msg') and record.msg:
            record.msg = self._mask_secrets(str(record.msg))

        if hasattr(record, 'args') and record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._mask_secrets(str(v)) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._mask_secrets(str(arg)) for arg in record.args)

        return True

    def _mask_secrets(self, text: str) -> str:
        """テキスト内の機密情報をマスク"""
        # 追加の機密値をマスク
        for secret in self.additional_secrets:
            if secret and len(secret) > 8:
                text = text.replace(secret, '***MASKED***')

        # パターンベースのマスク
        for pattern, replacement in self.PATTERNS:
            text = re.sub(pattern, replacement, text)

        return text


def setup_logger(
    name: str,
    log_file: str = "crypto_trader.log",
    level: int = logging.INFO,
    console: bool = True
) -> logging.Logger:
    """
    ロガーをセットアップ

    Args:
        name: ロガー名
        log_file: ログファイル名
        level: ログレベル（デフォルト: INFO）
        console: コンソール出力を有効にするか

    Returns:
        設定済みロガー
    """
    # ログディレクトリ作成
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / log_file

    # フォーマッター
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # ロガー取得（既存の場合は再利用）
    logger = logging.getLogger(name)

    # 既にハンドラーが設定されている場合はスキップ
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    # シークレットフィルター追加
    secret_filter = SecretFilter()
    logger.addFilter(secret_filter)

    # ファイルハンドラー（サイズベースのローテーション）
    # 10MBごとにローテート、最大30ファイル保持
    file_handler = RotatingFileHandler(
        filename=log_path,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=30,  # 30ファイル保持（最大300MB）
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    file_handler.addFilter(secret_filter)
    logger.addHandler(file_handler)

    # コンソールハンドラー（オプション）
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        logger.addHandler(console_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    既存のロガーを取得（存在しない場合は新規作成）

    Args:
        name: ロガー名

    Returns:
        ロガーインスタンス
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        # ハンドラーがない場合は自動セットアップ
        return setup_logger(name)
    return logger


# デフォルトロガーのセットアップ
def init_default_loggers():
    """デフォルトロガーを初期化"""
    # メインロガー
    setup_logger('crypto_trader', 'crypto_trader.log', level=logging.INFO)

    # データ収集ロガー
    setup_logger('data_collector', 'data_collector.log', level=logging.INFO)

    # 取引ロガー
    setup_logger('trading', 'trading.log', level=logging.INFO)

    # MLロガー
    setup_logger('ml_engine', 'ml_engine.log', level=logging.INFO)

    # エラーロガー（エラーのみ）
    setup_logger('errors', 'errors.log', level=logging.ERROR)


# システム起動時に初期化
if __name__ != "__main__":
    init_default_loggers()
