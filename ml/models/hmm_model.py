"""HMM（Hidden Markov Model）モデル - 市場状態分類

市場の隠れ状態（トレンド上昇、トレンド下降、レンジ相場など）を推定
"""

import numpy as np
import pandas as pd
import logging
from typing import Tuple, List, Optional, Dict
import joblib
from pathlib import Path
from hmmlearn import hmm
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)


class MarketRegimeHMM:
    """市場レジーム（状態）を分類するHMMモデル"""

    def __init__(self, n_states: int = 3, n_iter: int = 100, random_state: int = 42):
        """
        初期化

        Args:
            n_states: 隠れ状態の数（デフォルト: 3）
                     例: 上昇トレンド、下降トレンド、レンジ相場
            n_iter: 学習の反復回数
            random_state: 乱数シード
        """
        self.n_states = n_states
        self.n_iter = n_iter
        self.random_state = random_state

        # GaussianHMMモデル（連続値の観測値）
        self.model = hmm.GaussianHMM(
            n_components=n_states,
            covariance_type="full",  # 完全共分散行列
            n_iter=n_iter,
            random_state=random_state
        )

        # スケーラー（データ標準化用）
        self.scaler = StandardScaler()

        # モデル学習済みフラグ
        self.is_fitted = False

        # 状態の意味（学習後に推定）
        self.state_labels = {}

        logger.info(f"HMMモデル初期化: {n_states}状態")

    def prepare_features(self, df: pd.DataFrame) -> np.ndarray:
        """
        HMM用の特徴量を準備

        Args:
            df: 価格データ（技術指標含む）

        Returns:
            特徴量配列 (n_samples, n_features)
        """
        features = []

        # 1. リターン
        if 'return_1' in df.columns:
            features.append(df['return_1'].values)

        # 2. ボラティリティ
        if 'volatility_20' in df.columns:
            features.append(df['volatility_20'].values)
        elif 'atr' in df.columns:
            features.append(df['atr'].values / df['close'].values)

        # 3. トレンド強度（ADX）
        if 'adx' in df.columns:
            features.append(df['adx'].values / 100.0)  # 0-1に正規化

        # 4. モメンタム（RSI）
        if 'rsi' in df.columns:
            features.append((df['rsi'].values - 50) / 50.0)  # -1～1に正規化

        # 5. 出来高変化
        if 'volume_change' in df.columns:
            features.append(df['volume_change'].values)

        # フォールバック: 最低限の特徴量（リターンとボラティリティ）
        if len(features) == 0:
            returns = df['close'].pct_change()
            volatility = returns.rolling(window=20).std()
            features = [returns.values, volatility.values]

        # (n_features, n_samples) → (n_samples, n_features)
        X = np.column_stack(features)

        # NaN除去
        X = pd.DataFrame(X).dropna().values

        logger.info(f"HMM特徴量準備完了: {X.shape}")

        return X

    def fit(self, df: pd.DataFrame) -> 'MarketRegimeHMM':
        """
        HMMモデルを学習

        Args:
            df: 学習データ

        Returns:
            self
        """
        logger.info("HMMモデル学習開始")

        # 特徴量準備
        X = self.prepare_features(df)

        # 標準化
        X_scaled = self.scaler.fit_transform(X)

        # HMM学習
        self.model.fit(X_scaled)
        self.is_fitted = True

        # 状態の意味を推定
        self._interpret_states(df)

        logger.info(f"HMMモデル学習完了: {self.n_states}状態")
        logger.info(f"  - 収束スコア: {self.model.score(X_scaled):.2f}")
        logger.info(f"  - 状態ラベル: {self.state_labels}")

        return self

    def predict_states(self, df: pd.DataFrame) -> np.ndarray:
        """
        市場状態を予測

        Args:
            df: 予測データ

        Returns:
            状態配列 (n_samples,)
        """
        if not self.is_fitted:
            raise ValueError("モデルが学習されていません。先にfit()を実行してください。")

        # 特徴量準備
        X = self.prepare_features(df)

        # 標準化
        X_scaled = self.scaler.transform(X)

        # 最も可能性の高い状態系列をデコード（Viterbiアルゴリズム）
        states = self.model.predict(X_scaled)

        logger.debug(f"状態予測完了: {len(states)}サンプル")

        return states

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """
        各状態の確率を予測

        Args:
            df: 予測データ

        Returns:
            確率配列 (n_samples, n_states)
        """
        if not self.is_fitted:
            raise ValueError("モデルが学習されていません。先にfit()を実行してください。")

        # 特徴量準備
        X = self.prepare_features(df)

        # 標準化
        X_scaled = self.scaler.transform(X)

        # 状態確率を計算
        log_prob, posteriors = self.model.score_samples(X_scaled)

        logger.debug(f"状態確率予測完了: {posteriors.shape}")

        return posteriors

    def get_current_state(self, df: pd.DataFrame, lookback: int = 50) -> Dict:
        """
        現在の市場状態を取得

        Args:
            df: 最新データ
            lookback: 過去何期分のデータを使うか

        Returns:
            状態情報の辞書
        """
        # 最新N期間のデータ
        df_recent = df.tail(lookback)

        # 状態予測
        states = self.predict_states(df_recent)
        proba = self.predict_proba(df_recent)

        # 最新の状態
        current_state = states[-1]
        current_proba = proba[-1]

        # 状態の安定性（過去10期間で同じ状態の割合）
        stability = (states[-10:] == current_state).mean() if len(states) >= 10 else 1.0

        result = {
            'state': int(current_state),
            'state_label': self.state_labels.get(current_state, f'State_{current_state}'),
            'probability': float(current_proba[current_state]),
            'all_probabilities': current_proba.tolist(),
            'stability': float(stability),
            'recent_states': states[-10:].tolist() if len(states) >= 10 else states.tolist()
        }

        logger.info(f"現在の市場状態: {result['state_label']} (確率: {result['probability']:.2%})")

        return result

    def _interpret_states(self, df: pd.DataFrame):
        """
        各状態の意味を推定（学習後）

        状態の特徴を分析して、どの状態がどのレジームに対応するか推定する
        """
        # 全データで状態予測
        states = self.predict_states(df)

        # 元データとマージ（長さを合わせる）
        df_temp = df.copy()
        if 'return_1' in df_temp.columns:
            returns = df_temp['return_1'].dropna().values[:len(states)]
        else:
            returns = df_temp['close'].pct_change().dropna().values[:len(states)]

        # 各状態の平均リターンを計算
        state_characteristics = {}

        for state in range(self.n_states):
            mask = (states == state)
            if mask.sum() > 0:
                avg_return = returns[mask].mean()
                avg_volatility = returns[mask].std()

                state_characteristics[state] = {
                    'avg_return': avg_return,
                    'avg_volatility': avg_volatility,
                    'count': mask.sum()
                }

        # 平均リターンでソート
        sorted_states = sorted(state_characteristics.items(), key=lambda x: x[1]['avg_return'])

        # ラベル付け
        if self.n_states == 2:
            # 2状態: 下降/上昇
            self.state_labels = {
                sorted_states[0][0]: 'Bear (下降)',
                sorted_states[1][0]: 'Bull (上昇)'
            }
        elif self.n_states == 3:
            # 3状態: 下降/レンジ/上昇
            self.state_labels = {
                sorted_states[0][0]: 'Bear (下降)',
                sorted_states[1][0]: 'Range (レンジ)',
                sorted_states[2][0]: 'Bull (上昇)'
            }
        elif self.n_states == 4:
            # 4状態: 強下降/弱下降/弱上昇/強上昇
            self.state_labels = {
                sorted_states[0][0]: 'Strong Bear (強下降)',
                sorted_states[1][0]: 'Weak Bear (弱下降)',
                sorted_states[2][0]: 'Weak Bull (弱上昇)',
                sorted_states[3][0]: 'Strong Bull (強上昇)'
            }
        else:
            # 5状態以上: 番号のみ
            for i, (state, _) in enumerate(sorted_states):
                self.state_labels[state] = f'State_{i}'

        logger.info("状態解釈完了:")
        for state, label in self.state_labels.items():
            char = state_characteristics[state]
            logger.info(f"  - {label}: リターン={char['avg_return']:.4f}, "
                       f"ボラティリティ={char['avg_volatility']:.4f}, "
                       f"出現={char['count']}回")

    def save(self, filepath: str):
        """
        モデルを保存

        Args:
            filepath: 保存先パス
        """
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        model_data = {
            'model': self.model,
            'scaler': self.scaler,
            'n_states': self.n_states,
            'state_labels': self.state_labels,
            'is_fitted': self.is_fitted
        }

        joblib.dump(model_data, filepath, compress=3)

        logger.info(f"HMMモデル保存: {filepath}")

    def load(self, filepath: str):
        """
        モデルを読み込み

        Args:
            filepath: 読み込み元パス
        """
        model_data = joblib.load(filepath)

        self.model = model_data['model']
        self.scaler = model_data['scaler']
        self.n_states = model_data['n_states']
        self.state_labels = model_data['state_labels']
        self.is_fitted = model_data['is_fitted']

        logger.info(f"HMMモデル読み込み: {filepath}")

    def load_model(self, filepath: str) -> bool:
        """
        モデルを読み込み（load()のエイリアス、戻り値bool）

        Args:
            filepath: 読み込み元パス

        Returns:
            読み込み成功したかどうか
        """
        try:
            if not Path(filepath).exists():
                logger.warning(f"モデルファイルが見つかりません: {filepath}")
                return False

            self.load(filepath)
            return True
        except Exception as e:
            logger.error(f"モデル読み込み失敗: {e}")
            return False

    def save_model(self, filepath: str) -> bool:
        """
        モデルを保存（save()のエイリアス、戻り値bool）

        Args:
            filepath: 保存先パス

        Returns:
            保存成功したかどうか
        """
        try:
            self.save(filepath)
            return True
        except Exception as e:
            logger.error(f"モデル保存失敗: {e}")
            return False

    def get_transition_matrix(self) -> np.ndarray:
        """
        状態遷移行列を取得

        Returns:
            遷移行列 (n_states, n_states)
        """
        if not self.is_fitted:
            raise ValueError("モデルが学習されていません。")

        return self.model.transmat_

    def get_model_summary(self) -> Dict:
        """
        モデルのサマリー情報を取得

        Returns:
            サマリー辞書
        """
        if not self.is_fitted:
            return {'status': 'not_fitted'}

        summary = {
            'status': 'fitted',
            'n_states': self.n_states,
            'state_labels': self.state_labels,
            'transition_matrix': self.get_transition_matrix().tolist(),
            'means': self.model.means_.tolist(),
            'covariances': [cov.tolist() for cov in self.model.covars_]
        }

        return summary


# ヘルパー関数
def create_hmm_model(n_states: int = 3, n_iter: int = 100) -> MarketRegimeHMM:
    """
    HMMモデルを作成

    Args:
        n_states: 隠れ状態の数
        n_iter: 学習の反復回数

    Returns:
        MarketRegimeHMMインスタンス
    """
    return MarketRegimeHMM(n_states=n_states, n_iter=n_iter)
