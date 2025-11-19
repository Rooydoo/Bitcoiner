"""リスク管理モジュール

段階的利益確定、ストップロス、ドローダウン管理など
"""

import logging
from typing import Dict, Optional, Tuple
from trading.position_manager import Position

logger = logging.getLogger(__name__)


class RiskManager:
    """リスク管理クラス"""

    def __init__(
        self,
        max_position_size: float = 0.95,  # 最大ポジションサイズ（資金の95%）
        stop_loss_pct: float = 10.0,      # ストップロス（-10%）
        max_drawdown_pct: float = 20.0,   # 最大ドローダウン（-20%）
        profit_taking_enabled: bool = True, # 段階的利益確定を有効化
        consecutive_loss_limit: int = 5,  # 連続損失制限
        max_daily_loss_pct: float = 5.0,  # 日次最大損失（%）
        max_weekly_loss_pct: float = 10.0, # 週次最大損失（%）
        max_monthly_loss_pct: float = 15.0 # 月次最大損失（%）
    ):
        """
        Args:
            max_position_size: 最大ポジションサイズ（0-1）
            stop_loss_pct: ストップロス率（%）
            max_drawdown_pct: 最大ドローダウン率（%）
            profit_taking_enabled: 段階的利益確定を有効化
            consecutive_loss_limit: 連続損失制限
            max_daily_loss_pct: 日次最大損失率（%）
            max_weekly_loss_pct: 週次最大損失率（%）
            max_monthly_loss_pct: 月次最大損失率（%）
        """
        self.max_position_size = max_position_size
        self.stop_loss_pct = stop_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.profit_taking_enabled = profit_taking_enabled
        self.consecutive_loss_limit = consecutive_loss_limit
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_weekly_loss_pct = max_weekly_loss_pct
        self.max_monthly_loss_pct = max_monthly_loss_pct

        # 段階的利益確定設定（要件定義書より）
        self.profit_levels = [
            {'threshold_pct': 15.0, 'close_ratio': 0.5},  # +15%で50%決済
            {'threshold_pct': 25.0, 'close_ratio': 1.0}   # +25%で残り全て決済
        ]

        # 履歴
        self.peak_equity = 0.0
        self.partial_profit_taken = {}  # symbol -> bool
        self.consecutive_losses = 0  # 連続損失カウント
        self.trading_paused = False  # 取引一時停止フラグ
        self.daily_pnl = 0.0  # 日次損益
        self.weekly_pnl = 0.0  # 週次損益
        self.monthly_pnl = 0.0  # 月次損益
        self.last_reset_day = None
        self.last_reset_week = None
        self.last_reset_month = None

        logger.info("リスク管理システム初期化")
        logger.info(f"  - ストップロス: {stop_loss_pct}%")
        logger.info(f"  - 最大ドローダウン: {max_drawdown_pct}%")
        logger.info(f"  - 段階的利益確定: {'有効' if profit_taking_enabled else '無効'}")
        logger.info(f"  - 連続損失制限: {consecutive_loss_limit}回")
        logger.info(f"  - 日次最大損失: {max_daily_loss_pct}%")
        logger.info(f"  - 週次最大損失: {max_weekly_loss_pct}%")
        logger.info(f"  - 月次最大損失: {max_monthly_loss_pct}%")

    def check_stop_loss(
        self,
        position: Position,
        current_price: float
    ) -> bool:
        """
        ストップロスをチェック

        Args:
            position: ポジション
            current_price: 現在価格

        Returns:
            ストップロスに達している場合True
        """
        pnl_pct = position.calculate_unrealized_pnl_pct(current_price)

        if pnl_pct <= -self.stop_loss_pct:
            logger.warning(f"ストップロス発動: {position.symbol} "
                         f"損失={pnl_pct:.2f}% (閾値: -{self.stop_loss_pct}%)")
            return True

        return False

    def check_profit_taking(
        self,
        position: Position,
        current_price: float
    ) -> Optional[Dict]:
        """
        段階的利益確定をチェック

        Args:
            position: ポジション
            current_price: 現在価格

        Returns:
            利益確定アクションの辞書（アクション不要の場合はNone）
        """
        if not self.profit_taking_enabled:
            return None

        pnl_pct = position.calculate_unrealized_pnl_pct(current_price)

        # 第1段階: +15%で50%決済
        if pnl_pct >= 15.0 and position.symbol not in self.partial_profit_taken:
            logger.info(f"第1段階利益確定: {position.symbol} +{pnl_pct:.2f}% - 50%決済")
            self.partial_profit_taken[position.symbol] = True

            return {
                'action': 'partial_close',
                'close_ratio': 0.5,
                'reason': f'第1段階利益確定（+{pnl_pct:.2f}%）',
                'level': 1
            }

        # 第2段階: +25%で残り全て決済
        if pnl_pct >= 25.0:
            logger.info(f"第2段階利益確定: {position.symbol} +{pnl_pct:.2f}% - 全決済")

            return {
                'action': 'full_close',
                'close_ratio': 1.0,
                'reason': f'第2段階利益確定（+{pnl_pct:.2f}%）',
                'level': 2
            }

        return None

    def check_drawdown(
        self,
        current_equity: float,
        initial_capital: float
    ) -> bool:
        """
        最大ドローダウンをチェック

        Args:
            current_equity: 現在の資産
            initial_capital: 初期資金

        Returns:
            最大ドローダウンを超えている場合True
        """
        # ピーク更新
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity

        # ドローダウン計算
        if self.peak_equity > 0:
            drawdown_pct = ((self.peak_equity - current_equity) / self.peak_equity) * 100

            if drawdown_pct >= self.max_drawdown_pct:
                logger.error(f"最大ドローダウン超過: {drawdown_pct:.2f}% "
                           f"(閾値: {self.max_drawdown_pct}%)")
                return True

        return False

    def validate_position_size(
        self,
        position_value: float,
        available_capital: float
    ) -> Tuple[bool, str]:
        """
        ポジションサイズを検証

        Args:
            position_value: ポジション金額
            available_capital: 利用可能資金

        Returns:
            (検証結果, メッセージ)
        """
        max_allowed = available_capital * self.max_position_size

        if position_value > max_allowed:
            msg = (f"ポジションサイズ超過: ¥{position_value:,.0f} > "
                  f"¥{max_allowed:,.0f} ({self.max_position_size:.0%})")
            logger.warning(msg)
            return False, msg

        return True, "OK"

    def calculate_position_size_with_risk(
        self,
        available_capital: float,
        current_price: float,
        risk_per_trade_pct: float = 2.0
    ) -> float:
        """
        リスクベースでポジションサイズを計算

        Args:
            available_capital: 利用可能資金
            current_price: 現在価格
            risk_per_trade_pct: 1トレードあたりのリスク（%）

        Returns:
            推奨ポジションサイズ（数量）
        """
        # リスク額
        risk_amount = available_capital * (risk_per_trade_pct / 100)

        # ストップロス幅
        stop_loss_price = current_price * (1 - self.stop_loss_pct / 100)
        risk_per_unit = current_price - stop_loss_price

        # ポジションサイズ
        if risk_per_unit > 0:
            quantity = risk_amount / risk_per_unit
        else:
            quantity = 0.0

        # 最大ポジションサイズで制限
        max_quantity = (available_capital * self.max_position_size) / current_price
        quantity = min(quantity, max_quantity)

        logger.info(f"リスクベースポジションサイズ: {quantity:.6f} "
                   f"(リスク額: ¥{risk_amount:,.0f})")

        return quantity

    def should_enter_trade(
        self,
        signal_confidence: float,
        min_confidence: float = 0.6,
        current_equity: Optional[float] = None,
        initial_capital: Optional[float] = None
    ) -> Tuple[bool, str]:
        """
        取引に入るべきか判定

        Args:
            signal_confidence: シグナルの確信度（0-1）
            min_confidence: 最小確信度
            current_equity: 現在の資産
            initial_capital: 初期資金

        Returns:
            (判定結果, 理由)
        """
        # 取引一時停止チェック
        is_paused, pause_reason = self.is_trading_paused()
        if is_paused:
            return False, f"取引一時停止中: {pause_reason}"

        # 期間損失制限チェック
        if initial_capital:
            period_limit_exceeded, reason = self.check_period_loss_limits(initial_capital)
            if period_limit_exceeded:
                return False, reason

        # 確信度チェック
        if signal_confidence < min_confidence:
            return False, f"確信度不足: {signal_confidence:.2%} < {min_confidence:.2%}"

        # ドローダウンチェック
        if current_equity and initial_capital:
            if self.check_drawdown(current_equity, initial_capital):
                return False, f"最大ドローダウン超過"

        return True, "OK"

    def get_exit_action(
        self,
        position: Position,
        current_price: float
    ) -> Optional[Dict]:
        """
        エグジットアクションを取得（統合チェック）

        Args:
            position: ポジション
            current_price: 現在価格

        Returns:
            アクション情報の辞書（アクション不要の場合はNone）
        """
        # ストップロスチェック
        if self.check_stop_loss(position, current_price):
            return {
                'action': 'stop_loss',
                'close_ratio': 1.0,
                'reason': f'ストップロス（{position.calculate_unrealized_pnl_pct(current_price):.2f}%）'
            }

        # 利益確定チェック
        profit_action = self.check_profit_taking(position, current_price)
        if profit_action:
            return profit_action

        return None

    def reset_profit_tracking(self, symbol: str):
        """
        利益確定トラッキングをリセット

        Args:
            symbol: 取引ペア
        """
        if symbol in self.partial_profit_taken:
            del self.partial_profit_taken[symbol]
            logger.debug(f"利益確定トラッキングリセット: {symbol}")

    def record_trade_result(self, pnl: float, initial_capital: float):
        """
        取引結果を記録し、連続損失をトラッキング

        Args:
            pnl: 実現損益
            initial_capital: 初期資本
        """
        from datetime import datetime

        pnl_pct = (pnl / initial_capital) * 100 if initial_capital > 0 else 0.0

        # 期間別PNLを更新
        self._update_period_pnl(pnl)

        # 連続損失トラッキング
        if pnl < 0:
            self.consecutive_losses += 1
            logger.warning(f"連続損失: {self.consecutive_losses}回 (制限: {self.consecutive_loss_limit}回)")

            # 連続損失制限に達した場合
            if self.consecutive_losses >= self.consecutive_loss_limit:
                self.trading_paused = True
                logger.error(f"連続損失制限到達！取引を一時停止します（{self.consecutive_losses}回連続損失）")
        else:
            # 利益が出たらリセット
            if self.consecutive_losses > 0:
                logger.info(f"連続損失リセット（前回: {self.consecutive_losses}回）")
            self.consecutive_losses = 0

    def _update_period_pnl(self, pnl: float):
        """
        期間別PNLを更新

        Args:
            pnl: 実現損益
        """
        from datetime import datetime

        now = datetime.now()
        current_day = now.date()
        current_week = now.isocalendar()[1]  # ISO週番号
        current_month = now.month

        # 日次リセット
        if self.last_reset_day != current_day:
            self.daily_pnl = 0.0
            self.last_reset_day = current_day

        # 週次リセット
        if self.last_reset_week != current_week:
            self.weekly_pnl = 0.0
            self.last_reset_week = current_week

        # 月次リセット
        if self.last_reset_month != current_month:
            self.monthly_pnl = 0.0
            self.last_reset_month = current_month

        # PNL追加
        self.daily_pnl += pnl
        self.weekly_pnl += pnl
        self.monthly_pnl += pnl

    def check_period_loss_limits(self, initial_capital: float) -> Tuple[bool, str]:
        """
        期間別損失制限をチェック

        Args:
            initial_capital: 初期資本

        Returns:
            (制限超過フラグ, 理由)
        """
        # 日次損失チェック
        daily_loss_pct = (self.daily_pnl / initial_capital) * 100 if initial_capital > 0 else 0.0
        if daily_loss_pct <= -self.max_daily_loss_pct:
            msg = f"日次損失制限超過: {daily_loss_pct:.2f}% (制限: -{self.max_daily_loss_pct}%)"
            logger.error(msg)
            self.trading_paused = True
            return True, msg

        # 週次損失チェック
        weekly_loss_pct = (self.weekly_pnl / initial_capital) * 100 if initial_capital > 0 else 0.0
        if weekly_loss_pct <= -self.max_weekly_loss_pct:
            msg = f"週次損失制限超過: {weekly_loss_pct:.2f}% (制限: -{self.max_weekly_loss_pct}%)"
            logger.error(msg)
            self.trading_paused = True
            return True, msg

        # 月次損失チェック
        monthly_loss_pct = (self.monthly_pnl / initial_capital) * 100 if initial_capital > 0 else 0.0
        if monthly_loss_pct <= -self.max_monthly_loss_pct:
            msg = f"月次損失制限超過: {monthly_loss_pct:.2f}% (制限: -{self.max_monthly_loss_pct}%)"
            logger.error(msg)
            self.trading_paused = True
            return True, msg

        return False, "OK"

    def is_trading_paused(self) -> Tuple[bool, str]:
        """
        取引が一時停止中かチェック

        Returns:
            (停止中フラグ, 理由)
        """
        if self.trading_paused:
            # 停止理由を判定
            if self.consecutive_losses >= self.consecutive_loss_limit:
                return True, f"連続損失制限到達（{self.consecutive_losses}回）"
            else:
                return True, "損失制限超過"

        return False, "OK"

    def resume_trading(self):
        """取引を再開"""
        self.trading_paused = False
        self.consecutive_losses = 0
        logger.info("取引再開")

    def get_risk_metrics(self) -> Dict:
        """
        リスク指標を取得

        Returns:
            リスク指標の辞書
        """
        return {
            'max_position_size': self.max_position_size,
            'stop_loss_pct': self.stop_loss_pct,
            'max_drawdown_pct': self.max_drawdown_pct,
            'profit_taking_enabled': self.profit_taking_enabled,
            'peak_equity': self.peak_equity,
            'profit_levels': self.profit_levels
        }


# ヘルパー関数
def create_risk_manager(
    max_position_size: float = 0.95,
    stop_loss_pct: float = 10.0,
    max_drawdown_pct: float = 20.0
) -> RiskManager:
    """
    リスク管理インスタンスを作成

    Args:
        max_position_size: 最大ポジションサイズ
        stop_loss_pct: ストップロス率
        max_drawdown_pct: 最大ドローダウン率

    Returns:
        RiskManagerインスタンス
    """
    return RiskManager(max_position_size, stop_loss_pct, max_drawdown_pct)
