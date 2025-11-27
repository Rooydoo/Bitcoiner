"""ポジション管理システム

現在のポジション、損益、エントリー/エグジット管理
"""

import logging
from typing import Dict, Optional, List
from datetime import datetime
from data.storage.sqlite_manager import SQLiteManager

logger = logging.getLogger(__name__)


class Position:
    """ポジションクラス"""

    def __init__(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        entry_time: Optional[datetime] = None,
        position_id: Optional[str] = None,
        leverage: float = 1.0,
        margin: float = 0.0
    ):
        """
        Args:
            symbol: 取引ペア
            side: 'long' または 'short'
            entry_price: エントリー価格
            quantity: 数量
            entry_time: エントリー時刻
            position_id: ポジションID
            leverage: レバレッジ倍率（デフォルト: 1.0 = 現物）
            margin: 使用証拠金（レバレッジ取引時）
        """
        import uuid
        self.position_id = position_id or str(uuid.uuid4())
        self.symbol = symbol
        self.side = side
        self.entry_price = entry_price
        self.quantity = quantity
        self.entry_time = entry_time or datetime.now()
        self.exit_price = None
        self.exit_time = None
        self.realized_pnl = 0.0
        self.status = 'open'  # 'open', 'closed'

        # レバレッジ関連
        self.leverage = max(1.0, leverage)  # 最低1倍
        self.margin = margin if margin > 0 else (entry_price * quantity) / self.leverage
        self.is_leveraged = self.leverage > 1.0 or symbol.startswith('FX_')

    def calculate_unrealized_pnl(self, current_price: float, commission_rate: float = 0.0015) -> float:
        """
        未実現損益を計算（手数料考慮）

        Args:
            current_price: 現在価格
            commission_rate: 取引手数料率（デフォルト: 0.15%）

        Returns:
            未実現損益（手数料控除後）

        Note:
            エントリー時の手数料は注文執行時にbitFlyerで既に差し引かれているため、
            ここでは決済時の手数料（見込み）のみを考慮する。
            エントリー手数料を再度差し引くと二重計算になる。
        """
        if self.side == 'long':
            pnl = (current_price - self.entry_price) * self.quantity
        else:  # short
            pnl = (self.entry_price - current_price) * self.quantity

        # 決済時手数料のみ考慮（エントリー時手数料は既に支払い済みのため除外）
        exit_fee = current_price * self.quantity * commission_rate

        # 手数料を差し引いた実質PnL
        pnl_after_fees = pnl - exit_fee

        return pnl_after_fees

    def calculate_unrealized_pnl_pct(self, current_price: float) -> float:
        """
        未実現損益率（%）を計算

        Args:
            current_price: 現在価格

        Returns:
            損益率（%）
        """
        pnl = self.calculate_unrealized_pnl(current_price)
        invested_capital = self.entry_price * self.quantity

        return (pnl / invested_capital) * 100 if invested_capital > 0 else 0.0

    def close(self, exit_price: float, exit_time: Optional[datetime] = None):
        """
        ポジションをクローズ

        Args:
            exit_price: 決済価格
            exit_time: 決済時刻
        """
        self.exit_price = exit_price
        self.exit_time = exit_time or datetime.now()
        self.realized_pnl = self.calculate_unrealized_pnl(exit_price)
        self.status = 'closed'

        logger.info(f"ポジションクローズ: {self.symbol} {self.side.upper()} "
                   f"損益=¥{self.realized_pnl:,.0f} ({self.calculate_unrealized_pnl_pct(exit_price):.2f}%)")

    def calculate_margin_ratio(self, current_price: float) -> float:
        """
        証拠金維持率を計算（レバレッジ取引用）

        Args:
            current_price: 現在価格

        Returns:
            証拠金維持率（1.0 = 100%）
        """
        if not self.is_leveraged or self.margin <= 0:
            return 1.0  # 現物は常に100%

        # entry_priceが無効な場合のガード
        if self.entry_price <= 0:
            return 1.0

        # 未実現損益（率）
        if self.side == 'long':
            pnl_ratio = (current_price - self.entry_price) / self.entry_price
        else:
            pnl_ratio = (self.entry_price - current_price) / self.entry_price

        # 証拠金維持率 = (証拠金 + 評価損益) / 証拠金
        adjusted_margin = self.margin * (1 + pnl_ratio * self.leverage)
        margin_ratio = adjusted_margin / self.margin

        return max(0.0, margin_ratio)

    def get_liquidation_price(self, liquidation_threshold: float = 0.5) -> float:
        """
        ロスカット価格を計算

        Args:
            liquidation_threshold: ロスカットしきい値（デフォルト: 50%）

        Returns:
            ロスカット価格
        """
        if not self.is_leveraged:
            return 0.0  # 現物はロスカットなし

        # 証拠金維持率がしきい値になる価格を計算
        loss_ratio = (1 - liquidation_threshold) / self.leverage

        if self.side == 'long':
            return self.entry_price * (1 - loss_ratio)
        else:
            return self.entry_price * (1 + loss_ratio)

    def to_dict(self) -> Dict:
        """辞書形式に変換"""
        return {
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'quantity': self.quantity,
            'entry_time': self.entry_time.isoformat(),
            'exit_price': self.exit_price,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'realized_pnl': self.realized_pnl,
            'status': self.status,
            'leverage': self.leverage,
            'margin': self.margin,
            'is_leveraged': self.is_leveraged
        }


