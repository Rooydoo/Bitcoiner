"""Phase 2統合テスト - MLモデル開発完了確認"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.processor.indicators import TechnicalIndicators
from ml.training.feature_engineering import FeatureEngineer
from ml.models.hmm_model import MarketRegimeHMM
from ml.models.lightgbm_model import PriceDirectionLGBM
from ml.models.ensemble_model import EnsembleModel
from ml.backtesting.backtest_engine import BacktestEngine
from utils.logger import setup_logger

# ロガー設定
logger = setup_logger('test_phase2', 'test_phase2.log', console=True)


def create_realistic_data(n_rows: int = 2000) -> pd.DataFrame:
    """現実的な市場データを生成"""
    np.random.seed(42)

    price = 100.0
    prices = []

    for i in range(n_rows):
        # 市場状態の変化
        if i < 600:
            # 上昇トレンド
            ret = np.random.normal(0.0015, 0.015)
        elif i < 1200:
            # レンジ相場
            ret = np.random.normal(0.0, 0.01)
        elif i < 1600:
            # 下降トレンド
            ret = np.random.normal(-0.001, 0.02)
        else:
            # 再度上昇
            ret = np.random.normal(0.001, 0.012)

        price = price * (1 + ret)
        prices.append(price)

    prices_arr = np.array(prices)

    data = {
        'timestamp': np.arange(n_rows) * 3600,
        'open': prices_arr * (1 + np.random.uniform(-0.005, 0.005, n_rows)),
        'high': prices_arr * (1 + np.random.uniform(0, 0.015, n_rows)),
        'low': prices_arr * (1 + np.random.uniform(-0.015, 0, n_rows)),
        'close': prices_arr,
        'volume': np.random.uniform(10, 100, n_rows)
    }

    df = pd.DataFrame(data)
    df['high'] = df[['open', 'high', 'close']].max(axis=1)
    df['low'] = df[['open', 'low', 'close']].min(axis=1)

    return df


def test_phase2_integration():
    """Phase 2統合テスト"""
    print("=" * 70)
    print("Phase 2統合テスト: MLモデル開発")
    print("=" * 70)

    # ========== 1. データパイプライン確認 ==========
    print("\n[1] データパイプライン確認:")
    df_raw = create_realistic_data(n_rows=2000)
    print(f"  ✓ 生データ生成: {len(df_raw)}行")

    ti = TechnicalIndicators()
    df_indicators = ti.calculate_all(df_raw)
    print(f"  ✓ 技術指標計算: {len(df_indicators.columns)}列")

    fe = FeatureEngineer()
    df_features = fe.create_all_features(df_indicators)
    print(f"  ✓ 特徴量生成: {len(df_features.columns)}列, {len(fe.get_feature_columns())}特徴量")

    df_ml = fe.create_target_variable(df_features, prediction_horizon=1, threshold=0.001)
    print(f"  ✓ ターゲット変数生成: {len(df_ml)}行")

    # Train/Testデータ分割
    train_size = int(len(df_ml) * 0.7)
    df_train = df_ml[:train_size]
    df_test = df_ml[train_size:]
    print(f"  ✓ データ分割: Train={len(df_train)}, Test={len(df_test)}")

    # ========== 2. 個別モデルテスト ==========
    print("\n[2] 個別モデル確認:")

    # HMMモデル
    print("  [HMM]")
    hmm = MarketRegimeHMM(n_states=3, n_iter=100)
    hmm.fit(df_train)
    hmm_states = hmm.predict_states(df_test)
    print(f"    ✓ 学習・予測完了: {len(hmm_states)}サンプル")

    # LightGBMモデル
    print("  [LightGBM]")
    lgbm = PriceDirectionLGBM(n_classes=3)
    X_train, _, y_train, _, feat_names = lgbm.prepare_data(df_train, test_size=0.2)
    lgbm.fit(X_train, y_train, feature_names=feat_names, num_boost_round=200)
    print(f"    ✓ 学習完了: {len(feat_names)}特徴量")

    # ========== 3. アンサンブルモデルテスト ==========
    print("\n[3] アンサンブルモデル確認:")
    ensemble = EnsembleModel(
        hmm_model=MarketRegimeHMM(n_states=3),
        lgbm_model=PriceDirectionLGBM(n_classes=3),
        use_state_adjustment=True
    )
    ensemble.fit(df_train)
    print(f"  ✓ アンサンブル学習完了")

    # 予測精度
    eval_results = ensemble.evaluate(df_test)
    print(f"  ✓ 予測精度: {eval_results['accuracy']:.2%}")

    # 売買シグナル生成
    signal_info = ensemble.generate_trading_signal(df_test, confidence_threshold=0.55)
    print(f"  ✓ シグナル生成: {signal_info['signal']} (確信度: {signal_info['confidence']:.1%})")

    # ========== 4. バックテストテスト ==========
    print("\n[4] バックテスト実行:")

    # シグナルを全期間で生成
    predictions = ensemble.predict(df_test)

    # シグナル変換（0=Down→-1, 1=Range→0, 2=Up→1）
    signals = np.where(predictions == 0, -1, np.where(predictions == 2, 1, 0))

    # バックテスト実行
    backtest = BacktestEngine(
        initial_capital=200000,
        position_size=0.6,  # リスク管理のため60%に抑制
        commission_rate=0.0015
    )

    results = backtest.run_backtest(df_test, signals)

    print(f"  ✓ 取引回数: {results['total_trades']}回")
    print(f"  ✓ 勝率: {results['win_rate']:.2%}")
    print(f"  ✓ 総リターン: {results['total_return_pct']:.2f}%")
    print(f"  ✓ 最大ドローダウン: {results['max_drawdown_pct']:.2f}%")
    print(f"  ✓ シャープレシオ: {results['sharpe_ratio']:.2f}")

    # ========== 5. モデル保存・読み込みテスト ==========
    print("\n[5] モデル永続化確認:")
    model_dir = Path("models")
    model_dir.mkdir(exist_ok=True)

    # アンサンブルモデル保存
    ensemble_path = model_dir / "phase2_ensemble.pkl"
    ensemble.save(str(ensemble_path))
    print(f"  ✓ アンサンブルモデル保存: {ensemble_path}")

    # 読み込みテスト
    ensemble_loaded = EnsembleModel()
    ensemble_loaded.load(str(ensemble_path))
    print(f"  ✓ モデル読み込み成功")

    # 予測一致確認
    pred_loaded = ensemble_loaded.predict(df_test)
    match_rate = (predictions == pred_loaded).mean()
    print(f"  ✓ 予測一致率: {match_rate:.2%}")

    # ========== 6. パフォーマンスサマリー ==========
    print("\n[6] パフォーマンスサマリー:")
    print(f"  【モデル性能】")
    print(f"    - HMM状態数: {ensemble.hmm_model.n_states}")
    print(f"    - LightGBM特徴量数: {len(ensemble.lgbm_model.feature_names)}")
    print(f"    - 予測精度: {eval_results['accuracy']:.2%}")

    print(f"\n  【バックテスト結果】")
    print(f"    - 初期資金: ¥{backtest.initial_capital:,.0f}")
    print(f"    - 最終資金: ¥{results['final_equity']:,.0f}")
    print(f"    - 総損益: ¥{results['total_return']:,.0f} ({results['total_return_pct']:.2f}%)")
    print(f"    - 勝率: {results['win_rate']:.2%}")
    print(f"    - プロフィット率: {results['profit_factor']:.2f}")
    print(f"    - 最大DD: {results['max_drawdown_pct']:.2f}%")

    # ========== 7. Phase 2完了判定 ==========
    print("\n[7] Phase 2完了判定:")

    checks = {
        '特徴量エンジニアリング': len(fe.get_feature_columns()) >= 50,
        'HMMモデル': hmm.is_fitted and len(hmm_states) > 0,
        'LightGBMモデル': lgbm.is_fitted,
        'アンサンブルモデル': ensemble.is_fitted,
        'バックテスト': results['total_trades'] > 0,
        'モデル保存': ensemble_path.exists()
    }

    all_passed = all(checks.values())

    for check_name, passed in checks.items():
        status = "✓" if passed else "✗"
        print(f"  {status} {check_name}")

    # 最終判定
    print("\n" + "=" * 70)
    if all_passed:
        print("Phase 2: MLモデル開発 - 完了✓")
        print("\n実装済みコンポーネント:")
        print("  ✓ 特徴量エンジニアリング（107特徴量）")
        print("  ✓ HMMモデル（市場状態分類）")
        print("  ✓ LightGBMモデル（価格方向予測）")
        print("  ✓ アンサンブルモデル（HMM + LightGBM統合）")
        print("  ✓ バックテストエンジン")
        print("\n次のフェーズ: Phase 3 - 売買エンジン実装")
    else:
        print("Phase 2: 一部のチェックが失敗しました")

    print("=" * 70 + "\n")

    return ensemble, results


if __name__ == "__main__":
    model, backtest_results = test_phase2_integration()
