"""アンサンブルモデル - HMM + LightGBM統合

HMMで市場状態を分類し、LightGBMで価格方向を予測する統合モデル
押し目買い（下がり待ち）ロジック搭載
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, Tuple, Optional, List
from datetime import datetime, timedelta
import joblib
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
        use_state_adjustment: bool = True,
        wait_for_dip: bool = True
    ):
        """
        初期化

        Args:
            hmm_model: HMMモデル（Noneの場合は新規作成）
            lgbm_model: LightGBMモデル（Noneの場合は新規作成）
            use_state_adjustment: 市場状態に応じた予測調整を使用するか
            wait_for_dip: 押し目待ちモードを有効化するか
        """
        self.hmm_model = hmm_model or MarketRegimeHMM(n_states=3)
        self.lgbm_model = lgbm_model or PriceDirectionLGBM(n_classes=3)
        self.use_state_adjustment = use_state_adjustment
        self.wait_for_dip = wait_for_dip

        self.is_fitted = False

        # 押し目待ちモード用の待機シグナル管理
        self.pending_signals: Dict[str, Dict] = {}

        # 押し目判定パラメータ
        self.dip_config = {
            'rsi_threshold': 40,           # RSI < 40 で押し目と判定
            'sma_distance_threshold': 0,   # 20日MAを下回ったら押し目
            'return_5d_threshold': -0.03,  # 5日で3%以上下落
            'signal_expiry_hours': 48,     # 待機シグナルの有効期限（時間）
            'strong_signal_threshold': 0.75  # 強シグナル閾値（即買い）
        }

        logger.info("アンサンブルモデル初期化")
        logger.info(f"  - HMM状態数: {self.hmm_model.n_states}")
        logger.info(f"  - LightGBMクラス数: {self.lgbm_model.n_classes}")
        logger.info(f"  - 状態調整: {use_state_adjustment}")
        logger.info(f"  - 押し目待ちモード: {wait_for_dip}")

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

    def _check_dip_condition(self, df: pd.DataFrame) -> Tuple[bool, str]:
        """
        押し目（買い場）条件をチェック

        Args:
            df: 最新データ

        Returns:
            (押し目かどうか, 理由)
        """
        reasons = []

        # RSIチェック
        if 'rsi' in df.columns:
            current_rsi = df['rsi'].iloc[-1]
            if current_rsi < self.dip_config['rsi_threshold']:
                reasons.append(f"RSI={current_rsi:.1f}<{self.dip_config['rsi_threshold']}")

        # 20日MA乖離チェック
        if 'sma20_distance' in df.columns:
            sma_dist = df['sma20_distance'].iloc[-1]
            if sma_dist < self.dip_config['sma_distance_threshold']:
                reasons.append(f"MA乖離={sma_dist:.2%}")

        # 5日リターンチェック
        if 'return_5' in df.columns:
            ret_5d = df['return_5'].iloc[-1]
            if ret_5d < self.dip_config['return_5d_threshold']:
                reasons.append(f"5日変化={ret_5d:.2%}")

        is_dip = len(reasons) >= 1  # 1つ以上の条件を満たせば押し目
        reason_str = ", ".join(reasons) if reasons else "条件なし"

        return is_dip, reason_str

    def _check_high_zone(self, df: pd.DataFrame) -> Tuple[bool, str]:
        """
        高値圏かどうかをチェック（押し目待ちすべきか判定）

        Args:
            df: 最新データ

        Returns:
            (高値圏かどうか, 理由)
        """
        reasons = []

        # RSIが高い
        if 'rsi' in df.columns:
            current_rsi = df['rsi'].iloc[-1]
            if current_rsi > 60:
                reasons.append(f"RSI={current_rsi:.1f}>60")

        # MAを大きく上回っている
        if 'sma20_distance' in df.columns:
            sma_dist = df['sma20_distance'].iloc[-1]
            if sma_dist > 0.02:  # 2%以上上
                reasons.append(f"MA+{sma_dist:.2%}")

        # 直近で上がりすぎ
        if 'return_5' in df.columns:
            ret_5d = df['return_5'].iloc[-1]
            if ret_5d > 0.03:  # 5日で3%以上上昇
                reasons.append(f"5日+{ret_5d:.2%}")

        is_high = len(reasons) >= 2  # 2つ以上で高値圏判定
        reason_str = ", ".join(reasons) if reasons else ""

        return is_high, reason_str

    def _cleanup_expired_signals(self):
        """期限切れの待機シグナルを削除"""
        now = datetime.now()
        expired = []

        for symbol, sig in self.pending_signals.items():
            age_hours = (now - sig['timestamp']).total_seconds() / 3600
            if age_hours > self.dip_config['signal_expiry_hours']:
                expired.append(symbol)

        for symbol in expired:
            logger.info(f"待機シグナル期限切れ: {symbol} (発生から{self.dip_config['signal_expiry_hours']}時間経過)")
            del self.pending_signals[symbol]

    def generate_trading_signal(
        self,
        df: pd.DataFrame,
        confidence_threshold: float = 0.6,
        symbol: str = 'BTC/JPY'
    ) -> Dict:
        """
        売買シグナルを生成（押し目待ちモード対応）

        Args:
            df: 最新データ
            confidence_threshold: 売買判断の確率閾値
            symbol: 取引ペア

        Returns:
            シグナル情報の辞書
        """
        if not self.is_fitted:
            raise ValueError("モデルが学習されていません。")

        # 期限切れシグナルを削除
        self._cleanup_expired_signals()

        # 予測情報取得
        pred_info = self.predict_with_state_info(df)

        # 基本変数
        signal = 'HOLD'
        confidence = 0.0
        entry_type = 'none'

        state = pred_info['state']
        direction = pred_info['direction']
        direction_prob = pred_info['direction_probability']

        # 押し目条件チェック
        is_dip, dip_reason = self._check_dip_condition(df)
        is_high, high_reason = self._check_high_zone(df)

        # ========== 買いシグナル判定 ==========
        if direction == 2 and direction_prob > confidence_threshold:  # Up予測
            if state >= 1 or direction_prob > 0.7:

                # --- 強シグナル：即買い（押し目待たない）---
                if direction_prob >= self.dip_config['strong_signal_threshold']:
                    signal = 'BUY'
                    confidence = direction_prob
                    entry_type = 'strong_signal'
                    logger.info(f"強シグナル即買い: {symbol} prob={direction_prob:.2%}")

                # --- 押し目待ちモード ---
                elif self.wait_for_dip:

                    # 今が押し目なら買い
                    if is_dip:
                        signal = 'BUY'
                        confidence = direction_prob * 1.05  # 押し目ボーナス
                        entry_type = 'dip_buy'
                        logger.info(f"押し目買い: {symbol} ({dip_reason})")

                        # 待機シグナルがあれば消化
                        if symbol in self.pending_signals:
                            del self.pending_signals[symbol]

                    # 高値圏なら待機リストに追加
                    elif is_high:
                        if symbol not in self.pending_signals:
                            self.pending_signals[symbol] = {
                                'timestamp': datetime.now(),
                                'probability': direction_prob,
                                'state': state,
                                'price_level': df['close'].iloc[-1] if 'close' in df.columns else 0
                            }
                            logger.info(f"待機シグナル追加: {symbol} prob={direction_prob:.2%} ({high_reason})")
                        signal = 'HOLD'
                        entry_type = 'waiting_for_dip'

                    # 中立圏：普通に買い
                    else:
                        signal = 'BUY'
                        confidence = direction_prob
                        entry_type = 'normal'

                # --- 押し目待ちモード無効時 ---
                else:
                    signal = 'BUY'
                    confidence = direction_prob
                    entry_type = 'normal'

        # ========== 待機シグナル消化チェック ==========
        elif symbol in self.pending_signals and is_dip:
            pending = self.pending_signals[symbol]
            age_hours = (datetime.now() - pending['timestamp']).total_seconds() / 3600

            # 待機シグナルがあり、押し目になったら買い
            signal = 'BUY'
            confidence = pending['probability'] * 1.05
            entry_type = 'pending_dip_buy'
            logger.info(f"待機シグナル発動: {symbol} ({dip_reason}) 待機{age_hours:.1f}時間")
            del self.pending_signals[symbol]

        # ========== 売りシグナル判定 ==========
        elif direction == 0 and direction_prob > confidence_threshold:  # Down予測
            if state == 0 or direction_prob > 0.7:
                signal = 'SELL'
                confidence = direction_prob
                entry_type = 'sell_signal'

        # 結果作成
        result = {
            'signal': signal,
            'confidence': confidence,
            'state': pred_info['state_label'],
            'direction': pred_info['direction_label'],
            'state_prob': pred_info['state_probability'],
            'direction_prob': pred_info['direction_probability'],
            'entry_type': entry_type,
            'is_dip': is_dip,
            'dip_reason': dip_reason if is_dip else '',
            'pending_signals': len(self.pending_signals),
            'recommendation': self._generate_recommendation(signal, confidence, pred_info, entry_type)
        }

        logger.info(f"売買シグナル: {signal} (確信度: {confidence:.2%}, タイプ: {entry_type})")

        return result

    def _generate_recommendation(
        self,
        signal: str,
        confidence: float,
        pred_info: Dict,
        entry_type: str = 'normal'
    ) -> str:
        """推奨アクションを生成"""
        if signal == 'BUY':
            type_desc = {
                'strong_signal': '強シグナル',
                'dip_buy': '押し目買い',
                'pending_dip_buy': '待機→押し目買い',
                'normal': '通常'
            }.get(entry_type, '')

            return f"【買い推奨】{type_desc} 市場: {pred_info['state_label']}, 確率: {confidence:.1%}"
        elif signal == 'SELL':
            return f"【売り推奨】市場状態: {pred_info['state_label']}, 下降確率: {confidence:.1%}"
        elif entry_type == 'waiting_for_dip':
            return f"【押し目待ち】上昇予測あり、下がりを待機中 ({len(self.pending_signals)}件待機)"
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

        joblib.dump(ensemble_data, filepath, compress=3)

        logger.info(f"アンサンブルモデル保存: {filepath}")

    def load(self, filepath: str):
        """
        モデルを読み込み

        Args:
            filepath: 読み込み元パス
        """
        ensemble_data = joblib.load(filepath)

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
    use_state_adjustment: bool = True,
    wait_for_dip: bool = True
) -> EnsembleModel:
    """
    アンサンブルモデルを作成

    Args:
        n_states: HMMの状態数
        n_classes: LightGBMのクラス数
        use_state_adjustment: 状態調整を使用するか
        wait_for_dip: 押し目待ちモードを使用するか

    Returns:
        EnsembleModelインスタンス
    """
    hmm = MarketRegimeHMM(n_states=n_states)
    lgbm = PriceDirectionLGBM(n_classes=n_classes)
    return EnsembleModel(hmm, lgbm, use_state_adjustment, wait_for_dip)
