"""HMMモデルテスト"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

# matplotlibはオプション（なくてもテスト可能）
try:
    import matplotlib
    matplotlib.use('Agg')  # GUIなし環境用
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.models.hmm_model import MarketRegimeHMM
from data.processor.indicators import TechnicalIndicators
from utils.logger import setup_logger

# ロガー設定
logger = setup_logger('test_hmm', 'test_hmm.log', console=True)


def create_sample_market_data(n_rows: int = 2000) -> pd.DataFrame:
    """市場の状態遷移を含むサンプルデータを生成"""
    np.random.seed(42)

    data = {
        'timestamp': np.arange(n_rows) * 3600,
        'close': [],
        'open': [],
        'high': [],
        'low': [],
        'volume': []
    }

    price = 100.0
    prices = []

    # 3つの異なる市場状態を生成
    for i in range(n_rows):
        if i < 600:
            # 状態1: 上昇トレンド（高リターン、低ボラティリティ）
            return_val = np.random.normal(0.002, 0.01)
        elif i < 1200:
            # 状態2: レンジ相場（低リターン、低ボラティリティ）
            return_val = np.random.normal(0.0, 0.008)
        elif i < 1600:
            # 状態3: 下降トレンド（負リターン、高ボラティリティ）
            return_val = np.random.normal(-0.002, 0.02)
        else:
            # 状態4: 再度上昇トレンド
            return_val = np.random.normal(0.0015, 0.012)

        price = price * (1 + return_val)
        prices.append(price)

    # OHLCV生成
    prices_arr = np.array(prices)
    data['close'] = prices_arr
    data['open'] = prices_arr * (1 + np.random.uniform(-0.005, 0.005, n_rows))
    data['high'] = prices_arr * (1 + np.random.uniform(0, 0.015, n_rows))
    data['low'] = prices_arr * (1 + np.random.uniform(-0.015, 0, n_rows))
    data['volume'] = np.random.uniform(10, 100, n_rows)

    df = pd.DataFrame(data)

    # 高値・安値の調整
    df['high'] = df[['open', 'high', 'close']].max(axis=1)
    df['low'] = df[['open', 'low', 'close']].min(axis=1)

    return df


def test_hmm_model():
    """HMMモデルテスト"""
    print("=" * 60)
    print("HMMモデルテスト（市場状態分類）")
    print("=" * 60)

    # 1. サンプルデータ生成
    print("\n[1] サンプル市場データ生成:")
    df = create_sample_market_data(n_rows=2000)
    print(f"  ✓ データ生成完了: {len(df)}行")
    print(f"  ✓ 価格範囲: ¥{df['close'].min():.2f} ~ ¥{df['close'].max():.2f}")

    # 2. 技術指標計算
    print("\n[2] 技術指標計算:")
    ti = TechnicalIndicators()
    df_with_indicators = ti.calculate_all(df)
    print(f"  ✓ 技術指標計算完了: {len(df_with_indicators.columns)}列")

    # 3. HMMモデル初期化（3状態）
    print("\n[3] HMMモデル初期化:")
    hmm_model = MarketRegimeHMM(n_states=3, n_iter=100, random_state=42)
    print(f"  ✓ 状態数: {hmm_model.n_states}")
    print(f"  ✓ 反復回数: {hmm_model.n_iter}")

    # 4. モデル学習
    print("\n[4] HMMモデル学習:")
    train_data = df_with_indicators[:1500]  # 最初の1500行で学習
    hmm_model.fit(train_data)
    print(f"  ✓ 学習完了")
    print(f"  ✓ 状態ラベル:")
    for state, label in hmm_model.state_labels.items():
        print(f"      {state}: {label}")

    # 5. 状態予測
    print("\n[5] 市場状態予測:")
    test_data = df_with_indicators[1500:]  # 残り500行でテスト
    states = hmm_model.predict_states(test_data)
    proba = hmm_model.predict_proba(test_data)
    print(f"  ✓ 予測完了: {len(states)}サンプル")
    print(f"  ✓ 状態分布:")
    for state in range(hmm_model.n_states):
        count = (states == state).sum()
        pct = count / len(states) * 100
        label = hmm_model.state_labels.get(state, f'State_{state}')
        print(f"      {label}: {count}回 ({pct:.1f}%)")

    # 6. 現在の市場状態
    print("\n[6] 現在の市場状態:")
    current_state_info = hmm_model.get_current_state(df_with_indicators, lookback=100)
    print(f"  ✓ 現在の状態: {current_state_info['state_label']}")
    print(f"  ✓ 確率: {current_state_info['probability']:.2%}")
    print(f"  ✓ 安定性: {current_state_info['stability']:.2%}")
    print(f"  ✓ 全状態確率:")
    for i, prob in enumerate(current_state_info['all_probabilities']):
        label = hmm_model.state_labels.get(i, f'State_{i}')
        print(f"      {label}: {prob:.2%}")

    # 7. 状態遷移行列
    print("\n[7] 状態遷移行列:")
    trans_matrix = hmm_model.get_transition_matrix()
    print("  ", end="")
    for i in range(hmm_model.n_states):
        print(f"→S{i}     ", end="")
    print()
    for i in range(hmm_model.n_states):
        print(f"  S{i}", end=" ")
        for j in range(hmm_model.n_states):
            print(f"{trans_matrix[i, j]:.3f}  ", end="")
        print()
    print(f"\n  解釈: 各行から各列への遷移確率")

    # 8. モデル保存・読み込みテスト
    print("\n[8] モデル保存・読み込みテスト:")
    model_path = "models/test_hmm_model.pkl"
    hmm_model.save(model_path)
    print(f"  ✓ モデル保存: {model_path}")

    # 新しいインスタンスで読み込み
    hmm_model_loaded = MarketRegimeHMM()
    hmm_model_loaded.load(model_path)
    print(f"  ✓ モデル読み込み完了")
    print(f"  ✓ 状態数: {hmm_model_loaded.n_states}")
    print(f"  ✓ 学習済み: {hmm_model_loaded.is_fitted}")

    # 読み込んだモデルで予測
    states_loaded = hmm_model_loaded.predict_states(test_data)
    match_rate = (states == states_loaded).mean()
    print(f"  ✓ 予測一致率: {match_rate:.2%}")

    # 9. モデルサマリー
    print("\n[9] モデルサマリー:")
    summary = hmm_model.get_model_summary()
    print(f"  ✓ ステータス: {summary['status']}")
    print(f"  ✓ 状態数: {summary['n_states']}")
    print(f"  ✓ 平均値（各状態の特徴）:")
    for i, mean in enumerate(summary['means']):
        label = hmm_model.state_labels.get(i, f'State_{i}')
        print(f"      {label}: {mean}")

    # 10. 全期間での状態推移をプロット（オプション）
    print("\n[10] 状態推移の可視化:")
    if HAS_MATPLOTLIB:
        try:
            all_states = hmm_model.predict_states(df_with_indicators)

            # グラフ作成
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

            # 価格チャート
            ax1.plot(df_with_indicators['close'].values[:len(all_states)], label='Close Price', color='black', linewidth=1)
            ax1.set_ylabel('Price (JPY)')
            ax1.set_title('Market Regime Classification with HMM')
            ax1.legend()
            ax1.grid(True, alpha=0.3)

            # 状態の色分け
            for state in range(hmm_model.n_states):
                mask = (all_states == state)
                label = hmm_model.state_labels.get(state, f'State_{state}')
                ax1.scatter(np.where(mask)[0], df_with_indicators['close'].values[:len(all_states)][mask],
                           s=1, alpha=0.5, label=label)

            # 状態推移
            ax2.plot(all_states, linewidth=1)
            ax2.set_ylabel('State')
            ax2.set_xlabel('Time Period')
            ax2.set_yticks(range(hmm_model.n_states))
            ax2.set_yticklabels([hmm_model.state_labels.get(i, f'S{i}') for i in range(hmm_model.n_states)])
            ax2.grid(True, alpha=0.3)

            plt.tight_layout()
            chart_path = 'logs/hmm_states.png'
            plt.savefig(chart_path, dpi=100, bbox_inches='tight')
            print(f"  ✓ チャート保存: {chart_path}")
        except Exception as e:
            print(f"  ⚠ チャート作成スキップ: {e}")
    else:
        print(f"  ⚠ matplotlibなし - スキップ")

    print("\n" + "=" * 60)
    print("テスト完了！")
    print("=" * 60)

    return hmm_model, df_with_indicators


if __name__ == "__main__":
    model, data = test_hmm_model()
