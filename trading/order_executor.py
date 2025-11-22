"""注文実行モジュール - bitFlyer API統合

成行注文、指値注文、注文キャンセルなどの売買実行機能
"""

import logging
import time
import sys
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime
import ccxt

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

# リトライ機能インポート
from utils.retry import retry_on_network_error
# HIGH-2: 定数をインポート
from utils.constants import (
    BITFLYER_COMMISSION_RATE,
    MAX_ORDER_COST_JPY,
    BALANCE_BUFFER_RATE,
    ORDER_STATUS_RETRY_DELAYS
)

logger = logging.getLogger(__name__)


class OrderExecutor:
    """注文実行クラス"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        test_mode: bool = True
    ):
        """
        初期化

        Args:
            api_key: bitFlyer APIキー
            api_secret: bitFlyer APIシークレット
            test_mode: テストモード（実際の注文を実行しない）
        """
        self.test_mode = test_mode
        self.exchange = None

        if api_key and api_secret:
            try:
                self.exchange = ccxt.bitflyer({
                    'apiKey': api_key,
                    'secret': api_secret,
                    'enableRateLimit': True,
                    'rateLimit': 500
                })
                logger.info("bitFlyer API接続成功")
            except Exception as e:
                logger.error(f"bitFlyer API接続失敗: {e}")
                self.exchange = None
        else:
            logger.warning("APIキー未設定 - テストモードで動作")

        logger.info(f"注文実行モジュール初期化（テストモード: {test_mode}）")

    # ========== MEDIUM-3: 価格・コスト丸め処理 ==========

    @staticmethod
    def round_price(price: float, symbol: str = "BTC/JPY") -> float:
        """
        価格を適切な精度に丸める

        Args:
            price: 価格
            symbol: 取引ペア

        Returns:
            丸めた価格
        """
        # JPY建ては整数に丸める
        if "/JPY" in symbol:
            return round(price)
        # その他は8桁精度
        return round(price, 8)

    @staticmethod
    def round_amount(amount: float, symbol: str = "BTC/JPY") -> float:
        """
        数量を適切な精度に丸める

        Args:
            amount: 数量
            symbol: 取引ペア

        Returns:
            丸めた数量
        """
        # 暗号通貨は8桁精度
        return round(amount, 8)

    @staticmethod
    def round_cost(cost: float, quote_currency: str = "JPY") -> float:
        """
        コスト（金額）を適切な精度に丸める

        Args:
            cost: コスト
            quote_currency: 決済通貨

        Returns:
            丸めたコスト
        """
        # JPYは整数に丸める
        if quote_currency == "JPY":
            return round(cost)
        # その他は8桁精度
        return round(cost, 8)

    # ========== リトライ付きAPI呼び出しヘルパー ==========

    @retry_on_network_error(max_retries=4, base_delay=2.0)
    def _create_market_order_with_retry(self, symbol: str, side: str, amount: float):
        """成行注文実行（リトライ付き）"""
        return self.exchange.create_market_order(symbol, side, amount)

    @retry_on_network_error(max_retries=4, base_delay=2.0)
    def _fetch_balance_with_retry(self):
        """残高取得（リトライ付き）"""
        return self.exchange.fetch_balance()

    @retry_on_network_error(max_retries=4, base_delay=2.0)
    def _fetch_ticker_with_retry(self, symbol: str):
        """ティッカー取得（リトライ付き）"""
        return self.exchange.fetch_ticker(symbol)

    # ========== 注文実行メソッド ==========

    def create_market_order(
        self,
        symbol: str,
        side: str,
        amount: float
    ) -> Dict:
        """
        成行注文を作成

        Args:
            symbol: 取引ペア（例: 'BTC/JPY'）
            side: 'buy' または 'sell'
            amount: 数量

        Returns:
            注文情報の辞書
        """
        # 最小注文数量チェック
        min_amounts = {
            'BTC/JPY': 0.001,
            'ETH/JPY': 0.01,
            'XRP/JPY': 1.0,
            'FX_BTC_JPY': 0.01  # FXの場合
        }
        min_amount = min_amounts.get(symbol, 0.0)
        if amount < min_amount:
            logger.error(f"注文数量不足: {symbol} {amount:.8f} < 最小値 {min_amount}")
            return None

        # 最大注文数量チェック（異常に大きな注文を防止）
        max_amounts = {
            'BTC/JPY': 10.0,    # 最大10 BTC
            'ETH/JPY': 100.0,   # 最大100 ETH
            'XRP/JPY': 100000.0,  # 最大100,000 XRP
            'FX_BTC_JPY': 10.0
        }
        max_amount = max_amounts.get(symbol, 1000.0)
        if amount > max_amount:
            logger.error(f"注文数量超過: {symbol} {amount:.8f} > 最大値 {max_amount}")
            logger.error("  → 異常に大きな注文を検出しました。注文を拒否します。")
            return None

        # 注文金額の妥当性チェック（推定金額が1億円を超える場合は拒否）
        if not self.test_mode:
            try:
                estimated_price = self.get_current_price(symbol)
                # MEDIUM-3: コストを適切に丸める
                estimated_cost = self.round_cost(amount * estimated_price, "JPY")
                max_order_cost = 100_000_000  # 1億円
                if estimated_cost > max_order_cost:
                    logger.error(f"注文金額超過: {symbol} 推定¥{estimated_cost:,.0f} > 上限¥{max_order_cost:,.0f}")
                    logger.error(f"  → 数量: {amount:.8f}, 価格: ¥{estimated_price:,.0f}")
                    return None

                # 買い注文の場合、残高チェック
                if side == 'buy':
                    try:
                        balance = self.get_balance('JPY')
                        available_jpy = balance.get('free', 0)
                        # HIGH-2: 定数を使用
                        commission_rate = BITFLYER_COMMISSION_RATE
                        # MEDIUM-3: 必要資本を丸める
                        required_capital = self.round_cost(estimated_cost * (1 + commission_rate), "JPY")

                        # ✨ 3%バッファを追加（価格変動・手数料誤差・並行処理を考慮）
                        buffer_rate = BALANCE_BUFFER_RATE  # HIGH-2: 定数を使用
                        required_capital_with_buffer = self.round_cost(required_capital * (1 + buffer_rate), "JPY")

                        if required_capital_with_buffer > available_jpy:
                            logger.error(f"残高不足: 必要¥{required_capital:,.0f} (+バッファ¥{required_capital*buffer_rate:,.0f}) > 利用可能¥{available_jpy:,.0f}")
                            logger.error(f"  → {symbol} {amount:.8f} @ ¥{estimated_price:,.0f}")
                            return None
                    except Exception as balance_error:
                        logger.warning(f"残高チェック失敗: {balance_error}")

            except Exception as e:
                logger.warning(f"価格取得失敗のため注文金額チェックをスキップ: {e}")

        if self.test_mode:
            # テストモード: モック注文を返す
            order = self._create_mock_order(symbol, side, 'market', amount, None)
            logger.info(f"[テスト] 成行注文: {side.upper()} {amount} {symbol}")
            return order

        if not self.exchange:
            raise ValueError("API未接続 - APIキーを設定してください")

        try:
            order = self._create_market_order_with_retry(symbol, side, amount)
            logger.info(f"成行注文実行: {side.upper()} {amount} {symbol}")
            return order
        except Exception as e:
            logger.error(f"成行注文失敗: {e}")
            raise

    def create_limit_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float
    ) -> Dict:
        """
        指値注文を作成

        Args:
            symbol: 取引ペア
            side: 'buy' または 'sell'
            amount: 数量
            price: 指値価格

        Returns:
            注文情報の辞書
        """
        if self.test_mode:
            # テストモード: モック注文を返す
            order = self._create_mock_order(symbol, side, 'limit', amount, price)
            logger.info(f"[テスト] 指値注文: {side.upper()} {amount} {symbol} @ ¥{price:,.0f}")
            return order

        if not self.exchange:
            raise ValueError("API未接続 - APIキーを設定してください")

        try:
            order = self.exchange.create_limit_order(symbol, side, amount, price)
            logger.info(f"指値注文実行: {side.upper()} {amount} {symbol} @ ¥{price:,.0f}")
            return order
        except Exception as e:
            logger.error(f"指値注文失敗: {e}")
            raise

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """
        注文をキャンセル

        Args:
            order_id: 注文ID
            symbol: 取引ペア

        Returns:
            成功したかどうか
        """
        if self.test_mode:
            logger.info(f"[テスト] 注文キャンセル: {order_id}")
            return True

        if not self.exchange:
            raise ValueError("API未接続")

        try:
            self.exchange.cancel_order(order_id, symbol)
            logger.info(f"注文キャンセル成功: {order_id}")
            return True
        except Exception as e:
            logger.error(f"注文キャンセル失敗: {e}")
            return False

    def get_order_status(self, order_id: str, symbol: str) -> Dict:
        """
        注文状態を取得

        Args:
            order_id: 注文ID
            symbol: 取引ペア

        Returns:
            注文情報
        """
        if self.test_mode:
            return self._create_mock_order_status(order_id, 'closed')

        if not self.exchange:
            raise ValueError("API未接続")

        try:
            order = self.exchange.fetch_order(order_id, symbol)
            return order
        except Exception as e:
            logger.error(f"注文状態取得失敗: {e}")
            raise

    def get_balance(self, currency: Optional[str] = None) -> Dict:
        """
        残高を取得

        Args:
            currency: 通貨（Noneの場合は全通貨）

        Returns:
            残高情報
        """
        if self.test_mode:
            # テストモード: モック残高を返す
            mock_balance = {
                'JPY': {'free': 200000.0, 'used': 0.0, 'total': 200000.0},
                'BTC': {'free': 0.0, 'used': 0.0, 'total': 0.0},
                'ETH': {'free': 0.0, 'used': 0.0, 'total': 0.0}
            }
            if currency:
                return mock_balance.get(currency, {'free': 0.0, 'used': 0.0, 'total': 0.0})
            return mock_balance

        if not self.exchange:
            raise ValueError("API未接続")

        try:
            balance = self._fetch_balance_with_retry()
            if currency:
                return balance.get(currency, {'free': 0.0, 'used': 0.0, 'total': 0.0})
            return balance
        except Exception as e:
            logger.error(f"残高取得失敗: {e}")
            raise

    def get_current_price(self, symbol: str) -> float:
        """
        現在価格を取得

        Args:
            symbol: 取引ペア

        Returns:
            現在価格
        """
        if self.test_mode:
            # テストモード: ダミー価格
            mock_prices = {
                'BTC/JPY': 12000000.0,  # 1200万円
                'ETH/JPY': 500000.0      # 50万円
            }
            return mock_prices.get(symbol, 100000.0)

        if not self.exchange:
            raise ValueError("API未接続")

        try:
            ticker = self._fetch_ticker_with_retry(symbol)
            return ticker['last']
        except Exception as e:
            logger.error(f"価格取得失敗: {e}")
            raise

    def calculate_position_size(
        self,
        symbol: str,
        available_capital: float,
        position_ratio: float = 0.95
    ) -> float:
        """
        ポジションサイズを計算

        Args:
            symbol: 取引ペア
            available_capital: 利用可能資金
            position_ratio: ポジション比率（0-1）

        Returns:
            購入可能数量
        """
        current_price = self.get_current_price(symbol)

        # 価格の有効性をチェック
        if not current_price or current_price <= 0:
            logger.error(f"価格取得失敗または無効な価格: {symbol} = {current_price}")
            return 0.0

        trade_capital = available_capital * position_ratio
        # HIGH-2: 定数を使用
        commission_rate = BITFLYER_COMMISSION_RATE

        # 手数料を考慮した購入可能数量
        # 正しい計算: quantity * price * (1 + commission) <= capital
        quantity = trade_capital / (current_price * (1 + commission_rate))

        # MEDIUM-3: 数量を適切な精度に丸める
        quantity = self.round_amount(quantity, symbol)

        logger.info(f"ポジションサイズ計算: {quantity:.6f} {symbol.split('/')[0]} "
                   f"(資金: ¥{available_capital:,.0f}, 価格: ¥{current_price:,.0f})")

        return quantity

    def _create_mock_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        amount: float,
        price: Optional[float]
    ) -> Dict:
        """モック注文を作成（テスト用）"""
        order_id = f"MOCK_{int(time.time() * 1000)}"

        order = {
            'id': order_id,
            'symbol': symbol,
            'type': order_type,
            'side': side,
            'amount': amount,
            'price': price,
            'status': 'closed' if order_type == 'market' else 'open',
            'timestamp': int(time.time() * 1000),
            'datetime': datetime.now().isoformat(),
            'filled': amount if order_type == 'market' else 0,
            'remaining': 0 if order_type == 'market' else amount,
            # MEDIUM-3: コストと手数料を適切に丸める
            'cost': self.round_cost(amount * (price or self.get_current_price(symbol)), 'JPY'),
            'fee': {
                'currency': 'JPY',
                # HIGH-2: 定数を使用
                'cost': self.round_cost(amount * (price or self.get_current_price(symbol)) * BITFLYER_COMMISSION_RATE, 'JPY')
            }
        }

        return order

    def _create_mock_order_status(self, order_id: str, status: str = 'closed') -> Dict:
        """モック注文状態を作成（テスト用）"""
        return {
            'id': order_id,
            'status': status,
            'timestamp': int(time.time() * 1000),
            'datetime': datetime.now().isoformat()
        }


# ヘルパー関数
def create_order_executor(
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    test_mode: bool = True
) -> OrderExecutor:
    """
    注文実行インスタンスを作成

    Args:
        api_key: APIキー
        api_secret: APIシークレット
        test_mode: テストモード

    Returns:
        OrderExecutorインスタンス
    """
    return OrderExecutor(api_key, api_secret, test_mode)
