"""アンサンブルモデル - HMM + LightGBM統合

HMMで市場状態を分類し、LightGBMで価格方向を予測する統合モデル
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, Tuple, Optional, List
import pickle
from pathlib import Path

from ml.models.hmm_model import MarketRegimeHMM
from ml.models.lightgbm_model import PriceDirectionLGBM

logger = logging.getLogger(__name__)


class EnsembleModel:
    """HMMとLightGBMを統合したアンサンブルモデル"""

    def __init__(
        self,
        hmm_model: Optional[MarketRegimeHMM] = None,
        lgbm_model: Optional[PriceDirectionLGBM] = None,
        use_state_adjustment: bool = True
    ):
        """
        初期化

        Args:
            hmm_model: HMMモデル（Noneの場合は新規作成）
            lgbm_model: LightGBMモデル（Noneの場合は新規作成）
            use_state_adjustment: 市場状態に応じた予測調整を使用するか
        """
        self.hmm_model = hmm_model or MarketRegimeHMM(n_states=3)
        self.lgbm_model = lgbm_model or PriceDirectionLGBM(n_classes=3)
        self.use_state_adjustment = use_state_adjustment

        self.is_fitted = False

        logger.info("アンサンブルモデル初期化")
        logger.info(f"  - HMM状態数: {self.hmm_model.n_states}")
        logger.info(f"  - LightGBMクラス数: {self.lgbm_model.n_classes}")
        logger.info(f"  - 状態調整: {use_state_adjustment}")

    def fit(
        self,
        df_train: pd.DataFrame,
        target_col: str = 'target_direction',
        feature_cols: Optional[List[str]] = None
    ) -> 'EnsembleModel':
        """
        モデルを学習

        Args:
            df_train: 学習データ（特徴量 + ターゲット）
            target_col: ターゲット変数名
            feature_cols: 使用する特徴量カラム

        Returns:
            self
        """
        logger.info("アンサンブルモデル学習開始")

        # 1. HMMモデル学習
        logger.info("[1/2] HMMモデル学習中...")
        self.hmm_model.fit(df_train)
        logger.info("  ✓ HMMモデル学習完了")

        # 2. LightGBMモデル学習
        logger.info("[2/2] LightGBMモデル学習中...")
        X_train, _, y_train, _, feature_names = self.lgbm_model.prepare_data(
            df_train,
            target_col=target_col,
            feature_cols=feature_cols,
            test_size=0.2
        )

        # HMMの状態を特徴量として追加（オプション）
        if self.use_state_adjustment:
            states_train = self.hmm_model.predict_states(df_train)
            # データサイズを合わせる
            states_train = states_train[:len(y_train)]
            X_train = np.column_stack([X_train, states_train])
            feature_names = feature_names + ['hmm_state']

        self.lgbm_model.fit(X_train, y_train, feature_names=feature_names)
        logger.info("  ✓ LightGBMモデル学習完了")

        self.is_fitted = True
        logger.info("アンサンブルモデル学習完了")

        return self

    def predict(
        self,
        df: pd.DataFrame,
        return_probabilities: bool = False
    ) -> np.ndarray:
        """
        予測

        Args:
            df: 予測データ
            return_probabilities: 確率を返すか（Falseの場合はクラスラベル）

        Returns:
            予測結果（クラスラベルまたは確率）
        """
        if not self.is_fitted:
            raise ValueError("モデルが学習されていません。先にfit()を実行してください。")

        # HMMで市場状態を予測
        hmm_states = self.hmm_model.predict_states(df)

        # LightGBM用の特徴量を準備
        exclude_cols = ['timestamp', 'datetime', 'future_return',
                       'target_direction', 'target_binary', 'target_return',
                       'open', 'high', 'low', 'close', 'volume']
        feature_cols = [col for col in df.columns if col not in exclude_cols]
        X = df[feature_cols].values

        # データサイズ調整
        min_len = min(len(X), len(hmm_states))
        X = X[:min_len]
        hmm_states = hmm_states[:min_len]

        # HMM状態を特徴量に追加（学習時と同様）
        if self.use_state_adjustment:
            X = np.column_stack([X, hmm_states])

        # LightGBMで予測
        if return_probabilities:
            lgbm_proba = self.lgbm_model.predict_proba(X)
            return lgbm_proba
        else:
            lgbm_pred = self.lgbm_model.predict(X)
            return lgbm_pred

    def predict_with_state_info(self, df: pd.DataFrame) -> Dict:
        """
        市場状態情報付きで予測

        Args:
            df: 予測データ

        Returns:
            予測情報の辞書
        """
        if not self.is_fitted:
            raise ValueError("モデルが学習されていません。")

        # HMMで市場状態を予測
        hmm_states = self.hmm_model.predict_states(df)
        hmm_proba = self.hmm_model.predict_proba(df)

        # LightGBMで価格方向を予測
        lgbm_pred = self.predict(df, return_probabilities=False)
        lgbm_proba = self.predict(df, return_probabilities=True)

        # 最新の予測
        current_state = int(hmm_states[-1])
        current_state_label = self.hmm_model.state_labels.get(current_state, f'State_{current_state}')
        current_direction = int(lgbm_pred[-1])

        # 3クラス分類の場合
        if self.lgbm_model.n_classes == 3:
            direction_map = {0: 'Down', 1: 'Range', 2: 'Up'}
        else:
            direction_map = {0: 'Down', 1: 'Up'}

        current_direction_label = direction_map.get(current_direction, f'Class_{current_direction}')

        result = {
            'state': current_state,
            'state_label': current_state_label,
            'state_probability': float(hmm_proba[-1][current_state]),
            'direction': current_direction,
            'direction_label': current_direction_label,
            'direction_probability': float(lgbm_proba[-1][current_direction]) if self.lgbm_model.n_classes > 2 else float(lgbm_proba[-1]),
            'all_state_probabilities': hmm_proba[-1].tolist(),
            'all_direction_probabilities': lgbm_proba[-1].tolist() if self.lgbm_model.n_classes > 2 else [1-lgbm_proba[-1], lgbm_proba[-1]]
        }

        return result

    def generate_trading_signal(
        self,
        df: pd.DataFrame,
        confidence_threshold: float = 0.6
    ) -> Dict:
        """
        売買シグナルを生成

        Args:
            df: 最新データ
            confidence_threshold: 売買判断の確率閾値

        Returns:
            シグナル情報の辞書
        """
        if not self.is_fitted:
            raise ValueError("モデルが学習されていません。")

        # 予測情報取得
        pred_info = self.predict_with_state_info(df)

        # 売買シグナル判定
        signal = 'HOLD'  # デフォルトはホールド
        confidence = 0.0

        # 市場状態と方向性を総合判断
        state = pred_info['state']
        direction = pred_info['direction']
        direction_prob = pred_info['direction_probability']

        # シグナル生成ロジック
        if direction == 2 and direction_prob > confidence_threshold:  # Up予測
            # Bull状態または高確率の場合は買い
            if state >= 1 or direction_prob > 0.7:  # state 1=Range, 2=Bull
                signal = 'BUY'
                confidence = direction_prob
        elif direction == 0 and direction_prob > confidence_threshold:  # Down予測
            # Bear状態または高確率の場合は売り
            if state == 0 or direction_prob > 0.7:  # state 0=Bear
                signal = 'SELL'
                confidence = direction_prob

        result = {
            'signal': signal,
            'confidence': confidence,
            'state': pred_info['state_label'],
            'direction': pred_info['direction_label'],
            'state_prob': pred_info['state_probability'],
            'direction_prob': pred_info['direction_probability'],
            'recommendation': self._generate_recommendation(signal, confidence, pred_info)
        }

        logger.info(f"売買シグナル生成: {signal} (確信度: {confidence:.2%})")

        return result

    def _generate_recommendation(
        self,
        signal: str,
        confidence: float,
        pred_info: Dict
    ) -> str:
        """推奨アクションを生成"""
        if signal == 'BUY':
            return f"【買い推奨】市場状態: {pred_info['state_label']}, 上昇確率: {confidence:.1%}"
        elif signal == 'SELL':
            return f"【売り推奨】市場状態: {pred_info['state_label']}, 下降確率: {confidence:.1%}"
        else:
            return f"【様子見】市場状態: {pred_info['state_label']}, 方向性不明"

    def evaluate(
        self,
        df_test: pd.DataFrame,
        target_col: str = 'target_direction'
    ) -> Dict:
        """
        モデルを評価

        Args:
            df_test: テストデータ
            target_col: ターゲット変数名

        Returns:
            評価結果の辞書
        """
        if not self.is_fitted:
            raise ValueError("モデルが学習されていません。")

        # 予測
        predictions = self.predict(df_test)

        # 実際の値（LightGBMと同じラベル形式に変換）
        if target_col == 'target_direction':
            y_true_raw = df_test[target_col].values
            y_true = np.where(y_true_raw == -1, 0, np.where(y_true_raw == 0, 1, 2))
        else:
            y_true = df_test[target_col].values

        # データサイズ調整
        min_len = min(len(predictions), len(y_true))
        predictions = predictions[:min_len]
        y_true = y_true[:min_len]

        # 精度計算
        from sklearn.metrics import accuracy_score, classification_report

        accuracy = accuracy_score(y_true, predictions)

        labels = [0, 1, 2] if self.lgbm_model.n_classes == 3 else [0, 1]
        target_names = ['Down', 'Range', 'Up'] if self.lgbm_model.n_classes == 3 else ['Down', 'Up']

        report = classification_report(
            y_true, predictions,
            labels=labels,
            target_names=target_names,
            output_dict=True,
            zero_division=0
        )

        result = {
            'accuracy': accuracy,
            'classification_report': report
        }

        logger.info(f"アンサンブルモデル評価:")
        logger.info(f"  - 精度: {accuracy:.4f}")

        return result

    def save(self, filepath: str):
        """
        モデルを保存

        Args:
            filepath: 保存先パス
        """
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        # 個別モデルを保存
        hmm_path = str(Path(filepath).parent / f"{Path(filepath).stem}_hmm.pkl")
        lgbm_path = str(Path(filepath).parent / f"{Path(filepath).stem}_lgbm.pkl")

        self.hmm_model.save(hmm_path)
        self.lgbm_model.save(lgbm_path)

        # アンサンブル設定を保存
        ensemble_data = {
            'use_state_adjustment': self.use_state_adjustment,
            'is_fitted': self.is_fitted,
            'hmm_path': hmm_path,
            'lgbm_path': lgbm_path
        }

        with open(filepath, 'wb') as f:
            pickle.dump(ensemble_data, f)

        logger.info(f"アンサンブルモデル保存: {filepath}")

    def load(self, filepath: str):
        """
        モデルを読み込み

        Args:
            filepath: 読み込み元パス
        """
        with open(filepath, 'rb') as f:
            ensemble_data = pickle.load(f)

        # 個別モデルを読み込み
        self.hmm_model = MarketRegimeHMM()
        self.hmm_model.load(ensemble_data['hmm_path'])

        self.lgbm_model = PriceDirectionLGBM()
        self.lgbm_model.load(ensemble_data['lgbm_path'])

        self.use_state_adjustment = ensemble_data['use_state_adjustment']
        self.is_fitted = ensemble_data['is_fitted']

        logger.info(f"アンサンブルモデル読み込み: {filepath}")


# ヘルパー関数
def create_ensemble_model(
    n_states: int = 3,
    n_classes: int = 3,
    use_state_adjustment: bool = True
) -> EnsembleModel:
    """
    アンサンブルモデルを作成

    Args:
        n_states: HMMの状態数
        n_classes: LightGBMのクラス数
        use_state_adjustment: 状態調整を使用するか

    Returns:
        EnsembleModelインスタンス
    """
    hmm = MarketRegimeHMM(n_states=n_states)
    lgbm = PriceDirectionLGBM(n_classes=n_classes)
    return EnsembleModel(hmm, lgbm, use_state_adjustment)
