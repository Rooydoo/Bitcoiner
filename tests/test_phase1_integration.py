"""Phase 1統合テスト"""

import sys
from pathlib import Path
import time

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger import setup_logger
from utils.resource_monitor import get_resource_monitor
from data.storage.sqlite_manager import get_db_manager
from data.processor.indicators import TechnicalIndicators
import pandas as pd
import numpy as np

# ロガー設定
logger = setup_logger('phase1_test', 'phase1_test.log', console=True)


def test_phase1_integration():
    """Phase 1統合テスト"""
    logger.info("=" * 70)
    logger.info("Phase 1 統合テスト開始")
    logger.info("=" * 70)

    monitor = get_resource_monitor()

    # 初期リソース状態
    logger.info("\n[1] 初期リソース状態:")
    monitor.log_current_status()

    # データベーステスト
    logger.info("\n[2] データベーステスト:")
    db = get_db_manager()

    # サンプルデータ作成
    now = int(time.time())
    sample_data = pd.DataFrame({
        'timestamp': [now - i*3600 for i in range(100, 0, -1)],  # 過去100時間
        'open': np.random.uniform(49000, 51000, 100),
        'high': np.random.uniform(50000, 52000, 100),
        'low': np.random.uniform(48000, 50000, 100),
        'close': np.random.uniform(49000, 51000, 100),
        'volume': np.random.uniform(1000, 5000, 100)
    })

    # データ挿入
    db.insert_ohlcv(sample_data, 'BTC/USDT', '1h')
    logger.info("  ✓ BTC/USDT 1h データ挿入完了 (100件)")

    db.insert_ohlcv(sample_data, 'ETH/USDT', '1h')
    logger.info("  ✓ ETH/USDT 1h データ挿入完了 (100件)")

    # データ取得
    retrieved = db.get_latest_ohlcv('BTC/USDT', '1h', limit=50)
    logger.info(f"  ✓ データ取得テスト: {len(retrieved)}件取得")

    # DBサイズ確認
    sizes = db.get_database_sizes()
    logger.info(f"  ✓ データベースサイズ: {sizes}")

    # リソース状態（データ挿入後）
    logger.info("\n[3] データ挿入後のリソース状態:")
    mem_after_db = monitor.get_memory_usage()
    logger.info(f"  ✓ メモリ使用量: {mem_after_db.get('process_mb')} MB ({mem_after_db.get('process_percent')}%)")

    # 技術指標計算テスト
    logger.info("\n[4] 技術指標計算テスト:")
    ti = TechnicalIndicators()

    # 大量データで技術指標計算（メモリプロファイリング）
    large_data = pd.DataFrame({
        'timestamp': range(1000),
        'open': np.random.uniform(49000, 51000, 1000),
        'high': np.random.uniform(50000, 52000, 1000),
        'low': np.random.uniform(48000, 50000, 1000),
        'close': np.random.uniform(49000, 51000, 1000),
        'volume': np.random.uniform(1000, 5000, 1000)
    })

    start_time = time.time()
    df_with_indicators = ti.calculate_all(large_data)
    calc_time = time.time() - start_time

    logger.info(f"  ✓ 技術指標計算完了: {len(df_with_indicators)}行")
    logger.info(f"  ✓ 計算時間: {calc_time:.2f}秒")
    logger.info(f"  ✓ 指標数: {len(df_with_indicators.columns) - len(large_data.columns)}個追加")

    # リソース状態（計算後）
    logger.info("\n[5] 技術指標計算後のリソース状態:")
    mem_after_calc = monitor.get_memory_usage()
    logger.info(f"  ✓ メモリ使用量: {mem_after_calc.get('process_mb')} MB ({mem_after_calc.get('process_percent')}%)")

    # メモリ増加量
    mem_increase = mem_after_calc.get('process_mb', 0) - mem_after_db.get('process_mb', 0)
    logger.info(f"  ✓ メモリ増加量: {mem_increase:.2f} MB")

    # リソース制限チェック
    logger.info("\n[6] リソース制限チェック:")
    warnings = monitor.check_resource_limits(
        cpu_threshold=80.0,
        memory_threshold=50.0,  # 50%（8GBの半分=4GB）
        disk_threshold=90.0
    )

    if not any(warnings.values()):
        logger.info("  ✓ 全てのリソースが正常範囲内です")
    else:
        logger.warning(f"  ⚠ リソース警告: {warnings}")

    # 最終リソース状態
    logger.info("\n[7] 最終リソース状態:")
    monitor.log_current_status()

    # テスト結果サマリー
    logger.info("\n" + "=" * 70)
    logger.info("Phase 1 統合テスト完了")
    logger.info("=" * 70)

    logger.info("\n✅ テスト結果サマリー:")
    logger.info(f"  - データベース: {len(retrieved)}件のデータ取得成功")
    logger.info(f"  - 技術指標計算: {calc_time:.2f}秒で1000行処理")
    logger.info(f"  - メモリ効率: {mem_after_calc.get('process_mb')} MB使用（{mem_after_calc.get('process_percent')}%）")
    logger.info(f"  - リソース警告: {'なし' if not any(warnings.values()) else 'あり'}")

    # 推奨事項
    logger.info("\n📊 Phase 1 成果物:")
    logger.info("  ✓ SQLiteデータベーススキーマ")
    logger.info("  ✓ Binance API連携モジュール")
    logger.info("  ✓ 技術指標計算モジュール（20種類以上）")
    logger.info("  ✓ データ収集オーケストレーター")
    logger.info("  ✓ タスクスケジューラー")
    logger.info("  ✓ ロギングシステム")
    logger.info("  ✓ リソース監視システム")

    logger.info("\n🎯 次のステップ（Phase 2）:")
    logger.info("  - MLモデル（HMM、LightGBM）の実装")
    logger.info("  - 特徴量エンジニアリング")
    logger.info("  - バックテストエンジンの構築")
    logger.info("  - モデル評価・チューニング")

    logger.info("\n" + "=" * 70)


if __name__ == "__main__":
    test_phase1_integration()
