"""Binance API接続テスト"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.collector.binance_api import BinanceDataCollector
from utils.logger import setup_logger

# ロガー設定
logger = setup_logger('test_binance', 'test_binance.log', console=True)


def test_binance_connection():
    """Binance接続テスト"""
    print("=" * 60)
    print("Binance API接続テスト（APIキー不要）")
    print("=" * 60)

    # データコレクター初期化
    collector = BinanceDataCollector()

    # 接続テスト
    print("\n[1] 接続テスト:")
    if collector.test_connection():
        print("  ✓ 接続成功")
    else:
        print("  ✗ 接続失敗")
        return

    # ティッカー取得テスト
    print("\n[2] ティッカー取得テスト:")
    try:
        ticker = collector.fetch_ticker('BTC/USDT')
        print(f"  ✓ BTC/USDT 価格: ${ticker['last']:,.2f}")
        print(f"  ✓ 24h変動: {ticker['percentage']:.2f}%")
    except Exception as e:
        print(f"  ✗ エラー: {e}")

    # OHLCV取得テスト
    print("\n[3] OHLCV取得テスト（最新100件）:")
    try:
        df = collector.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=100)
        print(f"  ✓ 取得件数: {len(df)}")
        print(f"  ✓ 最新終値: ${df.iloc[-1]['close']:,.2f}")
        print(f"  ✓ 最新出来高: {df.iloc[-1]['volume']:,.2f} BTC")

        # タイムスタンプ確認
        latest_time = datetime.fromtimestamp(df.iloc[-1]['timestamp'])
        print(f"  ✓ 最新時刻: {latest_time}")
    except Exception as e:
        print(f"  ✗ エラー: {e}")

    # 板情報取得テスト
    print("\n[4] 板情報取得テスト:")
    try:
        bid_price, bid_vol, ask_price, ask_vol = collector.fetch_orderbook('BTC/USDT')
        spread = ask_price - bid_price
        spread_pct = (spread / bid_price) * 100

        print(f"  ✓ 買値: ${bid_price:,.2f} (数量: {bid_vol:.4f})")
        print(f"  ✓ 売値: ${ask_price:,.2f} (数量: {ask_vol:.4f})")
        print(f"  ✓ スプレッド: ${spread:.2f} ({spread_pct:.4f}%)")
    except Exception as e:
        print(f"  ✗ エラー: {e}")

    # 大量データ取得テスト（過去7日間、1時間足）
    print("\n[5] 大量データ取得テスト（過去7日間、1h足）:")
    try:
        start = datetime.now() - timedelta(days=7)
        df_bulk = collector.fetch_ohlcv_bulk(
            symbol='ETH/USDT',
            timeframe='1h',
            start_date=start,
            batch_size=1000
        )
        print(f"  ✓ 取得件数: {len(df_bulk)}")
        print(f"  ✓ 期間: {datetime.fromtimestamp(df_bulk.iloc[0]['timestamp'])} ~ {datetime.fromtimestamp(df_bulk.iloc[-1]['timestamp'])}")
        print(f"  ✓ 最新価格: ${df_bulk.iloc[-1]['close']:,.2f}")
    except Exception as e:
        print(f"  ✗ エラー: {e}")

    print("\n" + "=" * 60)
    print("テスト完了！")
    print("=" * 60)


if __name__ == "__main__":
    test_binance_connection()
