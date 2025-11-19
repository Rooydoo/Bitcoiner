"""bitFlyer API接続モジュール"""

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


class BitflyerDataCollector:
    """bitFlyer取引所のデータ取得クラス"""

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        """
        初期化

        Args:
            api_key: bitFlyer APIキー（Noneの場合は環境変数から読み込み）
            api_secret: bitFlyerシークレット（Noneの場合は環境変数から読み込み）
        """
        # API認証情報
        self.api_key = api_key or os.getenv('BITFLYER_API_KEY')
        self.api_secret = api_secret or os.getenv('BITFLYER_API_SECRET')

        # bitFlyer取引所初期化
        config = {
            'enableRateLimit': True,  # レート制限を自動管理
            'rateLimit': 500,  # 0.5秒間隔（bitFlyerは制限が厳しい）
        }

        if self.api_key and self.api_secret:
            config['apiKey'] = self.api_key
            config['secret'] = self.api_secret

        self.exchange = ccxt.bitflyer(config)
        logger.info("bitFlyer接続初期化完了")

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = '1m',
        since: Optional[int] = None,
        limit: int = 500  # bitFlyerは500が上限
    ) -> pd.DataFrame:
        """
        ローソク足データを取得

        注意: bitFlyerはfetchOHLCV()未サポートのため、fetch_trades()からOHLCVを構築

        Args:
            symbol: 通貨ペア（例: 'BTC/JPY'）
            timeframe: 時間足（'1m', '5m', '1h', '1d'など）
            since: 開始時刻（Unixタイムスタンプ、ミリ秒）
            limit: 取得件数（最大500）

        Returns:
            OHLCVデータフレーム
        """
        try:
            # bitFlyerのlimit制限
            if limit > 500:
                logger.warning(f"bitFlyerのlimit上限は500です。{limit}を500に調整します")
                limit = 500

            # bitFlyerはfetchOHLCV未サポート -> fetch_trades()からOHLCVを構築
            logger.info(f"fetch_trades()から{timeframe}のOHLCVを構築します")

            # 約定履歴を取得
            trades = self.exchange.fetch_trades(symbol, since=since, limit=1000)

            if not trades:
                logger.warning(f"約定データなし: {symbol}")
                return pd.DataFrame()

            # 約定データをDataFrameに変換
            trades_df = pd.DataFrame([
                {
                    'timestamp': t['timestamp'],
                    'price': t['price'],
                    'amount': t['amount']
                }
                for t in trades
            ])

            # タイムスタンプを秒単位に変換
            trades_df['timestamp'] = pd.to_datetime(trades_df['timestamp'], unit='ms')

            # タイムフレームに応じてリサンプリング
            timeframe_map = {
                '1m': '1T',
                '5m': '5T',
                '15m': '15T',
                '1h': '1H',
                '4h': '4H',
                '1d': '1D'
            }

            resample_freq = timeframe_map.get(timeframe, '1T')

            # OHLCVを構築
            trades_df.set_index('timestamp', inplace=True)
            ohlcv_df = trades_df['price'].resample(resample_freq).ohlc()
            ohlcv_df['volume'] = trades_df['amount'].resample(resample_freq).sum()

            # NaNを前方埋め
            ohlcv_df = ohlcv_df.ffill().dropna()

            # インデックスをリセット
            ohlcv_df.reset_index(inplace=True)

            # limit件数に調整
            if len(ohlcv_df) > limit:
                ohlcv_df = ohlcv_df.tail(limit)

            # カラム順を整理
            df = ohlcv_df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()

            # タイムスタンプをdatetimeオブジェクトからUnix秒に変換
            df['timestamp'] = df['timestamp'].astype(int) // 10**9

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
        batch_size: int = 500
    ) -> pd.DataFrame:
        """
        過去データを大量取得（複数回のAPIコール）

        Args:
            symbol: 通貨ペア
            timeframe: 時間足
            start_date: 開始日時
            end_date: 終了日時（Noneの場合は現在時刻）
            batch_size: 1回あたりの取得件数（bitFlyerは最大500）

        Returns:
            統合されたOHLCVデータフレーム
        """
        if end_date is None:
            end_date = datetime.now()

        # bitFlyerの制限
        if batch_size > 500:
            batch_size = 500

        logger.info(f"大量データ取得開始: {symbol} {timeframe} ({start_date} ~ {end_date})")

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

                # レート制限対策（bitFlyerは厳しいので長めに待機）
                time.sleep(0.5)

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

    def test_connection(self) -> bool:
        """
        接続テスト

        Returns:
            成功した場合True
        """
        try:
            # bitFlyerはfetch_statusをサポートしていないので、tickerで代用
            self.fetch_ticker('BTC/JPY')
            logger.info("bitFlyer接続テスト成功")
            return True
        except Exception as e:
            logger.error(f"bitFlyer接続テスト失敗: {e}")
            return False


# インスタンス生成用ヘルパー
def create_bitflyer_collector() -> BitflyerDataCollector:
    """
    bitFlyerデータコレクターを作成

    Returns:
        BitflyerDataCollectorインスタンス
    """
    return BitflyerDataCollector()
