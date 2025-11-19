"""Binance API接続モジュール"""

import ccxt
import logging
import time
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
from dotenv import load_dotenv

# 環境変数読み込み
load_dotenv()

logger = logging.getLogger(__name__)


class BinanceDataCollector:
    """Binance取引所のデータ取得クラス"""

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, testnet: bool = False):
        """
        初期化

        Args:
            api_key: BinanceAPIキー（Noneの場合は環境変数から読み込み）
            api_secret: Binanceシークレット（Noneの場合は環境変数から読み込み）
            testnet: テストネット使用フラグ
        """
        # API認証情報
        self.api_key = api_key or os.getenv('BINANCE_API_KEY')
        self.api_secret = api_secret or os.getenv('BINANCE_API_SECRET')

        # Binance取引所初期化
        config = {
            'enableRateLimit': True,  # レート制限を自動管理
            'rateLimit': 1200,  # 1.2秒間隔
        }

        if self.api_key and self.api_secret:
            config['apiKey'] = self.api_key
            config['secret'] = self.api_secret

        if testnet:
            config['urls'] = {
                'api': 'https://testnet.binance.vision/api',
            }

        self.exchange = ccxt.binance(config)
        logger.info(f"Binance接続初期化完了 (testnet={testnet})")

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = '1m',
        since: Optional[int] = None,
        limit: int = 1000
    ) -> pd.DataFrame:
        """
        ローソク足データを取得

        Args:
            symbol: 通貨ペア（例: 'BTC/USDT'）
            timeframe: 時間足（'1m', '5m', '1h', '1d'など）
            since: 開始時刻（Unixタイムスタンプ、ミリ秒）
            limit: 取得件数（最大1000）

        Returns:
            OHLCVデータフレーム
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)

            if not ohlcv:
                logger.warning(f"データなし: {symbol} {timeframe}")
                return pd.DataFrame()

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            # タイムスタンプをUnix秒に変換（DBと整合性を保つ）
            df['timestamp'] = (df['timestamp'] / 1000).astype(int)

            logger.debug(f"OHLCV取得: {symbol} {timeframe} ({len(df)}件)")
            return df

        except ccxt.NetworkError as e:
            logger.error(f"ネットワークエラー: {e}")
            raise
        except ccxt.ExchangeError as e:
            logger.error(f"取引所エラー: {e}")
            raise
        except Exception as e:
            logger.error(f"予期しないエラー: {e}")
            raise

    def fetch_ohlcv_bulk(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: Optional[datetime] = None,
        batch_size: int = 1000
    ) -> pd.DataFrame:
        """
        過去データを大量取得（複数回のAPIコール）

        Args:
            symbol: 通貨ペア
            timeframe: 時間足
            start_date: 開始日時
            end_date: 終了日時（Noneの場合は現在時刻）
            batch_size: 1回あたりの取得件数

        Returns:
            統合されたOHLCVデータフレーム
        """
        if end_date is None:
            end_date = datetime.now()

        logger.info(f"大量データ取得開始: {symbol} {timeframe} ({start_date} ~ {end_date})")

        # タイムフレームをミリ秒に変換
        timeframe_ms = self._timeframe_to_ms(timeframe)

        all_data = []
        current_time = int(start_date.timestamp() * 1000)  # ミリ秒
        end_time = int(end_date.timestamp() * 1000)

        batch_count = 0

        while current_time < end_time:
            try:
                # データ取得
                df = self.fetch_ohlcv(symbol, timeframe, since=current_time, limit=batch_size)

                if df.empty:
                    break

                all_data.append(df)
                batch_count += 1

                # 次の開始時刻を設定（最後のタイムスタンプ + 1期間）
                last_timestamp = int(df['timestamp'].iloc[-1])
                current_time = (last_timestamp + 1) * 1000  # 秒からミリ秒に変換

                # 進捗ログ
                if batch_count % 10 == 0:
                    progress_date = datetime.fromtimestamp(last_timestamp)
                    logger.info(f"進捗: {batch_count}バッチ目、最新: {progress_date}")

                # レート制限対策（念のため）
                time.sleep(0.1)

            except Exception as e:
                logger.error(f"バッチ{batch_count}でエラー: {e}")
                # エラーが発生しても、それまでのデータは返す
                break

        if all_data:
            combined = pd.concat(all_data, ignore_index=True)
            # 重複削除
            combined = combined.drop_duplicates(subset=['timestamp']).reset_index(drop=True)
            logger.info(f"大量データ取得完了: {len(combined)}件 ({batch_count}バッチ)")
            return combined
        else:
            logger.warning("データ取得なし")
            return pd.DataFrame()

    def fetch_ticker(self, symbol: str) -> Dict:
        """
        現在価格を取得

        Args:
            symbol: 通貨ペア

        Returns:
            ティッカー情報
        """
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            logger.debug(f"ティッカー取得: {symbol} = {ticker['last']}")
            return ticker
        except Exception as e:
            logger.error(f"ティッカー取得エラー: {e}")
            raise

    def fetch_orderbook(self, symbol: str, limit: int = 5) -> Tuple[float, float, float, float]:
        """
        板情報を取得

        Args:
            symbol: 通貨ペア
            limit: 取得する板の深さ

        Returns:
            (bid_price, bid_volume, ask_price, ask_volume)
        """
        try:
            orderbook = self.exchange.fetch_order_book(symbol, limit=limit)

            bids = orderbook['bids']
            asks = orderbook['asks']

            if not bids or not asks:
                raise ValueError("板情報が空です")

            bid_price = bids[0][0]  # 最良買値
            bid_volume = bids[0][1]
            ask_price = asks[0][0]  # 最良売値
            ask_volume = asks[0][1]

            logger.debug(f"板情報取得: {symbol} Bid={bid_price} Ask={ask_price}")
            return bid_price, bid_volume, ask_price, ask_volume

        except Exception as e:
            logger.error(f"板情報取得エラー: {e}")
            raise

    def fetch_balance(self) -> Dict:
        """
        残高を取得（認証必要）

        Returns:
            残高情報
        """
        if not self.api_key or not self.api_secret:
            raise ValueError("API認証情報が設定されていません")

        try:
            balance = self.exchange.fetch_balance()
            logger.info("残高取得完了")
            return balance
        except Exception as e:
            logger.error(f"残高取得エラー: {e}")
            raise

    def _timeframe_to_ms(self, timeframe: str) -> int:
        """
        タイムフレームをミリ秒に変換

        Args:
            timeframe: タイムフレーム文字列（例: '1m', '1h', '1d'）

        Returns:
            ミリ秒
        """
        units = {
            'm': 60 * 1000,
            'h': 60 * 60 * 1000,
            'd': 24 * 60 * 60 * 1000,
            'w': 7 * 24 * 60 * 60 * 1000,
        }

        amount = int(timeframe[:-1])
        unit = timeframe[-1]

        if unit not in units:
            raise ValueError(f"不正なタイムフレーム: {timeframe}")

        return amount * units[unit]

    def test_connection(self) -> bool:
        """
        接続テスト

        Returns:
            成功した場合True
        """
        try:
            self.exchange.fetch_status()
            logger.info("Binance接続テスト成功")
            return True
        except Exception as e:
            logger.error(f"Binance接続テスト失敗: {e}")
            return False


# インスタンス生成用ヘルパー
def create_binance_collector(testnet: bool = False) -> BinanceDataCollector:
    """
    Binanceデータコレクターを作成

    Args:
        testnet: テストネット使用フラグ

    Returns:
        BinanceDataCollectorインスタンス
    """
    return BinanceDataCollector(testnet=testnet)
