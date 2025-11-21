"""LightGBMモデルテスト"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.models.lightgbm_model import PriceDirectionLGBM
from ml.training.feature_engineering import FeatureEngineer
from data.processor.indicators import TechnicalIndicators
from utils.logger import setup_logger

# ロガー設定
logger = setup_logger('test_lgbm', 'test_lgbm.log', console=True)


def create_sample_data(n_rows: int = 2000) -> pd.DataFrame:
    """テスト用のサンプルデータを生成"""
    np.random.seed(42)

    # ランダムウォークで価格生成（トレンドを持たせる）
    trend = np.linspace(0, 0.5, n_rows)
    noise = np.random.normal(0, 0.02, n_rows)
    returns = trend / n_rows + noise
    price = 100 * np.exp(np.cumsum(returns))

    # OHLCV生成
    data = {
        'timestamp': np.arange(n_rows) * 3600,
        'open': price * (1 + np.random.uniform(-0.01, 0.01, n_rows)),
        'high': price * (1 + np.random.uniform(0, 0.02, n_rows)),
        'low': price * (1 + np.random.uniform(-0.02, 0, n_rows)),
        'close': price,
        'volume': np.random.uniform(10, 100, n_rows)
    }

    df = pd.DataFrame(data)

    # 高値・安値の調整
    df['high'] = df[['open', 'high', 'close']].max(axis=1)
    df['low'] = df[['open', 'low', 'close']].min(axis=1)

    return df


def test_lightgbm_model():
    """LightGBMモデルテスト"""
    print("=" * 60)
    print("LightGBMモデルテスト（価格方向予測）")
    print("=" * 60)

    # 1. サンプルデータ生成
    print("\n[1] サンプルデータ生成:")
    df = create_sample_data(n_rows=2000)
    print(f"  ✓ データ生成完了: {len(df)}行")
    print(f"  ✓ 価格範囲: ¥{df['close'].min():.2f} ~ ¥{df['close'].max():.2f}")

    # 2. 技術指標計算
    print("\n[2] 技術指標計算:")
    ti = TechnicalIndicators()
    df_with_indicators = ti.calculate_all(df)
    print(f"  ✓ 技術指標計算完了: {len(df_with_indicators.columns)}列")

    # 3. 特徴量生成
    print("\n[3] 特徴量生成:")
    fe = FeatureEngineer()
    df_features = fe.create_all_features(df_with_indicators)
    print(f"  ✓ 特徴量生成完了: {len(df_features.columns)}列")

    # 4. ターゲット変数生成
    print("\n[4] ターゲット変数生成:")
    df_with_target = fe.create_target_variable(df_features, prediction_horizon=1, threshold=0.001)
    print(f"  ✓ ターゲット変数生成完了: {len(df_with_target)}行")

    # ターゲット分布
    direction_counts = df_with_target['target_direction'].value_counts().sort_index()
    print(f"  ✓ ターゲット分布:")
    print(f"      下降(-1): {direction_counts.get(-1, 0)}件")
    print(f"      横ばい(0): {direction_counts.get(0, 0)}件")
    print(f"      上昇(1): {direction_counts.get(1, 0)}件")

    # 5. LightGBMモデル初期化（3クラス分類）
    print("\n[5] LightGBMモデル初期化（3クラス分類）:")
    lgbm_model = PriceDirectionLGBM(n_classes=3, random_state=42)
    print(f"  ✓ クラス数: {lgbm_model.n_classes}")
    print(f"  ✓ パラメータ: max_depth={lgbm_model.params['max_depth']}, "
          f"num_leaves={lgbm_model.params['num_leaves']}")

    # 6. データ準備
    print("\n[6] 学習用データ準備:")
    X_train, X_test, y_train, y_test, feature_names = lgbm_model.prepare_data(
        df_with_target,
        target_col='target_direction',
        test_size=0.2
    )
    print(f"  ✓ 学習データ: {len(X_train)}サンプル")
    print(f"  ✓ テストデータ: {len(X_test)}サンプル")
    print(f"  ✓ 特徴量数: {len(feature_names)}")

    # 7. モデル学習
    print("\n[7] モデル学習:")
    lgbm_model.fit(
        X_train, y_train,
        feature_names=feature_names,
        num_boost_round=300,
        early_stopping_rounds=30
    )
    print(f"  ✓ 学習完了")
    print(f"  ✓ Best iteration: {lgbm_model.model.best_iteration}")

    # 8. 予測
    print("\n[8] 予測:")
    y_pred = lgbm_model.predict(X_test)
    y_pred_proba = lgbm_model.predict_proba(X_test)
    print(f"  ✓ 予測完了: {len(y_pred)}サンプル")
    print(f"  ✓ 予測確率shape: {y_pred_proba.shape}")

    # 予測分布
    pred_counts = pd.Series(y_pred).value_counts().sort_index()
    print(f"  ✓ 予測分布:")
    for label, count in pred_counts.items():
        label_name = {-1: '下降', 0: '横ばい', 1: '上昇'}.get(label, f'Class_{label}')
        print(f"      {label_name}({label}): {count}件 ({count/len(y_pred)*100:.1f}%)")

    # 9. モデル評価
    print("\n[9] モデル評価:")
    eval_results = lgbm_model.evaluate(X_test, y_test)
    print(f"  ✓ 精度(Accuracy): {eval_results['accuracy']:.4f}")
    print(f"  ✓ クラス別F1スコア:")
    for class_name in ['Down', 'Range', 'Up']:
        if class_name in eval_results['classification_report']:
            f1 = eval_results['classification_report'][class_name]['f1-score']
            precision = eval_results['classification_report'][class_name]['precision']
            recall = eval_results['classification_report'][class_name]['recall']
            print(f"      {class_name:10s}: F1={f1:.4f}, Precision={precision:.4f}, Recall={recall:.4f}")

    # 混同行列
    print(f"\n  ✓ 混同行列:")
    cm = eval_results['confusion_matrix']
    print("              予測→")
    print("         Down   Range    Up")
    print(f"  Down   {cm[0][0]:5d}  {cm[0][1]:5d}  {cm[0][2]:5d}")
    print(f"  Range  {cm[1][0]:5d}  {cm[1][1]:5d}  {cm[1][2]:5d}")
    print(f"  Up     {cm[2][0]:5d}  {cm[2][1]:5d}  {cm[2][2]:5d}")

    # 10. 特徴量重要度
    print("\n[10] 特徴量重要度（Top 15）:")
    top_features = lgbm_model.get_feature_importance(top_n=15)
    for i, (name, imp) in enumerate(top_features.items(), 1):
        print(f"  {i:2d}. {name:30s} (gain: {imp['gain']:8.2f}, split: {imp['split']:5d})")

    # 11. モデル保存・読み込みテスト
    print("\n[11] モデル保存・読み込みテスト:")
    model_path = "models/test_lightgbm_model.pkl"
    lgbm_model.save(model_path)
    print(f"  ✓ モデル保存: {model_path}")

    # 新しいインスタンスで読み込み
    lgbm_model_loaded = PriceDirectionLGBM()
    lgbm_model_loaded.load(model_path)
    print(f"  ✓ モデル読み込み完了")
    print(f"  ✓ クラス数: {lgbm_model_loaded.n_classes}")
    print(f"  ✓ 特徴量数: {len(lgbm_model_loaded.feature_names)}")

    # 読み込んだモデルで予測
    y_pred_loaded = lgbm_model_loaded.predict(X_test)
    match_rate = (y_pred == y_pred_loaded).mean()
    print(f"  ✓ 予測一致率: {match_rate:.2%}")

    # 12. モデルサマリー
    print("\n[12] モデルサマリー:")
    summary = lgbm_model.get_model_summary()
    print(f"  ✓ ステータス: {summary['status']}")
    print(f"  ✓ クラス数: {summary['n_classes']}")
    print(f"  ✓ 特徴量数: {summary['n_features']}")
    print(f"  ✓ Best iteration: {summary['best_iteration']}")
    print(f"  ✓ Top 5特徴量: {', '.join(summary['top_features'][:5])}")

    # 13. バイナリ分類テスト
    print("\n[13] バイナリ分類テスト（上昇/下降）:")
    lgbm_binary = PriceDirectionLGBM(n_classes=2, random_state=42)

    X_train_b, X_test_b, y_train_b, y_test_b, feature_names_b = lgbm_binary.prepare_data(
        df_with_target,
        target_col='target_binary',
        test_size=0.2
    )

    lgbm_binary.fit(X_train_b, y_train_b, feature_names=feature_names_b, num_boost_round=200)
    eval_binary = lgbm_binary.evaluate(X_test_b, y_test_b)

    print(f"  ✓ 精度(Accuracy): {eval_binary['accuracy']:.4f}")
    print(f"  ✓ 下降F1スコア: {eval_binary['classification_report']['Down']['f1-score']:.4f}")
    print(f"  ✓ 上昇F1スコア: {eval_binary['classification_report']['Up']['f1-score']:.4f}")

    print("\n" + "=" * 60)
    print("テスト完了！")
    print("=" * 60)

    return lgbm_model, df_with_target


if __name__ == "__main__":
    model, data = test_lightgbm_model()
