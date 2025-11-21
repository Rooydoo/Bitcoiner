"""LightGBMモデル - 価格方向予測

価格の方向性（上昇/下降/横ばい）を予測する勾配ブースティングモデル
"""

import numpy as np
import pandas as pd
import logging
from typing import Tuple, List, Optional, Dict, Union
import pickle
from pathlib import Path
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

logger = logging.getLogger(__name__)


class PriceDirectionLGBM:
    """価格方向を予測するLightGBMモデル"""

    def __init__(
        self,
        n_classes: int = 3,
        params: Optional[Dict] = None,
        random_state: int = 42
    ):
        """
        初期化

        Args:
            n_classes: クラス数（2: 上昇/下降、3: 上昇/横ばい/下降）
            params: LightGBMパラメータ
            random_state: 乱数シード
        """
        self.n_classes = n_classes
        self.random_state = random_state

        # デフォルトパラメータ（リソース効率重視）
        default_params = {
            'objective': 'multiclass' if n_classes > 2 else 'binary',
            'num_class': n_classes if n_classes > 2 else None,
            'metric': 'multi_logloss' if n_classes > 2 else 'binary_logloss',
            'boosting_type': 'gbdt',
            'num_threads': 2,  # VPS 2コア対応
            'max_depth': 8,
            'num_leaves': 31,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'min_data_in_leaf': 20,
            'verbosity': -1,
            'seed': random_state
        }

        # ユーザー指定パラメータで上書き
        if params:
            default_params.update(params)

        self.params = default_params
        self.model = None
        self.feature_names = []
        self.feature_importance = {}
        self.is_fitted = False

        logger.info(f"LightGBMモデル初期化: {n_classes}クラス分類")

    def prepare_data(
        self,
        df: pd.DataFrame,
        target_col: str = 'target_direction',
        feature_cols: Optional[List[str]] = None,
        test_size: float = 0.2
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, List[str]]:
        """
        学習用データを準備

        Args:
            df: 特徴量データ
            target_col: ターゲット変数カラム名
            feature_cols: 使用する特徴量カラム（Noneの場合は自動選択）
            test_size: テストデータの割合

        Returns:
            X_train, X_test, y_train, y_test, feature_names
        """
        # 特徴量カラムの選択
        if feature_cols is None:
            # 自動選択: timestamp, target関連カラムを除外
            exclude_cols = ['timestamp', 'datetime', 'future_return',
                          'target_direction', 'target_binary', 'target_return',
                          'open', 'high', 'low', 'close', 'volume']
            feature_cols = [col for col in df.columns if col not in exclude_cols]

        # 欠損値確認
        if df[feature_cols].isnull().any().any():
            logger.warning("特徴量に欠損値あり - 削除します")
            df = df.dropna(subset=feature_cols)

        # ターゲット変数の調整
        if target_col == 'target_direction':
            # LightGBMは0から始まる連続したラベルが必要
            # -1, 0, 1 → 0, 1, 2
            y_raw = df[target_col].values
            y = np.where(y_raw == -1, 0, np.where(y_raw == 0, 1, 2))

            if self.n_classes == 2:
                # 2クラスの場合: 横ばいを上昇に含める
                # 0(下降), 1,2(横ばい・上昇) → 0, 1
                y = (y_raw >= 0).astype(int)
        else:
            y = df[target_col].values

        X = df[feature_cols].values

        # Train/Testデータ分割
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=self.random_state, shuffle=False
        )

        logger.info(f"データ準備完了: Train={len(X_train)}, Test={len(X_test)}, Features={len(feature_cols)}")

        return X_train, X_test, y_train, y_test, feature_cols

    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: Optional[np.ndarray] = None,
        y_val: Optional[np.ndarray] = None,
        feature_names: Optional[List[str]] = None,
        num_boost_round: int = 500,
        early_stopping_rounds: int = 50
    ) -> 'PriceDirectionLGBM':
        """
        モデルを学習

        Args:
            X_train: 学習データ特徴量
            y_train: 学習データターゲット
            X_val: 検証データ特徴量（Noneの場合は訓練データの一部を使用）
            y_val: 検証データターゲット
            feature_names: 特徴量名リスト
            num_boost_round: ブースティングの回数
            early_stopping_rounds: Early Stoppingのラウンド数

        Returns:
            self
        """
        logger.info("LightGBMモデル学習開始")

        # 検証データがない場合は分割
        if X_val is None or y_val is None:
            X_train, X_val, y_train, y_val = train_test_split(
                X_train, y_train, test_size=0.2, random_state=self.random_state
            )

        # LightGBM Dataset作成
        train_data = lgb.Dataset(X_train, label=y_train, feature_name=feature_names)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

        # 学習
        self.model = lgb.train(
            self.params,
            train_data,
            num_boost_round=num_boost_round,
            valid_sets=[train_data, val_data],
            valid_names=['train', 'valid'],
            callbacks=[
                lgb.early_stopping(stopping_rounds=early_stopping_rounds, verbose=False),
                lgb.log_evaluation(period=0)  # ログ出力抑制
            ]
        )

        self.is_fitted = True
        self.feature_names = feature_names or [f'f{i}' for i in range(X_train.shape[1])]

        # 特徴量重要度
        self._calculate_feature_importance()

        logger.info(f"LightGBMモデル学習完了")
        logger.info(f"  - Best iteration: {self.model.best_iteration}")
        logger.info(f"  - Best score: {self.model.best_score['valid'][list(self.model.best_score['valid'].keys())[0]]:.4f}")

        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        予測（クラスラベル）

        Args:
            X: 特徴量

        Returns:
            予測クラスラベル
        """
        if not self.is_fitted:
            raise ValueError("モデルが学習されていません。先にfit()を実行してください。")

        y_pred_proba = self.model.predict(X)

        if self.n_classes > 2:
            # マルチクラス: 最大確率のクラスを選択
            y_pred = np.argmax(y_pred_proba, axis=1)
        else:
            # バイナリ: 0.5で閾値
            y_pred = (y_pred_proba > 0.5).astype(int)

        return y_pred

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        予測確率

        Args:
            X: 特徴量

        Returns:
            予測確率（マルチクラス: (n_samples, n_classes), バイナリ: (n_samples,)）
        """
        if not self.is_fitted:
            raise ValueError("モデルが学習されていません。先にfit()を実行してください。")

        return self.model.predict(X)

    def evaluate(self, X_test: np.ndarray, y_test: np.ndarray) -> Dict:
        """
        モデルを評価

        Args:
            X_test: テストデータ特徴量
            y_test: テストデータターゲット

        Returns:
            評価指標の辞書
        """
        if not self.is_fitted:
            raise ValueError("モデルが学習されていません。")

        y_pred = self.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)

        # クラスラベル
        if self.n_classes == 2:
            labels = [0, 1]
            target_names = ['Down', 'Up']
        else:
            labels = [0, 1, 2]
            target_names = ['Down', 'Range', 'Up']

        # 分類レポート
        report = classification_report(y_test, y_pred, labels=labels,
                                      target_names=target_names, output_dict=True, zero_division=0)

        # 混同行列
        cm = confusion_matrix(y_test, y_pred, labels=labels)

        result = {
            'accuracy': accuracy,
            'classification_report': report,
            'confusion_matrix': cm.tolist()
        }

        logger.info(f"モデル評価結果:")
        logger.info(f"  - Accuracy: {accuracy:.4f}")
        for label in target_names:
            if label in report:
                logger.info(f"  - {label} F1-score: {report[label]['f1-score']:.4f}")

        return result

    def _calculate_feature_importance(self):
        """特徴量重要度を計算"""
        if not self.is_fitted:
            return

        importance_gain = self.model.feature_importance(importance_type='gain')
        importance_split = self.model.feature_importance(importance_type='split')

        self.feature_importance = {
            name: {
                'gain': float(gain),
                'split': int(split)
            }
            for name, gain, split in zip(self.feature_names, importance_gain, importance_split)
        }

        # 重要度でソート
        sorted_importance = sorted(
            self.feature_importance.items(),
            key=lambda x: x[1]['gain'],
            reverse=True
        )

        logger.info("Top 10特徴量重要度:")
        for i, (name, imp) in enumerate(sorted_importance[:10], 1):
            logger.info(f"  {i:2d}. {name:30s} (gain: {imp['gain']:.2f})")

    def get_feature_importance(self, top_n: int = 20) -> Dict:
        """
        特徴量重要度を取得

        Args:
            top_n: 上位何個取得するか

        Returns:
            特徴量重要度の辞書
        """
        if not self.is_fitted:
            raise ValueError("モデルが学習されていません。")

        sorted_importance = sorted(
            self.feature_importance.items(),
            key=lambda x: x[1]['gain'],
            reverse=True
        )

        return dict(sorted_importance[:top_n])

    def save(self, filepath: str):
        """
        モデルを保存

        Args:
            filepath: 保存先パス
        """
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)

        model_data = {
            'model': self.model,
            'params': self.params,
            'n_classes': self.n_classes,
            'feature_names': self.feature_names,
            'feature_importance': self.feature_importance,
            'is_fitted': self.is_fitted
        }

        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)

        logger.info(f"LightGBMモデル保存: {filepath}")

    def load(self, filepath: str):
        """
        モデルを読み込み

        Args:
            filepath: 読み込み元パス
        """
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)

        self.model = model_data['model']
        self.params = model_data['params']
        self.n_classes = model_data['n_classes']
        self.feature_names = model_data['feature_names']
        self.feature_importance = model_data['feature_importance']
        self.is_fitted = model_data['is_fitted']

        logger.info(f"LightGBMモデル読み込み: {filepath}")

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
            'n_classes': self.n_classes,
            'n_features': len(self.feature_names),
            'best_iteration': self.model.best_iteration,
            'params': self.params,
            'top_features': list(self.get_feature_importance(top_n=10).keys())
        }

        return summary


# ヘルパー関数
def create_lightgbm_model(
    n_classes: int = 3,
    params: Optional[Dict] = None
) -> PriceDirectionLGBM:
    """
    LightGBMモデルを作成

    Args:
        n_classes: クラス数
        params: カスタムパラメータ

    Returns:
        PriceDirectionLGBMインスタンス
    """
    return PriceDirectionLGBM(n_classes=n_classes, params=params)
