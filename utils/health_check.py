"""健全性チェック - システムの正常動作を監視

API接続、データベース、リソース使用率などを定期的にチェック
"""

import logging
import sys
import psutil
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import sqlite3

logger = logging.getLogger(__name__)


class HealthChecker:
    """健全性チェッククラス"""

    def __init__(
        self,
        db_dir: str = "database",
        max_memory_pct: float = 80.0,
        max_cpu_pct: float = 90.0
    ):
        """
        Args:
            db_dir: データベースディレクトリ
            max_memory_pct: メモリ使用率の警告閾値（%）
            max_cpu_pct: CPU使用率の警告閾値（%）
        """
        self.db_dir = Path(db_dir)
        self.max_memory_pct = max_memory_pct
        self.max_cpu_pct = max_cpu_pct
        self.issues: List[str] = []
        self.warnings: List[str] = []

    def run_all_checks(self) -> Tuple[bool, List[str], List[str]]:
        """
        全ての健全性チェックを実行

        Returns:
            (正常フラグ, 問題リスト, 警告リスト)
        """
        self.issues = []
        self.warnings = []

        # 各チェック実行
        self._check_database()
        self._check_disk_space()
        self._check_memory()
        self._check_cpu()
        self._check_directories()

        is_healthy = len(self.issues) == 0
        return is_healthy, self.issues, self.warnings

    def _check_database(self):
        """データベースの健全性チェック"""
        db_files = {
            'price_data.db': 'price data database',
            'trades.db': 'trades database',
            'ml_models.db': 'ML models database'
        }

        for db_file, description in db_files.items():
            db_path = self.db_dir / db_file

            # ファイル存在確認
            if not db_path.exists():
                self.warnings.append(f"{description} ({db_file}) が見つかりません（初回起動時は正常）")
                continue

            # ファイルサイズ確認
            size_mb = db_path.stat().st_size / (1024 * 1024)
            if size_mb > 1000:  # 1GB超
                self.warnings.append(f"{description} のサイズが大きいです: {size_mb:.1f}MB")

            # SQLite整合性チェック
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check")
                result = cursor.fetchone()
                conn.close()

                if result[0] != 'ok':
                    self.issues.append(f"{description} に整合性エラーがあります: {result[0]}")
            except Exception as e:
                self.issues.append(f"{description} のチェック失敗: {e}")

    def _check_disk_space(self):
        """ディスク空き容量チェック"""
        try:
            disk = psutil.disk_usage('.')
            free_gb = disk.free / (1024 ** 3)
            used_pct = disk.percent

            if free_gb < 1.0:  # 1GB未満
                self.issues.append(f"ディスク空き容量が不足しています: {free_gb:.2f}GB")
            elif free_gb < 5.0:  # 5GB未満
                self.warnings.append(f"ディスク空き容量が少なくなっています: {free_gb:.2f}GB")

            if used_pct > 95:
                self.issues.append(f"ディスク使用率が高すぎます: {used_pct:.1f}%")
            elif used_pct > 85:
                self.warnings.append(f"ディスク使用率が高くなっています: {used_pct:.1f}%")

        except Exception as e:
            self.warnings.append(f"ディスク容量チェック失敗: {e}")

    def _check_memory(self):
        """メモリ使用率チェック"""
        try:
            memory = psutil.virtual_memory()
            used_pct = memory.percent
            available_mb = memory.available / (1024 * 1024)

            if used_pct > self.max_memory_pct:
                self.issues.append(f"メモリ使用率が高すぎます: {used_pct:.1f}%")
            elif used_pct > self.max_memory_pct - 10:
                self.warnings.append(f"メモリ使用率が上昇しています: {used_pct:.1f}%")

            if available_mb < 500:  # 500MB未満
                self.warnings.append(f"利用可能メモリが少なくなっています: {available_mb:.1f}MB")

        except Exception as e:
            self.warnings.append(f"メモリチェック失敗: {e}")

    def _check_cpu(self):
        """CPU使用率チェック"""
        try:
            # 1秒間のCPU使用率を取得
            cpu_pct = psutil.cpu_percent(interval=1)

            if cpu_pct > self.max_cpu_pct:
                self.issues.append(f"CPU使用率が高すぎます: {cpu_pct:.1f}%")
            elif cpu_pct > self.max_cpu_pct - 10:
                self.warnings.append(f"CPU使用率が上昇しています: {cpu_pct:.1f}%")

        except Exception as e:
            self.warnings.append(f"CPUチェック失敗: {e}")

    def _check_directories(self):
        """必要なディレクトリの存在確認"""
        required_dirs = [
            'database',
            'logs',
            'ml_models',
            'config'
        ]

        for dir_name in required_dirs:
            dir_path = Path(dir_name)
            if not dir_path.exists():
                self.issues.append(f"必須ディレクトリが見つかりません: {dir_name}/")
            elif not dir_path.is_dir():
                self.issues.append(f"{dir_name} はディレクトリではありません")

    def check_api_connectivity(self, exchange=None) -> bool:
        """
        API接続性チェック（オプション）

        Args:
            exchange: ccxt exchangeインスタンス

        Returns:
            接続成功フラグ
        """
        if not exchange:
            return True  # exchangeが提供されない場合はスキップ

        try:
            # 簡単なAPIコール（ティッカー取得）
            exchange.fetch_ticker('BTC/JPY')
            logger.info("API接続性チェック: 正常")
            return True
        except Exception as e:
            self.issues.append(f"API接続に失敗しました: {e}")
            logger.error(f"API接続性チェック: 失敗 - {e}")
            return False

    def get_system_status(self) -> Dict:
        """
        現在のシステム状態を取得

        Returns:
            システム状態の辞書
        """
        try:
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('.')
            cpu_pct = psutil.cpu_percent(interval=0.5)

            return {
                'timestamp': datetime.now().isoformat(),
                'memory': {
                    'used_pct': memory.percent,
                    'available_mb': memory.available / (1024 * 1024),
                    'total_mb': memory.total / (1024 * 1024)
                },
                'disk': {
                    'used_pct': disk.percent,
                    'free_gb': disk.free / (1024 ** 3),
                    'total_gb': disk.total / (1024 ** 3)
                },
                'cpu': {
                    'used_pct': cpu_pct
                }
            }
        except Exception as e:
            logger.error(f"システム状態取得失敗: {e}")
            return {}

    def print_health_report(self, is_healthy: bool, issues: List[str], warnings: List[str]):
        """
        健全性チェック結果を表示

        Args:
            is_healthy: 正常フラグ
            issues: 問題リスト
            warnings: 警告リスト
        """
        print("\n" + "=" * 60)
        print("システム健全性チェック結果")
        print("=" * 60)

        # システム状態
        status = self.get_system_status()
        if status:
            print("\n📊 システム状態:")
            print(f"  メモリ: {status['memory']['used_pct']:.1f}% 使用 "
                  f"({status['memory']['available_mb']:.0f}MB 利用可能)")
            print(f"  ディスク: {status['disk']['used_pct']:.1f}% 使用 "
                  f"({status['disk']['free_gb']:.1f}GB 空き)")
            print(f"  CPU: {status['cpu']['used_pct']:.1f}% 使用")

        if issues:
            print("\n❌ 問題:")
            for i, issue in enumerate(issues, 1):
                print(f"  {i}. {issue}")

        if warnings:
            print("\n⚠️  警告:")
            for i, warning in enumerate(warnings, 1):
                print(f"  {i}. {warning}")

        if is_healthy:
            if not warnings:
                print("\n✅ システムは正常に動作しています")
            else:
                print("\n✅ システムは動作していますが、警告があります")
        else:
            print("\n❌ システムに問題があります")

        print("=" * 60 + "\n")


def run_health_check(notify_func: Optional[callable] = None) -> bool:
    """
    健全性チェックを実行（簡易インターフェース）

    Args:
        notify_func: 問題検出時に呼び出す通知関数

    Returns:
        正常フラグ
    """
    checker = HealthChecker()
    is_healthy, issues, warnings = checker.run_all_checks()
    checker.print_health_report(is_healthy, issues, warnings)

    # 問題がある場合は通知
    if not is_healthy and notify_func:
        notify_func("\n".join([f"❌ {issue}" for issue in issues]))

    return is_healthy


# テスト実行
if __name__ == "__main__":
    run_health_check()
