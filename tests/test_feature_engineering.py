"""特徴量エンジニアリングテスト"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.training.feature_engineering import FeatureEngineer
from data.processor.indicators import TechnicalIndicators
from utils.logger import setup_logger

# ロガー設定
logger = setup_logger('test_features', 'test_features.log', console=True)


def create_sample_data(n_rows: int = 1000) -> pd.DataFrame:
    """テスト用のサンプルデータを生成"""
    np.random.seed(42)

    # ランダムウォークで価格生成
    returns = np.random.normal(0.0001, 0.02, n_rows)
    price = 100 * np.exp(np.cumsum(returns))

    # OHLCV生成
    data = {
        'timestamp': np.arange(n_rows) * 3600,  # 1時間ごと
        'open': price * (1 + np.random.uniform(-0.01, 0.01, n_rows)),
        'high': price * (1 + np.random.uniform(0, 0.02, n_rows)),
        'low': price * (1 + np.random.uniform(-0.02, 0, n_rows)),
        'close': price,
        'volume': np.random.uniform(1, 100, n_rows)
    }

    df = pd.DataFrame(data)

    # 高値・安値の調整（整合性確保）
    df['high'] = df[['open', 'high', 'close']].max(axis=1)
    df['low'] = df[['open', 'low', 'close']].min(axis=1)

    return df


def test_feature_engineering():
    """特徴量エンジニアリングテスト"""
    print("=" * 60)
    print("特徴量エンジニアリングテスト")
    print("=" * 60)

    # 1. サンプルデータ生成
    print("\n[1] サンプルデータ生成:")
    df = create_sample_data(n_rows=1000)
    print(f"  ✓ データ生成完了: {len(df)}行")
    print(f"  ✓ カラム: {list(df.columns)}")
    print(f"  ✓ 価格範囲: ¥{df['close'].min():.2f} ~ ¥{df['close'].max():.2f}")

    # 2. 技術指標計算
    print("\n[2] 技術指標計算:")
    ti = TechnicalIndicators()
    df_with_indicators = ti.calculate_all(df)
    print(f"  ✓ 技術指標計算完了")
    print(f"  ✓ カラム数: {len(df.columns)} → {len(df_with_indicators.columns)}")

    # 3. 特徴量生成
    print("\n[3] 特徴量生成:")
    fe = FeatureEngineer()
    df_features = fe.create_all_features(df_with_indicators)
    print(f"  ✓ 特徴量生成完了")
    print(f"  ✓ データ行数: {len(df_with_indicators)} → {len(df_features)}")
    print(f"  ✓ 総カラム数: {len(df_features.columns)}")
    print(f"  ✓ 特徴量数: {len(fe.get_feature_columns())}")

    # 4. 特徴量のサンプル表示
    print("\n[4] 生成された特徴量（サンプル）:")
    feature_cols = fe.get_feature_columns()
    print(f"  - 価格特徴量: return_1, return_5, log_return, high_low_ratio, body_size")
    print(f"  - ボラティリティ: volatility_5, volatility_10, parkinson_vol")
    print(f"  - トレンド: sma20_distance, uptrend_5, consecutive_up")
    print(f"  - モメンタム: rsi_overbought, macd_crossover, roc_5")
    print(f"  - 出来高: volume_ratio, volume_spike, obv_trend")
    print(f"  - 時系列: hour, day_of_week, is_weekend")
    print(f"  - ラグ: close_lag_1, return_lag_1, volume_lag_1")
    print(f"  - 統計: close_zscore_20, skewness_20, kurtosis_20")

    # 5. ターゲット変数生成
    print("\n[5] ターゲット変数生成:")
    df_with_target = fe.create_target_variable(df_features, prediction_horizon=1, threshold=0.001)
    print(f"  ✓ ターゲット変数生成完了")
    print(f"  ✓ データ行数: {len(df_features)} → {len(df_with_target)}")

    # ターゲット分布
    direction_counts = df_with_target['target_direction'].value_counts().sort_index()
    print(f"\n  【方向性分類】")
    print(f"    下降(-1): {direction_counts.get(-1, 0)}件 ({direction_counts.get(-1, 0)/len(df_with_target)*100:.1f}%)")
    print(f"    横ばい(0): {direction_counts.get(0, 0)}件 ({direction_counts.get(0, 0)/len(df_with_target)*100:.1f}%)")
    print(f"    上昇(1): {direction_counts.get(1, 0)}件 ({direction_counts.get(1, 0)/len(df_with_target)*100:.1f}%)")

    binary_counts = df_with_target['target_binary'].value_counts()
    print(f"\n  【バイナリ分類】")
    print(f"    下降(0): {binary_counts.get(0, 0)}件 ({binary_counts.get(0, 0)/len(df_with_target)*100:.1f}%)")
    print(f"    上昇(1): {binary_counts.get(1, 0)}件 ({binary_counts.get(1, 0)/len(df_with_target)*100:.1f}%)")

    # 6. 重要特徴量選択
    print("\n[6] 重要特徴量選択（相関ベース）:")
    top_features = fe.select_important_features(df_with_target, target_col='target_direction', top_n=20)
    print(f"  ✓ Top 20特徴量:")
    for i, feat in enumerate(top_features[:10], 1):
        corr = df_with_target[feat].corr(df_with_target['target_direction'])
        print(f"    {i:2d}. {feat:30s} (相関: {abs(corr):.4f})")

    # 7. データ品質確認
    print("\n[7] データ品質確認:")
    print(f"  ✓ 欠損値: {df_with_target.isnull().sum().sum()}個")
    print(f"  ✓ 無限値: {np.isinf(df_with_target.select_dtypes(include=[np.number])).sum().sum()}個")

    # サンプルデータ表示
    print("\n[8] サンプルデータ（最新5行）:")
    sample_cols = ['close', 'return_1', 'volatility_20', 'rsi', 'macd', 'target_direction']
    available_cols = [col for col in sample_cols if col in df_with_target.columns]
    print(df_with_target[available_cols].tail(5).to_string())

    # 9. メモリ使用量
    print("\n[9] メモリ使用量:")
    memory_mb = df_with_target.memory_usage(deep=True).sum() / 1024 / 1024
    print(f"  ✓ DataFrame: {memory_mb:.2f} MB")
    print(f"  ✓ 行あたり: {memory_mb / len(df_with_target) * 1000:.2f} KB")

    print("\n" + "=" * 60)
    print("テスト完了！")
    print("=" * 60)

    return df_with_target, fe


if __name__ == "__main__":
    df, feature_engineer = test_feature_engineering()
