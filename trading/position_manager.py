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
        position_id: Optional[str] = None
    ):
        """
        Args:
            symbol: 取引ペア
            side: 'long' または 'short'
            entry_price: エントリー価格
            quantity: 数量
            entry_time: エントリー時刻
            position_id: ポジションID
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

    def calculate_unrealized_pnl(self, current_price: float) -> float:
        """
        未実現損益を計算

        Args:
            current_price: 現在価格

        Returns:
            未実現損益
        """
        if self.side == 'long':
            pnl = (current_price - self.entry_price) * self.quantity
        else:  # short
            pnl = (self.entry_price - current_price) * self.quantity

        return pnl

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
            'status': self.status
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
        quantity: float
    ) -> Position:
        """
        新規ポジションを開く

        Args:
            symbol: 取引ペア
            side: 'long' または 'short'
            entry_price: エントリー価格
            quantity: 数量

        Returns:
            Positionインスタンス
        """
        # 既存のポジションがある場合は警告
        if symbol in self.open_positions:
            logger.warning(f"{symbol}の既存ポジションがあります - 上書きします")
            self.close_position(symbol, entry_price)

        position = Position(symbol, side, entry_price, quantity)
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
                'status': 'open'
            }
            self.db_manager.create_position(position_data)

        logger.info(f"ポジションオープン: {symbol} {side.upper()} "
                   f"{quantity:.6f} @ ¥{entry_price:,.0f}")

        return position

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
            trade_data = {
                'symbol': symbol,
                'side': position.side,
                'price': exit_price,
                'amount': position.quantity,
                'cost': exit_price * position.quantity,
                'fee': exit_price * position.quantity * 0.0015,
                'order_type': 'market',
                'pnl': position.realized_pnl,
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

        return {
            'symbol': symbol,
            'side': position.side,
            'entry_price': position.entry_price,
            'current_price': current_price,
            'quantity': position.quantity,
            'unrealized_pnl': unrealized_pnl,
            'unrealized_pnl_pct': unrealized_pnl_pct,
            'holding_hours': holding_hours,
            'entry_time': position.entry_time.isoformat()
        }

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
