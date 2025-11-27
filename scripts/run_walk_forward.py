#!/usr/bin/env python3
"""ウォークフォワード検証実行スクリプト

使用例:
    python scripts/run_walk_forward.py --symbol BTC/JPY --train-days 180 --test-days 30
"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import logging
import pandas as pd
import numpy as np
from datetime import datetime

from ml.backtesting.walk_forward import create_walk_forward_engine
from ml.models.ensemble_model import EnsembleModel
from ml.models.hmm_model import MarketRegimeHMM
from ml.models.lightgbm_model import PriceDirectionLGBM
from ml.feature_engineering.feature_engineer import FeatureEngineer
from data.indicators.technical_indicators import TechnicalIndicators
from data.collector.bitflyer_client import BitFlyerClient
from utils.logger import setup_logger

# ロガー設定
logger = setup_logger('walk_forward', 'walk_forward.log')


def prepare_data(symbol: str, days: int = 730) -> pd.DataFrame:
    """データ準備"""
    logger.info(f"データ取得中: {symbol} ({days}日分)")

    client = BitFlyerClient()
    indicators = TechnicalIndicators()
    feature_engineer = FeatureEngineer()

    # OHLCVデータ取得（1時間足）
    limit = days * 24
    ohlcv = client.fetch_ohlcv(symbol, '1h', limit)

    if ohlcv is None or len(ohlcv) < 100:
        raise ValueError(f"データ取得失敗: {symbol}")

    # DataFrame作成
    df = pd.DataFrame(
        ohlcv,
        columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
    )
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

    # テクニカル指標計算
    logger.info("テクニカル指標計算中...")
    df = indicators.calculate_all_indicators(df)

    # 特徴量エンジニアリング
    logger.info("特徴量エンジニアリング中...")
    df = feature_engineer.engineer_features(df)

    # NaN除去
    df = df.dropna()

    logger.info(f"データ準備完了: {len(df)}サンプル")

    return df


def model_trainer(train_df: pd.DataFrame) -> EnsembleModel:
    """モデル学習関数"""
    # モデル初期化
    hmm = MarketRegimeHMM(n_states=3)
    lgbm = PriceDirectionLGBM(n_classes=3)
    model = EnsembleModel(hmm_model=hmm, lgbm_model=lgbm, wait_for_dip=False)

    # ターゲット作成
    df = train_df.copy()
    df['future_return'] = df['close'].shift(-1) / df['close'] - 1
    df['target_direction'] = pd.cut(
        df['future_return'],
        bins=[-np.inf, -0.005, 0.005, np.inf],
        labels=[-1, 0, 1]
    ).astype(int)
    df = df.dropna()

    # 学習
    model.fit(df, target_col='target_direction')

    return model


def signal_generator(model: EnsembleModel, test_df: pd.DataFrame) -> np.ndarray:
    """シグナル生成関数"""
    signals = []

    for i in range(len(test_df)):
        # 直近データで予測
        df_slice = test_df.iloc[:i+1].copy()

        if len(df_slice) < 50:
            signals.append(0)  # HOLD
            continue

        try:
            result = model.generate_trading_signal(
                df_slice,
                confidence_threshold=0.6,
                symbol='BTC/JPY'
            )

            if result['signal'] == 'BUY':
                signals.append(1)
            elif result['signal'] == 'SELL':
                signals.append(-1)
            else:
                signals.append(0)
        except Exception:
            signals.append(0)

    return np.array(signals)


def main():
    parser = argparse.ArgumentParser(description='ウォークフォワード検証')
    parser.add_argument('--symbol', type=str, default='BTC/JPY', help='取引ペア')
    parser.add_argument('--train-days', type=int, default=180, help='学習期間（日）')
    parser.add_argument('--test-days', type=int, default=30, help='検証期間（日）')
    parser.add_argument('--step-days', type=int, default=7, help='ステップ（日）')
    parser.add_argument('--data-days', type=int, default=730, help='データ取得期間（日）')
    parser.add_argument('--capital', type=float, default=200000, help='初期資金')

    args = parser.parse_args()

    print("=" * 70)
    print("ウォークフォワード検証")
    print("=" * 70)
    print(f"通貨ペア: {args.symbol}")
    print(f"学習期間: {args.train_days}日")
    print(f"検証期間: {args.test_days}日")
    print(f"ステップ: {args.step_days}日")
    print(f"初期資金: ¥{args.capital:,.0f}")
    print("=" * 70)

    try:
        # データ準備
        df = prepare_data(args.symbol, args.data_days)

        # ウォークフォワードエンジン作成
        engine = create_walk_forward_engine(
            train_days=args.train_days,
            test_days=args.test_days,
            step_days=args.step_days,
            initial_capital=args.capital
        )

        # 検証実行
        results = engine.run(
            df=df,
            model_trainer=model_trainer,
            signal_generator=signal_generator,
            timestamp_col='timestamp'
        )

        # 結果表示
        engine.print_summary()

        # Fold詳細をCSV出力
        fold_df = engine.get_fold_details()
        output_path = f'logs/walk_forward_{args.symbol.replace("/", "_")}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        fold_df.to_csv(output_path, index=False)
        print(f"\n詳細結果を保存: {output_path}")

    except Exception as e:
        logger.error(f"エラー: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
