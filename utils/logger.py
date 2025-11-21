"""ロギング設定モジュール"""

import logging
import sys
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler, RotatingFileHandler
from typing import Optional


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
