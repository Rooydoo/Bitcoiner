"""環境変数バリデーション

起動時に.envの必須項目と形式をチェック
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from dotenv import load_dotenv

# 環境変数読み込み
load_dotenv()


class EnvValidator:
    """環境変数バリデータークラス"""

    def __init__(self, test_mode: bool = False):
        """
        Args:
            test_mode: テストモード（検証を緩和）
        """
        self.test_mode = test_mode
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate_all(self) -> Tuple[bool, List[str], List[str]]:
        """
        全ての環境変数を検証

        Returns:
            (検証成功, エラーリスト, 警告リスト)
        """
        self.errors = []
        self.warnings = []

        # .envファイルの存在確認
        env_path = Path('.env')
        if not env_path.exists():
            self.errors.append(".envファイルが見つかりません（config/.env.exampleからコピーしてください）")
            return False, self.errors, self.warnings

        # bitFlyer API検証（本番モードのみ必須）
        if not self.test_mode:
            self._validate_bitflyer_api()
        else:
            self.warnings.append("テストモード: bitFlyer API検証をスキップ")

        # Telegram検証（オプション）
        self._validate_telegram()

        # その他の設定検証
        self._validate_misc_config()

        is_valid = len(self.errors) == 0
        return is_valid, self.errors, self.warnings

    def _validate_bitflyer_api(self):
        """bitFlyer API認証情報の検証"""
        api_key = os.getenv('BITFLYER_API_KEY', '').strip()
        api_secret = os.getenv('BITFLYER_API_SECRET', '').strip()

        # APIキーの存在確認
        if not api_key:
            self.errors.append("BITFLYER_API_KEY が設定されていません（本番モード必須）")
        else:
            # APIキー形式チェック（英数字、最低16文字）
            if len(api_key) < 16:
                self.errors.append(f"BITFLYER_API_KEY の長さが不正です（{len(api_key)}文字、最低16文字必要）")
            elif not re.match(r'^[a-zA-Z0-9\-_]+$', api_key):
                self.errors.append("BITFLYER_API_KEY の形式が不正です（英数字とハイフン、アンダースコアのみ）")
            elif api_key == 'your_api_key_here':
                self.errors.append("BITFLYER_API_KEY がデフォルト値のままです（実際のキーを設定してください）")

        # APIシークレットの存在確認
        if not api_secret:
            self.errors.append("BITFLYER_API_SECRET が設定されていません（本番モード必須）")
        else:
            # APIシークレット形式チェック（英数字、最低16文字）
            if len(api_secret) < 16:
                self.errors.append(f"BITFLYER_API_SECRET の長さが不正です（{len(api_secret)}文字、最低16文字必要）")
            elif not re.match(r'^[a-zA-Z0-9\-_/+=]+$', api_secret):
                self.errors.append("BITFLYER_API_SECRET の形式が不正です（英数字と特殊文字のみ）")
            elif api_secret == 'your_api_secret_here':
                self.errors.append("BITFLYER_API_SECRET がデフォルト値のままです（実際のシークレットを設定してください）")

    def _validate_telegram(self):
        """Telegram設定の検証（オプション）"""
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
        chat_id = os.getenv('TELEGRAM_CHAT_ID', '').strip()

        if bot_token or chat_id:
            # 片方だけ設定されている場合は警告
            if bot_token and not chat_id:
                self.warnings.append("TELEGRAM_BOT_TOKEN は設定されていますが、TELEGRAM_CHAT_ID が設定されていません")
            elif chat_id and not bot_token:
                self.warnings.append("TELEGRAM_CHAT_ID は設定されていますが、TELEGRAM_BOT_TOKEN が設定されていません")

            # Botトークン形式チェック
            if bot_token:
                # Telegramトークンの一般的な形式: 数字:英数字（例: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11）
                if not re.match(r'^\d+:[a-zA-Z0-9_-]+$', bot_token):
                    self.errors.append("TELEGRAM_BOT_TOKEN の形式が不正です（形式: 数字:英数字）")
                elif bot_token == 'your_telegram_bot_token_here':
                    self.warnings.append("TELEGRAM_BOT_TOKEN がデフォルト値のままです")

            # Chat ID形式チェック
            if chat_id:
                # Chat IDは数字またはマイナス付き数字
                if not re.match(r'^-?\d+$', chat_id):
                    self.errors.append("TELEGRAM_CHAT_ID の形式が不正です（数字のみ）")
                elif chat_id == 'your_telegram_chat_id_here':
                    self.warnings.append("TELEGRAM_CHAT_ID がデフォルト値のままです")
        else:
            self.warnings.append("Telegram通知が無効です（TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 未設定）")

    def _validate_misc_config(self):
        """その他の設定検証"""
        # Streamlit認証（オプション）
        streamlit_user = os.getenv('STREAMLIT_USERNAME', '').strip()
        streamlit_pass = os.getenv('STREAMLIT_PASSWORD', '').strip()

        if streamlit_pass == 'changeme':
            self.warnings.append("STREAMLIT_PASSWORD がデフォルト値（changeme）のままです")

    def print_validation_result(self, is_valid: bool, errors: List[str], warnings: List[str]):
        """
        検証結果を表示

        Args:
            is_valid: 検証成功フラグ
            errors: エラーリスト
            warnings: 警告リスト
        """
        print("\n" + "=" * 60)
        print("環境変数検証結果")
        print("=" * 60)

        if errors:
            print("\n❌ エラー:")
            for i, error in enumerate(errors, 1):
                print(f"  {i}. {error}")

        if warnings:
            print("\n⚠️  警告:")
            for i, warning in enumerate(warnings, 1):
                print(f"  {i}. {warning}")

        if is_valid:
            if not warnings:
                print("\n✅ 全ての検証に合格しました")
            else:
                print("\n✅ 必須項目の検証に合格しました（警告あり）")
        else:
            print("\n❌ 検証に失敗しました")
            print("\n対処方法:")
            print("  1. .env ファイルを編集")
            print("  2. 必要なAPIキーを設定")
            print("  3. 再度起動")

        print("=" * 60 + "\n")


def validate_environment(test_mode: bool = False, exit_on_error: bool = True) -> bool:
    """
    環境変数を検証（簡易インターフェース）

    Args:
        test_mode: テストモード
        exit_on_error: エラー時に終了するか

    Returns:
        検証成功フラグ
    """
    validator = EnvValidator(test_mode=test_mode)
    is_valid, errors, warnings = validator.validate_all()
    validator.print_validation_result(is_valid, errors, warnings)

    if not is_valid and exit_on_error:
        print("環境変数の設定を修正してから再度起動してください。")
        sys.exit(1)

    return is_valid


# テスト実行
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='環境変数バリデーション')
    parser.add_argument('--test', action='store_true', help='テストモード')
    args = parser.parse_args()

    validate_environment(test_mode=args.test, exit_on_error=False)
