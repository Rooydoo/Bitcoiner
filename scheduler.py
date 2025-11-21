"""タスクスケジューラー - 定期実行タスクの管理"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
import yaml
from pathlib import Path

from data.collector.data_orchestrator import create_orchestrator
from utils.logger import setup_logger

# ロガー設定
logger = setup_logger('scheduler', 'scheduler.log')

# グローバルスケジューラー
scheduler = BackgroundScheduler()


class CryptoTradingScheduler:
    """暗号資産取引システムのタスクスケジューラー"""

    def __init__(self, config_path: str = "config/config.yaml"):
        """
        初期化

        Args:
            config_path: 設定ファイルパス
        """
        # 設定読み込み
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        # データ収集オーケストレーター
        trading_pairs = [pair['symbol'] for pair in self.config['trading_pairs']]
        self.orchestrator = create_orchestrator(symbols=trading_pairs)

        # スケジューラー
        self.scheduler = BackgroundScheduler()

        logger.info("スケジューラー初期化完了")

    def start(self):
        """スケジューラー開始"""
        logger.info("=" * 60)
        logger.info("CryptoTrader スケジューラー起動")
        logger.info("=" * 60)

        # データ収集タスク
        self._schedule_data_collection()

        # レポート生成タスク
        self._schedule_reports()

        # メンテナンスタスク
        self._schedule_maintenance()

        # スケジューラー起動
        self.scheduler.start()
        logger.info("スケジューラー起動完了")

        # 登録されたジョブの一覧表示
        self._print_scheduled_jobs()

    def _schedule_data_collection(self):
        """データ収集タスクをスケジュール"""

        # 1分ごと: 1分足データ収集
        self.scheduler.add_job(
            func=lambda: self.orchestrator.collect_all_symbols(timeframes=['1m']),
            trigger=IntervalTrigger(minutes=1),
            id='collect_1m',
            name='1分足データ収集',
            max_instances=1
        )
        logger.info("スケジュール追加: 1分足データ収集（1分ごと）")

        # 5分ごと: 5分足データ収集
        self.scheduler.add_job(
            func=lambda: self.orchestrator.collect_all_symbols(timeframes=['5m']),
            trigger=IntervalTrigger(minutes=5),
            id='collect_5m',
            name='5分足データ収集',
            max_instances=1
        )
        logger.info("スケジュール追加: 5分足データ収集（5分ごと）")

        # 1時間ごと: 1時間足データ収集
        self.scheduler.add_job(
            func=lambda: self.orchestrator.collect_all_symbols(timeframes=['1h']),
            trigger=IntervalTrigger(hours=1),
            id='collect_1h',
            name='1時間足データ収集',
            max_instances=1
        )
        logger.info("スケジュール追加: 1時間足データ収集（1時間ごと）")

        # 1日1回: 日足データ収集（午前0時5分）
        self.scheduler.add_job(
            func=lambda: self.orchestrator.collect_all_symbols(timeframes=['1d']),
            trigger=CronTrigger(hour=0, minute=5),
            id='collect_daily',
            name='日足データ収集',
            max_instances=1
        )
        logger.info("スケジュール追加: 日足データ収集（毎日0:05）")

        # 板情報取得（1分ごと）
        self.scheduler.add_job(
            func=self.orchestrator.collect_orderbook_snapshot,
            trigger=IntervalTrigger(minutes=1),
            id='collect_orderbook',
            name='板情報収集',
            max_instances=1
        )
        logger.info("スケジュール追加: 板情報収集（1分ごと）")

    def _schedule_reports(self):
        """レポート生成タスクをスケジュール"""

        # 朝レポート（7:00）
        self.scheduler.add_job(
            func=self._generate_morning_report,
            trigger=CronTrigger(hour=7, minute=0),
            id='morning_report',
            name='朝レポート生成',
            max_instances=1
        )
        logger.info("スケジュール追加: 朝レポート（毎日7:00）")

        # 昼レポート（13:00）
        self.scheduler.add_job(
            func=self._generate_noon_report,
            trigger=CronTrigger(hour=13, minute=0),
            id='noon_report',
            name='昼レポート生成',
            max_instances=1
        )
        logger.info("スケジュール追加: 昼レポート（毎日13:00）")

        # 夜レポート（22:00）
        self.scheduler.add_job(
            func=self._generate_evening_report,
            trigger=CronTrigger(hour=22, minute=0),
            id='evening_report',
            name='夜レポート生成',
            max_instances=1
        )
        logger.info("スケジュール追加: 夜レポート（毎日22:00）")

    def _schedule_maintenance(self):
        """メンテナンスタスクをスケジュール"""

        # データベースVACUUM（毎週日曜深夜2時）
        self.scheduler.add_job(
            func=self._vacuum_databases,
            trigger=CronTrigger(day_of_week='sun', hour=2, minute=0),
            id='vacuum_db',
            name='DB最適化',
            max_instances=1
        )
        logger.info("スケジュール追加: DB最適化（毎週日曜2:00）")

        # MLモデル再学習（毎週日曜深夜3時）
        self.scheduler.add_job(
            func=self._retrain_models,
            trigger=CronTrigger(day_of_week='sun', hour=3, minute=0),
            id='retrain_models',
            name='MLモデル再学習',
            max_instances=1
        )
        logger.info("スケジュール追加: MLモデル再学習（毎週日曜3:00）")

    # ========== タスク実装 ==========

    def _generate_morning_report(self):
        """朝レポート生成"""
        logger.info("=" * 60)
        logger.info("朝レポート生成開始")
        logger.info("=" * 60)

        # TODO: レポート生成ロジック実装（Phase 4）
        summary = self.orchestrator.get_data_summary()
        logger.info(f"データ統計: {summary}")

        logger.info("朝レポート生成完了")

    def _generate_noon_report(self):
        """昼レポート生成"""
        logger.info("=" * 60)
        logger.info("昼レポート生成開始")
        logger.info("=" * 60)

        # TODO: レポート生成ロジック実装（Phase 4）
        summary = self.orchestrator.get_data_summary()
        logger.info(f"データ統計: {summary}")

        logger.info("昼レポート生成完了")

    def _generate_evening_report(self):
        """夜レポート生成"""
        logger.info("=" * 60)
        logger.info("夜レポート生成開始")
        logger.info("=" * 60)

        # TODO: レポート生成ロジック実装（Phase 4）
        summary = self.orchestrator.get_data_summary()
        logger.info(f"データ統計: {summary}")

        logger.info("夜レポート生成完了")

    def _vacuum_databases(self):
        """データベース最適化"""
        logger.info("=" * 60)
        logger.info("データベース最適化開始")
        logger.info("=" * 60)

        from data.storage.sqlite_manager import get_db_manager
        db = get_db_manager()

        sizes_before = db.get_database_sizes()
        logger.info(f"最適化前サイズ: {sizes_before}")

        db.vacuum_databases()

        sizes_after = db.get_database_sizes()
        logger.info(f"最適化後サイズ: {sizes_after}")

        logger.info("データベース最適化完了")

    def _retrain_models(self):
        """MLモデル再学習"""
        logger.info("=" * 60)
        logger.info("MLモデル再学習開始")
        logger.info("=" * 60)

        # TODO: MLモデル再学習ロジック実装（Phase 2）
        logger.info("MLモデル再学習はPhase 2で実装予定")

        logger.info("MLモデル再学習完了")

    def _print_scheduled_jobs(self):
        """スケジュールされたジョブの一覧表示"""
        logger.info("\n" + "=" * 60)
        logger.info("スケジュール一覧:")
        logger.info("=" * 60)

        jobs = self.scheduler.get_jobs()
        for job in jobs:
            logger.info(f"  - {job.name} (次回実行: {job.next_run_time})")

        logger.info("=" * 60 + "\n")

    def stop(self):
        """スケジューラー停止"""
        logger.info("スケジューラー停止中...")
        self.scheduler.shutdown()
        logger.info("スケジューラー停止完了")


# メイン実行
def main():
    """メイン関数"""
    scheduler_instance = CryptoTradingScheduler()
    scheduler_instance.start()

    # スケジューラーを稼働し続ける
    try:
        import time
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("終了シグナル受信")
        scheduler_instance.stop()


if __name__ == "__main__":
    main()
