"""データ収集オーケストレーター"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict
import pandas as pd
import time

from data.collector.bitflyer_api import BitflyerDataCollector
from data.storage.sqlite_manager import get_db_manager
from data.processor.indicators import TechnicalIndicators

logger = logging.getLogger(__name__)


class DataCollectionOrchestrator:
    """データ収集を統合管理するクラス"""

    def __init__(self, symbols: List[str] = None):
        """
        初期化

        Args:
            symbols: 取引ペアのリスト（例: ['BTC/JPY', 'ETH/JPY']）
        """
        self.symbols = symbols or ['BTC/JPY', 'ETH/JPY']
        self.collector = BitflyerDataCollector()
        self.db = get_db_manager()
        self.ti = TechnicalIndicators()

        logger.info(f"データ収集オーケストレーター初期化: {self.symbols}")

    def collect_and_store_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 100,
        calculate_indicators: bool = True
    ) -> int:
        """
        OHLCVデータを取得してDBに保存

        Args:
            symbol: 通貨ペア
            timeframe: 時間足
            limit: 取得件数
            calculate_indicators: 技術指標を計算するか

        Returns:
            保存された件数
        """
        try:
            # データ取得
            logger.info(f"データ取得開始: {symbol} {timeframe} (limit={limit})")
            df = self.collector.fetch_ohlcv(symbol, timeframe, limit=limit)

            if df.empty:
                logger.warning(f"データなし: {symbol} {timeframe}")
                return 0

            # 技術指標計算（オプション）
            if calculate_indicators and len(df) >= 75:  # SMA75に必要な最小データ数
                logger.debug(f"技術指標計算: {symbol} {timeframe}")
                df = self.ti.calculate_all(df)

            # DB保存
            self.db.insert_ohlcv(df, symbol, timeframe)
            logger.info(f"データ保存完了: {symbol} {timeframe} ({len(df)}件)")

            return len(df)

        except Exception as e:
            logger.error(f"データ収集エラー: {symbol} {timeframe} - {e}")
            return 0

    def collect_historical_data(
        self,
        symbol: str,
        timeframe: str,
        days: int = 730,  # 2年分
        batch_size: int = 500  # bitFlyerは500が上限
    ) -> int:
        """
        過去データを大量取得してDBに保存

        Args:
            symbol: 通貨ペア
            timeframe: 時間足
            days: 過去何日分取得するか
            batch_size: 1回あたりの取得件数

        Returns:
            保存された件数
        """
        try:
            start_date = datetime.now() - timedelta(days=days)
            logger.info(f"過去データ取得開始: {symbol} {timeframe} ({days}日分)")

            # 大量データ取得
            df = self.collector.fetch_ohlcv_bulk(
                symbol=symbol,
                timeframe=timeframe,
                start_date=start_date,
                batch_size=batch_size
            )

            if df.empty:
                logger.warning(f"過去データなし: {symbol} {timeframe}")
                return 0

            # チャンク分割して保存（メモリ効率のため）
            chunk_size = 10000
            total_saved = 0

            for i in range(0, len(df), chunk_size):
                chunk = df.iloc[i:i+chunk_size]
                self.db.insert_ohlcv(chunk, symbol, timeframe)
                total_saved += len(chunk)
                logger.info(f"進捗: {total_saved}/{len(df)}件保存")

            logger.info(f"過去データ保存完了: {symbol} {timeframe} ({total_saved}件)")
            return total_saved

        except Exception as e:
            logger.error(f"過去データ収集エラー: {symbol} {timeframe} - {e}")
            return 0

    def collect_all_symbols(self, timeframes: List[str] = None) -> Dict[str, int]:
        """
        全通貨ペアのデータを取得

        Args:
            timeframes: 時間足のリスト（Noneの場合はデフォルト）

        Returns:
            通貨ペア別の取得件数
        """
        if timeframes is None:
            timeframes = ['1m', '5m', '1h', '1d']

        results = {}

        for symbol in self.symbols:
            for timeframe in timeframes:
                key = f"{symbol}_{timeframe}"
                count = self.collect_and_store_ohlcv(symbol, timeframe, limit=100)
                results[key] = count

                # レート制限対策（bitFlyerは厳しい）
                time.sleep(0.5)

        logger.info(f"全通貨ペアデータ収集完了: {sum(results.values())}件")
        return results

    def collect_orderbook_snapshot(self) -> int:
        """
        全通貨ペアの板情報を取得して保存

        Returns:
            保存された件数
        """
        count = 0

        for symbol in self.symbols:
            try:
                bid_price, bid_vol, ask_price, ask_vol = self.collector.fetch_orderbook(symbol)
                spread = ask_price - bid_price

                # DB保存（orderbook INSERT）
                # TODO: DBにorderbook insert_orderbook メソッドを追加
                logger.info(f"板情報: {symbol} Bid={bid_price:.2f} Ask={ask_price:.2f} Spread={spread:.4f}")
                count += 1

                time.sleep(0.1)

            except Exception as e:
                logger.error(f"板情報取得エラー: {symbol} - {e}")

        return count

    def initialize_historical_data(self, days: int = 730):
        """
        初期データを取得（初回セットアップ用）

        Args:
            days: 過去何日分取得するか（デフォルト2年）
        """
        logger.info("=" * 60)
        logger.info(f"初期データ取得開始（過去{days}日分）")
        logger.info("=" * 60)

        # 主要な時間足のみ取得（1m足は容量大きいので除外）
        timeframes = ['1h', '1d']

        for symbol in self.symbols:
            for timeframe in timeframes:
                logger.info(f"\n処理中: {symbol} {timeframe}")
                count = self.collect_historical_data(symbol, timeframe, days=days)
                logger.info(f"完了: {symbol} {timeframe} ({count}件)")

                # レート制限対策
                time.sleep(1)

        logger.info("=" * 60)
        logger.info("初期データ取得完了")
        logger.info("=" * 60)

    def get_data_summary(self) -> Dict[str, any]:
        """
        データの統計情報を取得

        Returns:
            統計情報の辞書
        """
        summary = {
            'db_sizes': self.db.get_database_sizes(),
            'symbols': self.symbols,
            'timestamp': datetime.now().isoformat()
        }

        # 各通貨ペアのデータ件数
        for symbol in self.symbols:
            for timeframe in ['1h', '1d']:
                df = self.db.get_latest_ohlcv(symbol, timeframe, limit=1)
                if not df.empty:
                    latest_time = datetime.fromtimestamp(df.iloc[0]['timestamp'])
                    summary[f'{symbol}_{timeframe}_latest'] = latest_time.isoformat()

        return summary


# ヘルパー関数
def create_orchestrator(symbols: List[str] = None) -> DataCollectionOrchestrator:
    """
    データ収集オーケストレーターを作成

    Args:
        symbols: 通貨ペアリスト

    Returns:
        DataCollectionOrchestratorインスタンス
    """
    return DataCollectionOrchestrator(symbols=symbols)
