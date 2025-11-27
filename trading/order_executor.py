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

logger = logging.getLogger(__name__)


class OrderExecutor:
    """注文実行クラス"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        test_mode: bool = True,
        leverage_config: Optional[Dict] = None
    ):
        """
        初期化

        Args:
            api_key: bitFlyer APIキー
            api_secret: bitFlyer APIシークレット
            test_mode: テストモード（実際の注文を実行しない）
            leverage_config: レバレッジ設定（Noneの場合は現物取引）
        """
        self.test_mode = test_mode
        self.exchange = None

        # レバレッジ設定（デフォルトは現物取引 = 1倍）
        self.leverage_enabled = False
        self.max_leverage = 1.0
        self.fx_symbol = 'FX_BTC_JPY'
        self.margin_call_threshold = 0.8
        self.liquidation_threshold = 0.5
        self.allow_short = False

        if leverage_config:
            self.leverage_enabled = leverage_config.get('enabled', False)
            self.max_leverage = leverage_config.get('max_leverage', 2.0)
            self.fx_symbol = leverage_config.get('fx_symbol', 'FX_BTC_JPY')
            self.margin_call_threshold = leverage_config.get('margin_call_threshold', 0.8)
            self.liquidation_threshold = leverage_config.get('liquidation_threshold', 0.5)
            self.allow_short = leverage_config.get('allow_short', False)

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

        leverage_status = f"{self.max_leverage}倍" if self.leverage_enabled else "無効（現物取引）"
        logger.info(f"注文実行モジュール初期化（テストモード: {test_mode}, レバレッジ: {leverage_status}）")

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
                estimated_cost = amount * estimated_price
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
                        commission_rate = 0.0015
                        required_capital = estimated_cost * (1 + commission_rate)

                        if required_capital > available_jpy:
                            logger.error(f"残高不足: 必要¥{required_capital:,.0f} > 利用可能¥{available_jpy:,.0f}")
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
                'BTC/JPY': 12000000.0,   # 1200万円
                'ETH/JPY': 500000.0,     # 50万円
                'FX_BTC_JPY': 12050000.0  # FX価格（現物より若干高め）
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
        ポジションサイズを計算（エントリー・エグジット両方の手数料を考慮）

        Args:
            symbol: 取引ペア
            available_capital: 利用可能資金
            position_ratio: ポジション比率（0-1）

        Returns:
            購入可能数量

        Note:
            エントリー時とエグジット時の両方で手数料がかかるため、
            両方を考慮してポジションサイズを計算する。
            これにより、決済時に資金不足になることを防ぐ。
        """
        current_price = self.get_current_price(symbol)

        # 価格の有効性をチェック
        if not current_price or current_price <= 0:
            logger.error(f"価格取得失敗または無効な価格: {symbol} = {current_price}")
            return 0.0

        trade_capital = available_capital * position_ratio
        commission_rate = 0.0015  # bitFlyer手数料

        # エントリー・エグジット両方の手数料を考慮
        # エントリー時: quantity * price * (1 + commission)
        # エグジット時: quantity * price * commission（最悪の場合を想定）
        # 合計: quantity * price * (1 + 2 * commission) <= capital
        total_commission_factor = 1 + (2 * commission_rate)
        quantity = trade_capital / (current_price * total_commission_factor)

        # 精度調整（8桁に丸める）
        quantity = round(quantity, 8)

        entry_cost = quantity * current_price * (1 + commission_rate)
        logger.info(f"ポジションサイズ計算: {quantity:.6f} {symbol.split('/')[0]} "
                   f"(資金: ¥{available_capital:,.0f}, 価格: ¥{current_price:,.0f}, "
                   f"予想コスト: ¥{entry_cost:,.0f})")

        return quantity

    def calculate_leveraged_position_size(
        self,
        available_capital: float,
        leverage: float = 1.0,
        position_ratio: float = 0.95
    ) -> Dict:
        """
        レバレッジ取引用のポジションサイズを計算

        Args:
            available_capital: 利用可能証拠金
            leverage: レバレッジ倍率（1.0-2.0）
            position_ratio: ポジション比率（0-1）

        Returns:
            ポジション情報（数量、証拠金、レバレッジ等）

        Note:
            - レバレッジ無効時は現物取引として計算（レバレッジ1倍）
            - ペアトレードでは常にレバレッジ1倍を使用
        """
        # レバレッジの有効性チェック
        if not self.leverage_enabled:
            leverage = 1.0
            logger.debug("レバレッジ無効 - 現物取引モードで計算")

        # レバレッジ上限チェック
        leverage = min(leverage, self.max_leverage)
        leverage = max(leverage, 1.0)

        # FX価格を取得
        fx_price = self.get_current_price(self.fx_symbol)
        if not fx_price or fx_price <= 0:
            logger.error(f"FX価格取得失敗: {self.fx_symbol}")
            return None

        # 証拠金計算
        margin_capital = available_capital * position_ratio
        commission_rate = 0.0015  # bitFlyer手数料

        # レバレッジを考慮した購入力
        buying_power = margin_capital * leverage

        # 手数料を考慮した数量計算
        total_commission_factor = 1 + (2 * commission_rate)
        quantity = buying_power / (fx_price * total_commission_factor)
        quantity = round(quantity, 8)

        # 必要証拠金
        required_margin = (quantity * fx_price) / leverage
        # ロスカット価格（買いポジションの場合）
        liquidation_price = fx_price * (1 - (self.liquidation_threshold / leverage))

        result = {
            'symbol': self.fx_symbol,
            'quantity': quantity,
            'leverage': leverage,
            'margin': required_margin,
            'buying_power': buying_power,
            'entry_price': fx_price,
            'liquidation_price': liquidation_price,
            'margin_call_price': fx_price * (1 - (self.margin_call_threshold - 0.5) / leverage)
        }

        logger.info(f"レバレッジポジション計算: {quantity:.6f} BTC "
                   f"(レバレッジ: {leverage}倍, 証拠金: ¥{required_margin:,.0f}, "
                   f"ロスカット: ¥{liquidation_price:,.0f})")

        return result

    def get_margin_status(self, position_value: float, margin: float, current_price: float, entry_price: float, side: str = 'long') -> Dict:
        """
        証拠金維持率と状態を取得

        Args:
            position_value: ポジション価値（数量 × 価格）
            margin: 使用証拠金
            current_price: 現在価格
            entry_price: エントリー価格
            side: ポジション方向（'long' or 'short'）

        Returns:
            証拠金状態の辞書
        """
        if margin <= 0:
            return {'margin_ratio': 1.0, 'status': 'no_position', 'unrealized_pnl': 0}

        # 未実現損益計算
        if side == 'long':
            unrealized_pnl = (current_price - entry_price) / entry_price
        else:
            unrealized_pnl = (entry_price - current_price) / entry_price

        # 証拠金維持率 = (証拠金 + 評価損益) / 証拠金
        adjusted_margin = margin * (1 + unrealized_pnl)
        margin_ratio = adjusted_margin / margin

        # 状態判定
        if margin_ratio <= self.liquidation_threshold:
            status = 'liquidation'
        elif margin_ratio <= self.margin_call_threshold:
            status = 'margin_call'
        else:
            status = 'normal'

        return {
            'margin_ratio': margin_ratio,
            'status': status,
            'unrealized_pnl': unrealized_pnl,
            'adjusted_margin': adjusted_margin
        }

    def is_fx_symbol(self, symbol: str) -> bool:
        """FX取引ペアかどうかを判定"""
        return symbol.startswith('FX_')

    def get_effective_symbol(self, base_symbol: str, use_leverage: bool = False) -> str:
        """
        実際に使用するシンボルを取得

        Args:
            base_symbol: 基本シンボル（例: 'BTC/JPY'）
            use_leverage: レバレッジを使用するか

        Returns:
            使用するシンボル（レバレッジ有効時はFXシンボル）
        """
        if use_leverage and self.leverage_enabled and 'BTC' in base_symbol:
            return self.fx_symbol
        return base_symbol

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
            'cost': amount * (price or self.get_current_price(symbol)),
            'fee': {
                'currency': 'JPY',
                'cost': amount * (price or self.get_current_price(symbol)) * 0.0015
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
