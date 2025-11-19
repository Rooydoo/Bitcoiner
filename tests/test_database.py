"""SQLiteマネージャーのテスト"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.storage.sqlite_manager import SQLiteManager
import pandas as pd
import time

def test_database_initialization():
    """データベース初期化のテスト"""
    print("=" * 60)
    print("SQLiteデータベース初期化テスト")
    print("=" * 60)

    # テスト用DBマネージャー
    db = SQLiteManager(db_dir="database_test")

    # データベースファイルの確認
    print("\n[1] データベースファイルの確認:")
    for name in ['price_data.db', 'trades.db', 'ml_models.db']:
        db_path = db.db_dir / name
        exists = "✓" if db_path.exists() else "✗"
        print(f"  {exists} {name}: {db_path}")

    # データベースサイズの確認
    print("\n[2] データベースサイズ:")
    sizes = db.get_database_sizes()
    for name, size in sizes.items():
        print(f"  {name}: {size} MB")

    # サンプルOHLCVデータの挿入
    print("\n[3] サンプルデータ挿入テスト:")

    # テストデータ作成
    now = int(time.time())
    test_data = pd.DataFrame({
        'timestamp': [now - 3600, now - 1800, now],
        'open': [50000, 50100, 50200],
        'high': [50200, 50300, 50400],
        'low': [49900, 50000, 50100],
        'close': [50100, 50200, 50300],
        'volume': [1000, 1100, 1200]
    })

    db.insert_ohlcv(test_data, symbol='BTC/USDT', timeframe='1h')
    print("  ✓ BTC/USDT 1h データ挿入完了 (3件)")

    # データ取得テスト
    print("\n[4] データ取得テスト:")
    retrieved = db.get_latest_ohlcv('BTC/USDT', '1h', limit=10)
    print(f"  ✓ 取得件数: {len(retrieved)}")
    print(f"  ✓ カラム: {list(retrieved.columns)}")

    if len(retrieved) > 0:
        print("\n  最新データ:")
        print(f"    Close: {retrieved.iloc[-1]['close']}")
        print(f"    Volume: {retrieved.iloc[-1]['volume']}")

    # テスト取引の挿入
    print("\n[5] 取引データ挿入テスト:")
    trade = {
        'symbol': 'BTC/USDT',
        'side': 'buy',
        'order_type': 'market',
        'price': 50300,
        'amount': 0.1,
        'cost': 5030,
        'fee': 5.03,
        'fee_currency': 'USDT',
        'timestamp': now,
        'order_id': 'TEST_ORDER_001'
    }

    trade_id = db.insert_trade(trade)
    print(f"  ✓ 取引記録 ID: {trade_id}")

    # ポジション作成テスト
    print("\n[6] ポジション作成テスト:")
    position = {
        'position_id': 'POS_TEST_001',
        'symbol': 'BTC/USDT',
        'side': 'long',
        'entry_price': 50300,
        'entry_amount': 0.1,
        'entry_time': now,
        'stop_loss': 47785,  # -5%
        'take_profit': 57845  # +15%
    }

    pos_id = db.create_position(position)
    print(f"  ✓ ポジション作成: {pos_id}")

    # オープンポジション取得
    open_positions = db.get_open_positions()
    print(f"  ✓ オープンポジション数: {len(open_positions)}")

    print("\n" + "=" * 60)
    print("テスト完了！")
    print("=" * 60)

    # クリーンアップ
    import shutil
    shutil.rmtree("database_test")
    print("\nテストDBディレクトリを削除しました")

if __name__ == "__main__":
    test_database_initialization()
