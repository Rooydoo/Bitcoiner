"""アンサンブルモデルテスト"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.models.ensemble_model import EnsembleModel, create_ensemble_model
from ml.training.feature_engineering import FeatureEngineer
from data.processor.indicators import TechnicalIndicators
from utils.logger import setup_logger

# ロガー設定
logger = setup_logger('test_ensemble', 'test_ensemble.log', console=True)


def create_sample_data(n_rows: int = 1500) -> pd.DataFrame:
    """テスト用のサンプルデータを生成"""
    np.random.seed(42)

    # トレンドとボラティリティの変化を含む価格生成
    price = 100.0
    prices = []

    for i in range(n_rows):
        if i < 500:
            # 上昇トレンド
            ret = np.random.normal(0.001, 0.015)
        elif i < 1000:
            # レンジ相場
            ret = np.random.normal(0.0, 0.01)
        else:
            # 下降トレンド
            ret = np.random.normal(-0.001, 0.02)

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


def test_ensemble_model():
    """アンサンブルモデルテスト"""
    print("=" * 60)
    print("アンサンブルモデルテスト（HMM + LightGBM）")
    print("=" * 60)

    # 1. データ準備
    print("\n[1] データ準備:")
    df = create_sample_data(n_rows=1500)
    print(f"  ✓ データ生成: {len(df)}行")

    # 技術指標 + 特徴量
    ti = TechnicalIndicators()
    df = ti.calculate_all(df)
    fe = FeatureEngineer()
    df = fe.create_all_features(df)
    df = fe.create_target_variable(df, prediction_horizon=1, threshold=0.001)
    print(f"  ✓ 特徴量生成完了: {len(df)}行, {len(df.columns)}列")

    # Train/Testデータ分割
    train_size = int(len(df) * 0.8)
    df_train = df[:train_size]
    df_test = df[train_size:]
    print(f"  ✓ Train={len(df_train)}行, Test={len(df_test)}行")

    # 2. アンサンブルモデル初期化
    print("\n[2] アンサンブルモデル初期化:")
    ensemble = create_ensemble_model(n_states=3, n_classes=3, use_state_adjustment=True)
    print(f"  ✓ HMM状態数: {ensemble.hmm_model.n_states}")
    print(f"  ✓ LightGBMクラス数: {ensemble.lgbm_model.n_classes}")
    print(f"  ✓ 状態調整: {ensemble.use_state_adjustment}")

    # 3. モデル学習
    print("\n[3] モデル学習:")
    ensemble.fit(df_train, target_col='target_direction')
    print(f"  ✓ 学習完了")

    # 4. 予測
    print("\n[4] 予測:")
    predictions = ensemble.predict(df_test)
    print(f"  ✓ 予測完了: {len(predictions)}サンプル")

    # 予測分布
    pred_counts = pd.Series(predictions).value_counts().sort_index()
    print(f"  ✓ 予測分布:")
    for label, count in pred_counts.items():
        label_name = {0: 'Down', 1: 'Range', 2: 'Up'}.get(label, f'Class_{label}')
        print(f"      {label_name}: {count}件 ({count/len(predictions)*100:.1f}%)")

    # 5. 市場状態付き予測
    print("\n[5] 市場状態付き予測（最新）:")
    pred_info = ensemble.predict_with_state_info(df_test)
    print(f"  ✓ 市場状態: {pred_info['state_label']} (確率: {pred_info['state_probability']:.2%})")
    print(f"  ✓ 価格方向: {pred_info['direction_label']} (確率: {pred_info['direction_probability']:.2%})")

    # 6. 売買シグナル生成
    print("\n[6] 売買シグナル生成:")
    signal = ensemble.generate_trading_signal(df_test, confidence_threshold=0.6)
    print(f"  ✓ シグナル: {signal['signal']}")
    print(f"  ✓ 確信度: {signal['confidence']:.2%}")
    print(f"  ✓ 推奨: {signal['recommendation']}")

    # 7. モデル評価
    print("\n[7] モデル評価:")
    eval_results = ensemble.evaluate(df_test, target_col='target_direction')
    print(f"  ✓ 精度: {eval_results['accuracy']:.4f}")
    print(f"  ✓ クラス別F1スコア:")
    for class_name in ['Down', 'Range', 'Up']:
        if class_name in eval_results['classification_report']:
            f1 = eval_results['classification_report'][class_name]['f1-score']
            print(f"      {class_name:10s}: {f1:.4f}")

    # 8. モデル保存・読み込みテスト
    print("\n[8] モデル保存・読み込みテスト:")
    model_path = "models/test_ensemble_model.pkl"
    ensemble.save(model_path)
    print(f"  ✓ モデル保存: {model_path}")

    # 新しいインスタンスで読み込み
    ensemble_loaded = EnsembleModel()
    ensemble_loaded.load(model_path)
    print(f"  ✓ モデル読み込み完了")

    # 読み込んだモデルで予測
    predictions_loaded = ensemble_loaded.predict(df_test)
    match_rate = (predictions == predictions_loaded).mean()
    print(f"  ✓ 予測一致率: {match_rate:.2%}")

    # 9. 複数シグナル生成テスト
    print("\n[9] 複数時点でのシグナル生成:")
    for i in range(-5, 0):
        df_slice = df_test[:i] if i < -1 else df_test
        sig = ensemble.generate_trading_signal(df_slice, confidence_threshold=0.55)
        print(f"  時点{i:2d}: {sig['signal']:4s} (確信度: {sig['confidence']:.1%}) - {sig['state']}")

    print("\n" + "=" * 60)
    print("テスト完了！")
    print("=" * 60)

    return ensemble, df_test


if __name__ == "__main__":
    model, data = test_ensemble_model()
