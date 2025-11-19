"""データベースバックアップスクリプト

SQLiteデータベースをバックアップし、古いバックアップを自動削除
"""

import os
import shutil
import sys
from pathlib import Path
from datetime import datetime, timedelta
import logging

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger import setup_logger

logger = setup_logger('backup', 'backup.log', console=True)


class DatabaseBackup:
    """データベースバックアップクラス"""

    def __init__(
        self,
        db_dir: str = "database",
        backup_dir: str = "backups",
        retention_days: int = 30
    ):
        """
        Args:
            db_dir: データベースディレクトリ
            backup_dir: バックアップ先ディレクトリ
            retention_days: バックアップ保持日数
        """
        self.db_dir = Path(db_dir)
        self.backup_dir = Path(backup_dir)
        self.retention_days = retention_days

        # バックアップディレクトリ作成
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"バックアップ設定: {db_dir} → {backup_dir} (保持: {retention_days}日)")

    def backup_all_databases(self) -> dict:
        """
        全データベースをバックアップ

        Returns:
            バックアップ結果の辞書
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_results = {}

        logger.info("=" * 60)
        logger.info("データベースバックアップ開始")
        logger.info("=" * 60)

        # .dbファイルを全て検索
        db_files = list(self.db_dir.glob("*.db"))

        if not db_files:
            logger.warning(f"バックアップ対象のDBファイルが見つかりません: {self.db_dir}")
            return {}

        for db_file in db_files:
            try:
                # バックアップファイル名
                backup_filename = f"{db_file.stem}_{timestamp}.db"
                backup_path = self.backup_dir / backup_filename

                # コピー
                shutil.copy2(db_file, backup_path)

                # ファイルサイズ確認
                size_mb = backup_path.stat().st_size / (1024 * 1024)

                logger.info(f"✓ {db_file.name} → {backup_filename} ({size_mb:.2f} MB)")

                backup_results[db_file.name] = {
                    'status': 'success',
                    'backup_path': str(backup_path),
                    'size_mb': size_mb
                }

            except Exception as e:
                logger.error(f"✗ {db_file.name} バックアップ失敗: {e}")
                backup_results[db_file.name] = {
                    'status': 'failed',
                    'error': str(e)
                }

        logger.info("=" * 60)
        logger.info(f"バックアップ完了: {len(db_files)}件")
        logger.info("=" * 60 + "\n")

        return backup_results

    def cleanup_old_backups(self):
        """
        古いバックアップを削除

        保持期間を超えたバックアップファイルを削除
        """
        cutoff_date = datetime.now() - timedelta(days=self.retention_days)

        logger.info(f"古いバックアップ削除中（{self.retention_days}日以前）...")

        deleted_count = 0
        total_size_mb = 0.0

        # .dbファイルを全て検索
        backup_files = list(self.backup_dir.glob("*.db"))

        for backup_file in backup_files:
            # ファイル作成日時取得
            file_mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)

            if file_mtime < cutoff_date:
                size_mb = backup_file.stat().st_size / (1024 * 1024)

                try:
                    backup_file.unlink()
                    logger.info(f"  削除: {backup_file.name} ({size_mb:.2f} MB)")
                    deleted_count += 1
                    total_size_mb += size_mb

                except Exception as e:
                    logger.error(f"  削除失敗: {backup_file.name} - {e}")

        if deleted_count > 0:
            logger.info(f"✓ {deleted_count}件のバックアップを削除 (合計 {total_size_mb:.2f} MB)\n")
        else:
            logger.info("削除対象のバックアップなし\n")

    def get_backup_summary(self) -> dict:
        """
        バックアップサマリー取得

        Returns:
            バックアップ情報の辞書
        """
        backup_files = list(self.backup_dir.glob("*.db"))

        if not backup_files:
            return {
                'count': 0,
                'total_size_mb': 0.0,
                'oldest': None,
                'newest': None
            }

        # サイズ合計
        total_size = sum(f.stat().st_size for f in backup_files)
        total_size_mb = total_size / (1024 * 1024)

        # 最古・最新
        sorted_files = sorted(backup_files, key=lambda f: f.stat().st_mtime)
        oldest = datetime.fromtimestamp(sorted_files[0].stat().st_mtime)
        newest = datetime.fromtimestamp(sorted_files[-1].stat().st_mtime)

        return {
            'count': len(backup_files),
            'total_size_mb': total_size_mb,
            'oldest': oldest.strftime('%Y-%m-%d %H:%M:%S'),
            'newest': newest.strftime('%Y-%m-%d %H:%M:%S')
        }

    def restore_database(self, backup_file: str, target_db: str):
        """
        データベースを復元

        Args:
            backup_file: バックアップファイル名
            target_db: 復元先DBファイル名
        """
        backup_path = self.backup_dir / backup_file
        target_path = self.db_dir / target_db

        if not backup_path.exists():
            logger.error(f"バックアップファイルが見つかりません: {backup_path}")
            return False

        try:
            # 現在のDBをバックアップ（上書き前）
            if target_path.exists():
                safety_backup = target_path.with_suffix(f'.db.before_restore_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
                shutil.copy2(target_path, safety_backup)
                logger.info(f"既存DBを保存: {safety_backup.name}")

            # 復元
            shutil.copy2(backup_path, target_path)
            logger.info(f"✓ 復元完了: {backup_file} → {target_db}")
            return True

        except Exception as e:
            logger.error(f"✗ 復元失敗: {e}")
            return False


def main():
    """メインエントリーポイント"""
    import argparse

    parser = argparse.ArgumentParser(description='CryptoTrader データベースバックアップ')
    parser.add_argument(
        '--action',
        choices=['backup', 'cleanup', 'summary', 'restore'],
        default='backup',
        help='実行アクション'
    )
    parser.add_argument(
        '--retention',
        type=int,
        default=30,
        help='バックアップ保持日数（デフォルト: 30日）'
    )
    parser.add_argument(
        '--backup-file',
        type=str,
        help='復元するバックアップファイル名'
    )
    parser.add_argument(
        '--target-db',
        type=str,
        help='復元先DBファイル名'
    )

    args = parser.parse_args()

    # バックアップマネージャー初期化
    backup_manager = DatabaseBackup(retention_days=args.retention)

    if args.action == 'backup':
        # バックアップ実行
        results = backup_manager.backup_all_databases()

        # 古いバックアップ削除
        backup_manager.cleanup_old_backups()

        # サマリー表示
        summary = backup_manager.get_backup_summary()
        logger.info("【バックアップサマリー】")
        logger.info(f"  バックアップ数: {summary['count']}件")
        logger.info(f"  合計サイズ: {summary['total_size_mb']:.2f} MB")
        logger.info(f"  最古: {summary['oldest']}")
        logger.info(f"  最新: {summary['newest']}")

    elif args.action == 'cleanup':
        # クリーンアップのみ
        backup_manager.cleanup_old_backups()

    elif args.action == 'summary':
        # サマリー表示
        summary = backup_manager.get_backup_summary()
        print(f"\nバックアップ数: {summary['count']}件")
        print(f"合計サイズ: {summary['total_size_mb']:.2f} MB")
        print(f"最古: {summary['oldest']}")
        print(f"最新: {summary['newest']}\n")

    elif args.action == 'restore':
        # 復元
        if not args.backup_file or not args.target_db:
            logger.error("復元には --backup-file と --target-db が必要です")
            sys.exit(1)

        backup_manager.restore_database(args.backup_file, args.target_db)


if __name__ == "__main__":
    main()
