"""技術指標計算テスト"""

import sys
from pathlib import Path
import numpy as np

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.processor.indicators import TechnicalIndicators
import pandas as pd


def generate_sample_data(num_points: int = 200) -> pd.DataFrame:
    """サンプルOHLCVデータを生成"""
    np.random.seed(42)

    # ランダムウォークで価格を生成
    base_price = 50000
    price_changes = np.random.randn(num_points) * 100
    close_prices = base_price + np.cumsum(price_changes)

    # OHLCVを生成
    data = {
        'timestamp': range(num_points),
        'open': close_prices - np.random.uniform(-50, 50, num_points),
        'high': close_prices + np.random.uniform(0, 100, num_points),
        'low': close_prices - np.random.uniform(0, 100, num_points),
        'close': close_prices,
        'volume': np.random.uniform(1000, 5000, num_points)
    }

    return pd.DataFrame(data)


def test_technical_indicators():
    """技術指標計算テスト"""
    print("=" * 60)
    print("技術指標計算テスト")
    print("=" * 60)

    # サンプルデータ生成
    print("\n[1] サンプルデータ生成:")
    df = generate_sample_data(200)
    print(f"  ✓ データ件数: {len(df)}")
    print(f"  ✓ 価格範囲: ${df['close'].min():,.2f} ~ ${df['close'].max():,.2f}")

    # 技術指標計算
    print("\n[2] 技術指標計算:")
    ti = TechnicalIndicators()
    df_with_indicators = ti.calculate_all(df)

    print(f"  ✓ 計算後のカラム数: {len(df_with_indicators.columns)}")
    print(f"  ✓ 追加された指標数: {len(df_with_indicators.columns) - len(df.columns)}")

    # 各指標の確認
    print("\n[3] 計算された指標の確認:")

    # トレンド系
    print("\n  トレンド系:")
    for col in ['sma_5', 'sma_25', 'sma_75', 'ema_12', 'ema_26', 'macd', 'macd_signal', 'adx']:
        if col in df_with_indicators.columns:
            value = df_with_indicators[col].iloc[-1]
            if pd.notna(value):
                print(f"    ✓ {col}: {value:.2f}")
            else:
                print(f"    ⚠ {col}: NaN（データ不足）")

    # オシレーター系
    print("\n  オシレーター系:")
    for col in ['rsi', 'stoch_k', 'stoch_d', 'cci']:
        if col in df_with_indicators.columns:
            value = df_with_indicators[col].iloc[-1]
            if pd.notna(value):
                print(f"    ✓ {col}: {value:.2f}")
            else:
                print(f"    ⚠ {col}: NaN（データ不足）")

    # ボラティリティ系
    print("\n  ボラティリティ系:")
    for col in ['bb_upper', 'bb_middle', 'bb_lower', 'bb_width', 'atr']:
        if col in df_with_indicators.columns:
            value = df_with_indicators[col].iloc[-1]
            if pd.notna(value):
                print(f"    ✓ {col}: {value:.2f}")
            else:
                print(f"    ⚠ {col}: NaN（データ不足）")

    # 出来高系
    print("\n  出来高系:")
    for col in ['obv', 'vwap']:
        if col in df_with_indicators.columns:
            value = df_with_indicators[col].iloc[-1]
            if pd.notna(value):
                print(f"    ✓ {col}: {value:.2f}")
            else:
                print(f"    ⚠ {col}: NaN（データ不足）")

    # NaNのカウント
    print("\n[4] データ品質確認:")
    nan_counts = df_with_indicators.isna().sum()
    total_nan = nan_counts.sum()
    print(f"  ✓ 総NaN数: {total_nan}")
    print(f"  ✓ NaN率: {(total_nan / (len(df_with_indicators) * len(df_with_indicators.columns))) * 100:.2f}%")

    # 最初の方は移動平均計算で必然的にNaNが発生
    valid_from = df_with_indicators.dropna().index[0] if not df_with_indicators.dropna().empty else 0
    print(f"  ✓ 有効データ開始行: {valid_from}行目から")

    print("\n" + "=" * 60)
    print("テスト完了！")
    print("=" * 60)


if __name__ == "__main__":
    test_technical_indicators()
