"""設定ファイルバリデーション

config.yamlの値の妥当性をチェック
"""

import sys
from pathlib import Path
from typing import List, Tuple, Dict, Any
import yaml

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.config_loader import ConfigLoader


class ConfigValidator:
    """設定ファイルバリデータークラス"""

    def __init__(self, config_path: str = "config/config.yaml"):
        """
        Args:
            config_path: 設定ファイルパス
        """
        self.config_path = Path(config_path)
        self.errors: List[str] = []
        self.warnings: List[str] = []

        try:
            self.config = ConfigLoader(str(config_path))
        except Exception as e:
            self.errors.append(f"設定ファイル読み込みエラー: {e}")
            self.config = None

    def validate_all(self) -> Tuple[bool, List[str], List[str]]:
        """
        全ての設定を検証

        Returns:
            (検証成功, エラーリスト, 警告リスト)
        """
        self.errors = []
        self.warnings = []

        if not self.config:
            return False, self.errors, self.warnings

        # 各セクションの検証
        self._validate_trading()
        self._validate_risk_management()
        self._validate_trading_pairs()
        self._validate_ml_config()
        self._validate_strategy_allocation()

        is_valid = len(self.errors) == 0
        return is_valid, self.errors, self.warnings

    def _validate_trading(self):
        """取引設定の検証"""
        # 初期資本
        initial_capital = self.config.get('trading.initial_capital')
        if not initial_capital:
            self.errors.append("trading.initial_capital が設定されていません")
        elif initial_capital < 10000:
            self.warnings.append(f"trading.initial_capital が少なすぎます: ¥{initial_capital:,}（推奨: ¥100,000以上）")
        elif initial_capital < 100000:
            self.warnings.append(f"trading.initial_capital: ¥{initial_capital:,}（推奨: ¥200,000以上）")

        # 最小信頼度
        min_confidence = self.config.get('trading.min_confidence')
        if not min_confidence:
            self.errors.append("trading.min_confidence が設定されていません")
        elif not (0.0 < min_confidence <= 1.0):
            self.errors.append(f"trading.min_confidence は0.0-1.0の範囲で設定してください: {min_confidence}")
        elif min_confidence < 0.5:
            self.warnings.append(f"trading.min_confidence が低すぎます: {min_confidence}（推奨: 0.6以上）")

        # 取引間隔
        interval = self.config.get('trading.trading_interval_minutes')
        if not interval:
            self.warnings.append("trading.trading_interval_minutes が設定されていません（デフォルト: 5分）")
        elif interval < 1:
            self.errors.append(f"trading.trading_interval_minutes は1分以上で設定してください: {interval}")
        elif interval > 60:
            self.warnings.append(f"trading.trading_interval_minutes が長すぎます: {interval}分")

    def _validate_risk_management(self):
        """リスク管理設定の検証"""
        # ストップロス
        stop_loss = self.config.get('risk_management.stop_loss_pct')
        if not stop_loss:
            self.errors.append("risk_management.stop_loss_pct が設定されていません")
        elif not (1.0 <= stop_loss <= 50.0):
            self.errors.append(f"risk_management.stop_loss_pct は1.0-50.0%の範囲で設定してください: {stop_loss}%")
        elif stop_loss < 5.0:
            self.warnings.append(f"risk_management.stop_loss_pct が厳しすぎます: {stop_loss}%（推奨: 5-15%）")
        elif stop_loss > 20.0:
            self.warnings.append(f"risk_management.stop_loss_pct が緩すぎます: {stop_loss}%（推奨: 5-15%）")

        # 利益確定レベル
        take_profit_first = self.config.get('risk_management.take_profit_first')
        take_profit_second = self.config.get('risk_management.take_profit_second')

        if not take_profit_first:
            self.errors.append("risk_management.take_profit_first が設定されていません")
        elif take_profit_first < 5.0:
            self.warnings.append(f"risk_management.take_profit_first が低すぎます: {take_profit_first}%")

        if not take_profit_second:
            self.errors.append("risk_management.take_profit_second が設定されていません")
        elif take_profit_second <= take_profit_first:
            self.errors.append(
                f"risk_management.take_profit_second ({take_profit_second}%) は "
                f"take_profit_first ({take_profit_first}%) より大きくしてください"
            )

        # 最大ドローダウン
        max_dd = self.config.get('risk_management.max_drawdown_pct')
        if not max_dd:
            self.warnings.append("risk_management.max_drawdown_pct が設定されていません（デフォルト: 20%）")
        elif not (5.0 <= max_dd <= 50.0):
            self.errors.append(f"risk_management.max_drawdown_pct は5.0-50.0%の範囲で設定してください: {max_dd}%")

        # ポジションサイズ
        max_position = self.config.get('risk_management.max_position_size')
        if max_position and not (0.1 <= max_position <= 1.0):
            self.errors.append(f"risk_management.max_position_size は0.1-1.0の範囲で設定してください: {max_position}")

    def _validate_trading_pairs(self):
        """取引ペア設定の検証"""
        pairs = self.config.get('trading_pairs', [])

        if not pairs:
            self.errors.append("trading_pairs が設定されていません")
            return

        if not isinstance(pairs, list):
            self.errors.append("trading_pairs はリスト形式で設定してください")
            return

        total_allocation = 0.0

        for i, pair in enumerate(pairs):
            # シンボル確認
            symbol = pair.get('symbol')
            if not symbol:
                self.errors.append(f"trading_pairs[{i}]: symbol が設定されていません")
                continue

            # 対応ペアチェック
            supported_pairs = ['BTC/JPY', 'ETH/JPY']
            if symbol not in supported_pairs:
                self.warnings.append(
                    f"trading_pairs[{i}]: {symbol} は未テストです（対応ペア: {', '.join(supported_pairs)}）"
                )

            # アロケーション確認
            allocation = pair.get('allocation')
            if allocation is None:
                self.errors.append(f"trading_pairs[{i}]: allocation が設定されていません")
            elif not (0.0 < allocation <= 1.0):
                self.errors.append(f"trading_pairs[{i}]: allocation は0.0-1.0の範囲で設定してください: {allocation}")
            else:
                total_allocation += allocation

        # 合計アロケーション確認
        if abs(total_allocation - 1.0) > 0.01:
            self.warnings.append(
                f"trading_pairs の allocation 合計が1.0ではありません: {total_allocation:.2f}"
            )

    def _validate_ml_config(self):
        """機械学習設定の検証"""
        # 学習期間
        initial_days = self.config.get('machine_learning.initial_training_days')
        if initial_days and initial_days < 30:
            self.warnings.append(
                f"machine_learning.initial_training_days が短すぎます: {initial_days}日（推奨: 365日以上）"
            )

        # 再学習間隔
        retrain_days = self.config.get('machine_learning.retrain_interval_days')
        if retrain_days and retrain_days < 1:
            self.errors.append(f"machine_learning.retrain_interval_days は1日以上で設定してください: {retrain_days}")

        # LightGBM設定
        num_threads = self.config.get('machine_learning.lightgbm.num_threads')
        if num_threads and num_threads < 1:
            self.errors.append(f"machine_learning.lightgbm.num_threads は1以上で設定してください: {num_threads}")
        elif num_threads and num_threads > 16:
            self.warnings.append(f"machine_learning.lightgbm.num_threads が多すぎます: {num_threads}")

    def _validate_strategy_allocation(self):
        """戦略配分設定の検証"""
        alloc = self.config.get('strategy_allocation', {})

        if not alloc:
            self.warnings.append("strategy_allocation が設定されていません（デフォルト値使用）")
            return

        # crypto_ratio検証
        crypto_ratio = alloc.get('crypto_ratio')
        if crypto_ratio is not None:
            if not (0.0 <= crypto_ratio <= 1.0):
                self.errors.append(
                    f"strategy_allocation.crypto_ratio は0.0-1.0の範囲で設定してください: {crypto_ratio}"
                )
            elif crypto_ratio > 0.9:
                self.warnings.append(
                    f"strategy_allocation.crypto_ratio が高すぎます: {crypto_ratio:.0%}（推奨: 80%以下）"
                )

        # trend_ratio検証
        trend_ratio = alloc.get('trend_ratio')
        if trend_ratio is not None:
            if not (0.0 <= trend_ratio <= 1.0):
                self.errors.append(
                    f"strategy_allocation.trend_ratio は0.0-1.0の範囲で設定してください: {trend_ratio}"
                )

        # cointegration_ratio検証
        coint_ratio = alloc.get('cointegration_ratio')
        if coint_ratio is not None:
            if not (0.0 <= coint_ratio <= 1.0):
                self.errors.append(
                    f"strategy_allocation.cointegration_ratio は0.0-1.0の範囲で設定してください: {coint_ratio}"
                )

        # 戦略比率の合計チェック
        if trend_ratio is not None and coint_ratio is not None:
            total_strategy = trend_ratio + coint_ratio
            if total_strategy > 1.0:
                self.warnings.append(
                    f"strategy_allocation の trend_ratio + cointegration_ratio が1.0を超えています: "
                    f"{trend_ratio} + {coint_ratio} = {total_strategy:.2f}"
                )
            elif total_strategy < 0.5:
                self.warnings.append(
                    f"strategy_allocation の戦略配分が低すぎます: "
                    f"trend={trend_ratio:.0%} + coint={coint_ratio:.0%} = {total_strategy:.0%}"
                )

    def print_validation_result(self, is_valid: bool, errors: List[str], warnings: List[str]):
        """
        検証結果を表示

        Args:
            is_valid: 検証成功フラグ
            errors: エラーリスト
            warnings: 警告リスト
        """
        print("\n" + "=" * 60)
        print("設定ファイル検証結果")
        print("=" * 60)

        if errors:
            print("\n❌ エラー:")
            for i, error in enumerate(errors, 1):
                print(f"  {i}. {error}")

        if warnings:
            print("\n⚠️  警告:")
            for i, warning in enumerate(warnings, 1):
                print(f"  {i}. {warning}")

        if is_valid:
            if not warnings:
                print("\n✅ 全ての検証に合格しました")
            else:
                print("\n✅ 必須項目の検証に合格しました（警告あり）")
        else:
            print("\n❌ 検証に失敗しました")
            print("\n対処方法:")
            print("  1. config/config.yaml を編集")
            print("  2. 設定値を修正")
            print("  3. 再度起動")

        print("=" * 60 + "\n")


def validate_config(config_path: str = "config/config.yaml", exit_on_error: bool = True) -> bool:
    """
    設定ファイルを検証（簡易インターフェース）

    Args:
        config_path: 設定ファイルパス
        exit_on_error: エラー時に終了するか

    Returns:
        検証成功フラグ
    """
    validator = ConfigValidator(config_path)
    is_valid, errors, warnings = validator.validate_all()
    validator.print_validation_result(is_valid, errors, warnings)

    if not is_valid and exit_on_error:
        print("設定ファイルを修正してから再度起動してください。")
        sys.exit(1)

    return is_valid


# テスト実行
if __name__ == "__main__":
    validate_config(exit_on_error=False)
