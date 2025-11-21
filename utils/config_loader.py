"""設定ファイル読み込みモジュール

YAMLと環境変数から設定を読み込む
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from dotenv import load_dotenv


class ConfigLoader:
    """設定ローダークラス"""

    def __init__(self, config_path: str = "config/config.yaml"):
        """
        Args:
            config_path: 設定ファイルパス
        """
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}

        # .envファイル読み込み
        env_path = Path(".env")
        if env_path.exists():
            load_dotenv(env_path)

        # YAML設定読み込み
        self._load_yaml_config()

        # 環境変数で上書き
        self._override_with_env()

    def _load_yaml_config(self):
        """YAML設定ファイル読み込み"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"設定ファイルが見つかりません: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f) or {}

    def _override_with_env(self):
        """環境変数で設定を上書き"""
        # bitFlyer API設定
        api_key = os.getenv('BITFLYER_API_KEY')
        api_secret = os.getenv('BITFLYER_API_SECRET')

        if api_key and api_secret:
            if 'exchange' not in self.config:
                self.config['exchange'] = {}
            self.config['exchange']['api_key'] = api_key
            self.config['exchange']['api_secret'] = api_secret

        # Telegram設定
        telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

        if telegram_token or telegram_chat_id:
            if 'telegram' not in self.config:
                self.config['telegram'] = {}
            if telegram_token:
                self.config['telegram']['bot_token'] = telegram_token
            if telegram_chat_id:
                self.config['telegram']['chat_id'] = telegram_chat_id

    def get(self, key: str, default: Any = None) -> Any:
        """
        設定値取得

        Args:
            key: 設定キー（ドット区切りで階層指定可能: 'exchange.name'）
            default: デフォルト値

        Returns:
            設定値
        """
        keys = key.split('.')
        value = self.config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default

            if value is None:
                return default

        return value

    def get_all(self) -> Dict[str, Any]:
        """
        全設定取得

        Returns:
            全設定の辞書
        """
        return self.config.copy()

    def __getitem__(self, key: str) -> Any:
        """辞書風アクセス"""
        return self.get(key)

    def __contains__(self, key: str) -> bool:
        """'key in config' をサポート"""
        return self.get(key) is not None