class PositionManager:
    """ポジション管理クラス"""

    def __init__(self, db_manager: Optional[SQLiteManager] = None):
        """
        Args:
            db_manager: SQLiteManagerインスタンス
        """
        self.db_manager = db_manager
        self.open_positions: Dict[str, Position] = {}  # symbol -> Position
        self.closed_positions: List[Position] = []

        logger.info("ポジション管理システム初期化")

    def open_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        leverage: float = 1.0,
        margin: float = 0.0
    ) -> Position:
        """
        新規ポジションを開く

        Args:
            symbol: 取引ペア
            side: 'long' または 'short'
            entry_price: エントリー価格
            quantity: 数量
            leverage: レバレッジ倍率（デフォルト: 1.0 = 現物）
            margin: 使用証拠金

        Returns:
            Positionインスタンス
        """
        # 既存のポジションがある場合はエラー
        if symbol in self.open_positions:
            logger.error(f"{symbol}の既存ポジションがあります。先に既存ポジションを決済してください。")
            return None

        # ショートポジション検証: bitFlyer現物市場では空売り不可
        # FX_BTC_JPY以外でショートを試みた場合はエラー
        if side == 'short' and not symbol.startswith('FX_'):
            logger.error(f"現物市場 {symbol} ではショートポジションは取引できません。"
                        f"ショートポジションはFX_BTC_JPYのみ対応しています。")
            return None

        # レバレッジ検証: 現物市場ではレバレッジ不可
        if leverage > 1.0 and not symbol.startswith('FX_'):
            logger.warning(f"現物市場 {symbol} ではレバレッジは使用できません。1倍に設定します。")
            leverage = 1.0

        position = Position(symbol, side, entry_price, quantity, leverage=leverage, margin=margin)
        self.open_positions[symbol] = position

        # DBに保存
        if self.db_manager:
            position_data = {
                'position_id': position.position_id,
                'symbol': symbol,
                'side': side,
                'entry_price': entry_price,
                'entry_amount': quantity,
                'entry_time': position.entry_time.isoformat(),
                'status': 'open',
                'leverage': leverage,
                'margin': position.margin
            }
            self.db_manager.create_position(position_data)

        leverage_info = f" (レバレッジ: {leverage}倍)" if leverage > 1.0 else ""
        logger.info(f"ポジションオープン: {symbol} {side.upper()} "
                   f"{quantity:.6f} @ ¥{entry_price:,.0f}{leverage_info}")

        return position

    def create_pending_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float
    ) -> Optional[Position]:
        """
        保留中ポジションを作成（注文実行前にDB記録）

        Args:
            symbol: 取引ペア
            side: 'long' または 'short'
            entry_price: エントリー予定価格
            quantity: 数量

        Returns:
            Positionインスタンス（status='pending_execution'）
        """
        # 既存のポジション確認
        if symbol in self.open_positions:
            logger.error(f"{symbol}の既存ポジションがあります。")
            return None

        # ショートポジション検証
        if side == 'short' and not symbol.startswith('FX_'):
            logger.error(f"現物市場 {symbol} ではショートポジション不可")
            return None

        position = Position(symbol, side, entry_price, quantity)
        position.status = 'pending_execution'  # 保留ステータス

        # DBに保留レコード作成
        if self.db_manager:
            position_data = {
                'position_id': position.position_id,
                'symbol': symbol,
                'side': side,
                'entry_price': entry_price,
                'entry_amount': quantity,
                'entry_time': position.entry_time.isoformat(),
                'status': 'pending_execution'
            }
            self.db_manager.create_position(position_data)

        logger.info(f"保留ポジション作成: {symbol} {side.upper()} "
                   f"{quantity:.6f} @ ¥{entry_price:,.0f} (ID: {position.position_id})")

        return position

    def confirm_pending_position(
        self,
        position: Position,
        actual_price: float
    ) -> bool:
        """
        保留ポジションを確定（注文実行成功後）

        Args:
            position: 保留中のポジション
            actual_price: 実際の約定価格

        Returns:
            成功したかどうか
        """
        if position.status != 'pending_execution':
            logger.error(f"ポジション {position.position_id} は保留状態ではありません")
            return False

        # ステータスを確定
        position.status = 'open'
        position.entry_price = actual_price  # 実際の約定価格で更新

        # メモリに登録
        self.open_positions[position.symbol] = position

        # DB更新
        if self.db_manager:
            self.db_manager.update_position(
                position.position_id,
                {
                    'status': 'open',
                    'entry_price': actual_price
                }
            )

        logger.info(f"ポジション確定: {position.symbol} {position.side.upper()} "
                   f"@ ¥{actual_price:,.0f} (ID: {position.position_id})")

        return True

    def cancel_pending_position(
        self,
        position: Position,
        reason: str = "注文失敗"
    ) -> bool:
        """
        保留ポジションをキャンセル（注文実行失敗時）

        Args:
            position: 保留中のポジション
            reason: キャンセル理由

        Returns:
            成功したかどうか
        """
        if position.status != 'pending_execution':
            logger.warning(f"ポジション {position.position_id} は保留状態ではありません")

        # ステータスをキャンセルに
        position.status = 'execution_failed'

        # DB更新
        if self.db_manager:
            self.db_manager.update_position(
                position.position_id,
                {
                    'status': 'execution_failed'
                }
            )

        logger.warning(f"ポジションキャンセル: {position.symbol} - 理由: {reason} "
                      f"(ID: {position.position_id})")

        return True

    def partial_close_position(
        self,
        symbol: str,
        exit_price: float,
        close_ratio: float
    ) -> Optional[Dict]:
        """
        ポジションを部分的にクローズ

        Args:
            symbol: 取引ペア
            exit_price: 決済価格
            close_ratio: クローズする割合（0.0-1.0）

        Returns:
            部分決済情報の辞書（存在しない場合はNone）
        """
        if symbol not in self.open_positions:
            logger.warning(f"{symbol}のオープンポジションが見つかりません")
            return None

        if not (0.0 < close_ratio <= 1.0):
            logger.error(f"close_ratioは0.0-1.0の範囲で指定してください: {close_ratio}")
            return None

        position = self.open_positions[symbol]

        # 部分決済する数量を計算
        partial_quantity = position.quantity * close_ratio
        remaining_quantity = position.quantity * (1.0 - close_ratio)

        # 部分決済のPNL計算（手数料考慮）
        commission_rate = 0.0015  # bitFlyer手数料 0.15%

        if position.side == 'long':
            partial_pnl = (exit_price - position.entry_price) * partial_quantity
        else:  # short
            partial_pnl = (position.entry_price - exit_price) * partial_quantity

        # 決済時手数料のみ考慮（エントリー時手数料は既に支払い済み）
        exit_fee = exit_price * partial_quantity * commission_rate

        # 手数料控除後の実質PnL
        partial_pnl_after_fees = partial_pnl - exit_fee

        partial_pnl_pct = (partial_pnl_after_fees / (position.entry_price * partial_quantity)) * 100 if partial_quantity > 0 else 0.0

        logger.info(f"ポジション部分決済: {symbol} {position.side.upper()} "
                   f"{close_ratio:.0%} ({partial_quantity:.6f} / {position.quantity:.6f}) "
                   f"損益=¥{partial_pnl_after_fees:,.0f} ({partial_pnl_pct:+.2f}%)")

        # DBにトレード履歴を記録
        if self.db_manager:
            from datetime import datetime
            trade_data = {
                'symbol': symbol,
                'side': position.side,
                'price': exit_price,
                'amount': partial_quantity,
                'cost': exit_price * partial_quantity,
                'fee': exit_fee,  # 決済時手数料のみ
                'order_type': 'market',
                'pnl': partial_pnl_after_fees,  # 手数料控除後
                'timestamp': datetime.now().isoformat()
            }
            self.db_manager.insert_trade(trade_data)

            # ポジションの数量を更新
            updates = {
                'entry_amount': remaining_quantity
            }
            self.db_manager.update_position(position.position_id, updates)

        # ポジションの数量を更新
        position.quantity = remaining_quantity

        partial_close_info = {
            'symbol': symbol,
            'side': position.side,
            'partial_quantity': partial_quantity,
            'remaining_quantity': remaining_quantity,
            'close_ratio': close_ratio,
            'partial_pnl': partial_pnl_after_fees,  # 手数料控除後
            'partial_pnl_pct': partial_pnl_pct,
            'exit_price': exit_price,
            'exit_fee': exit_fee  # 決済時手数料のみ
        }

        return partial_close_info

    def close_position(
        self,
        symbol: str,
        exit_price: float
    ) -> Optional[Position]:
        """
        ポジションをクローズ

        Args:
            symbol: 取引ペア
            exit_price: 決済価格

        Returns:
            クローズしたPositionインスタンス（存在しない場合はNone）
        """
        if symbol not in self.open_positions:
            logger.warning(f"{symbol}のオープンポジションが見つかりません")
            return None

        position = self.open_positions.pop(symbol)
        position.close(exit_price)
        self.closed_positions.append(position)

        # DBに保存
        if self.db_manager:
            # ポジション更新
            updates = {
                'exit_price': exit_price,
                'exit_amount': position.quantity,
                'exit_time': position.exit_time.isoformat(),
                'status': 'closed'
            }
            self.db_manager.update_position(position.position_id, updates)

            # トレード履歴にも記録
            from datetime import datetime
            commission_rate = 0.0015
            exit_fee = exit_price * position.quantity * commission_rate
            trade_data = {
                'symbol': symbol,
                'side': position.side,
                'price': exit_price,
                'amount': position.quantity,
                'cost': exit_price * position.quantity,
                'fee': exit_fee,  # 決済時手数料のみ（エントリー時は既に支払い済み）
                'order_type': 'market',
                'pnl': position.realized_pnl,  # 既に手数料控除済み
                'timestamp': datetime.now().isoformat()
            }
            self.db_manager.insert_trade(trade_data)

        return position

    def get_position(self, symbol: str) -> Optional[Position]:
        """
        ポジションを取得

        Args:
            symbol: 取引ペア

        Returns:
            Positionインスタンス（存在しない場合はNone）
        """
        return self.open_positions.get(symbol)

    def get_open_position(self, symbol: str) -> Optional[Position]:
        """
        オープンポジションを取得（get_positionのエイリアス）

        Args:
            symbol: 取引ペア

        Returns:
            Positionインスタンス（存在しない場合はNone）
        """
        return self.get_position(symbol)

    def has_position(self, symbol: str) -> bool:
        """
        ポジションを保有しているか

        Args:
            symbol: 取引ペア

        Returns:
            保有している場合True
        """
        return symbol in self.open_positions

    def get_all_positions(self) -> Dict[str, Position]:
        """
        全オープンポジションを取得

        Returns:
            シンボル -> Positionの辞書
        """
        return self.open_positions.copy()

    def calculate_total_pnl(self, current_prices: Dict[str, float]) -> Dict:
        """
        総損益を計算

        Args:
            current_prices: シンボル -> 現在価格の辞書

        Returns:
            損益情報の辞書
        """
        unrealized_pnl = 0.0
        realized_pnl = sum(pos.realized_pnl for pos in self.closed_positions)

        # 未実現損益
        for symbol, position in self.open_positions.items():
            if symbol in current_prices:
                unrealized_pnl += position.calculate_unrealized_pnl(current_prices[symbol])

        total_pnl = realized_pnl + unrealized_pnl

        return {
            'realized_pnl': realized_pnl,
            'unrealized_pnl': unrealized_pnl,
            'total_pnl': total_pnl,
            'open_positions': len(self.open_positions),
            'closed_positions': len(self.closed_positions)
        }

    def get_position_summary(self, symbol: str, current_price: float) -> Optional[Dict]:
        """
        ポジションサマリーを取得

        Args:
            symbol: 取引ペア
            current_price: 現在価格

        Returns:
            サマリー情報の辞書
        """
        position = self.get_position(symbol)
        if not position:
            return None

        unrealized_pnl = position.calculate_unrealized_pnl(current_price)
        unrealized_pnl_pct = position.calculate_unrealized_pnl_pct(current_price)

        holding_time = datetime.now() - position.entry_time
        holding_hours = holding_time.total_seconds() / 3600

        result = {
            'symbol': symbol,
            'side': position.side,
            'entry_price': position.entry_price,
            'current_price': current_price,
            'quantity': position.quantity,
            'unrealized_pnl': unrealized_pnl,
            'unrealized_pnl_pct': unrealized_pnl_pct,
            'holding_hours': holding_hours,
            'entry_time': position.entry_time.isoformat(),
            'leverage': position.leverage,
            'is_leveraged': position.is_leveraged
        }

        # レバレッジ取引の場合は証拠金情報を追加
        if position.is_leveraged:
            result['margin'] = position.margin
            result['margin_ratio'] = position.calculate_margin_ratio(current_price)
            result['liquidation_price'] = position.get_liquidation_price()

        return result

    def close_all_positions(self, current_prices: Dict[str, float]) -> List[Position]:
        """
        全ポジションをクローズ

        Args:
            current_prices: シンボル -> 現在価格の辞書

        Returns:
            クローズしたPositionのリスト
        """
        closed = []

        for symbol in list(self.open_positions.keys()):
            if symbol in current_prices:
                position = self.close_position(symbol, current_prices[symbol])
                if position:
                    closed.append(position)

        logger.info(f"全ポジションクローズ: {len(closed)}件")

        return closed


# ヘルパー関数
def create_position_manager(db_manager: Optional[SQLiteManager] = None) -> PositionManager:
    """
    ポジション管理インスタンスを作成

    Args:
        db_manager: SQLiteManagerインスタンス

    Returns:
        PositionManagerインスタンス
    """
    return PositionManager(db_manager)
