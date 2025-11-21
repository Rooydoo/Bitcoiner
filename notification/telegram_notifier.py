"""Telegram通知モジュール

取引通知、日次サマリー、アラートなどを送信
"""

import logging
from typing import Optional, Dict, List
from datetime import datetime
import requests

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Telegram通知クラス"""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
        enabled: bool = True
    ):
        """
        Args:
            bot_token: Telegram Bot Token
            chat_id: Telegram Chat ID
            enabled: 通知を有効化
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.enabled = enabled and bot_token and chat_id

        if not self.enabled:
            logger.warning("Telegram通知が無効です（Token/Chat ID未設定）")
        else:
            logger.info("Telegram通知が有効です")

        self.api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage" if bot_token else None

    def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """
        メッセージを送信

        Args:
            message: 送信メッセージ
            parse_mode: パースモード（HTML or Markdown）

        Returns:
            成功したかどうか
        """
        if not self.enabled:
            logger.debug(f"[テスト] Telegram通知: {message}")
            return True

        try:
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode
            }

            response = requests.post(self.api_url, json=payload, timeout=10)
            response.raise_for_status()

            logger.info("Telegram通知送信成功")
            return True

        except Exception as e:
            logger.error(f"Telegram通知送信失敗: {e}")
            return False

    def notify_trade_open(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: float
    ):
        """
        取引開始通知

        Args:
            symbol: 取引ペア
            side: 'long' or 'short'
            price: 価格
            quantity: 数量
        """
        side_jp = "🟢 買い" if side == "long" else "🔴 売り"

        message = f"""
📈 <b>取引実行</b>

{side_jp} <b>{symbol}</b>
価格: ¥{price:,.0f}
数量: {quantity:.6f}
合計: ¥{price * quantity:,.0f}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_message(message.strip())
        logger.info(f"取引開始通知送信: {symbol} {side}")

    def notify_trade_close(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        pnl: float,
        pnl_pct: float
    ):
        """
        取引終了通知

        Args:
            symbol: 取引ペア
            side: 'long' or 'short'
            entry_price: エントリー価格
            exit_price: 決済価格
            quantity: 数量
            pnl: 損益
            pnl_pct: 損益率（%）
        """
        if pnl > 0:
            emoji = "🎉"
            result = "利益確定"
        else:
            emoji = "⚠️"
            result = "損切り"

        side_jp = "買い" if side == "long" else "売り"

        message = f"""
{emoji} <b>{result}</b>

<b>{symbol}</b> {side_jp}ポジションクローズ

エントリー: ¥{entry_price:,.0f}
決済: ¥{exit_price:,.0f}
数量: {quantity:.6f}

💰 損益: <b>¥{pnl:,.0f}</b> ({pnl_pct:+.2f}%)

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_message(message.strip())
        logger.info(f"取引終了通知送信: {symbol} 損益=¥{pnl:,.0f}")

    def notify_stop_loss(
        self,
        symbol: str,
        current_price: float,
        pnl_pct: float
    ):
        """
        ストップロス発動通知

        Args:
            symbol: 取引ペア
            current_price: 現在価格
            pnl_pct: 損失率（%）
        """
        message = f"""
🛑 <b>ストップロス発動</b>

<b>{symbol}</b>
現在価格: ¥{current_price:,.0f}
損失率: {pnl_pct:.2f}%

ポジションを自動クローズします。

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_message(message.strip())
        logger.warning(f"ストップロス通知送信: {symbol}")

    def notify_take_profit(
        self,
        symbol: str,
        level: int,
        close_ratio: float,
        pnl_pct: float
    ):
        """
        利益確定通知

        Args:
            symbol: 取引ペア
            level: 利確レベル（1 or 2）
            close_ratio: 決済比率（0-1）
            pnl_pct: 利益率（%）
        """
        level_jp = "第1段階" if level == 1 else "第2段階"

        message = f"""
✅ <b>{level_jp}利益確定</b>

<b>{symbol}</b>
利益率: +{pnl_pct:.2f}%
決済比率: {close_ratio:.0%}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_message(message.strip())
        logger.info(f"利益確定通知送信: {symbol} レベル{level}")

    def notify_daily_summary(
        self,
        total_equity: float,
        daily_pnl: float,
        daily_pnl_pct: float,
        trades_count: int,
        win_rate: float,
        open_positions: List[Dict]
    ):
        """
        日次サマリー通知

        Args:
            total_equity: 総資産
            daily_pnl: 本日損益
            daily_pnl_pct: 本日損益率（%）
            trades_count: 取引回数
            win_rate: 勝率
            open_positions: 保有ポジション一覧
        """
        emoji = "📊"
        if daily_pnl > 0:
            pnl_emoji = "📈"
        elif daily_pnl < 0:
            pnl_emoji = "📉"
        else:
            pnl_emoji = "➖"

        message = f"""
{emoji} <b>日次レポート</b>
━━━━━━━━━━━━━━━━

💰 総資産: <b>¥{total_equity:,.0f}</b>
{pnl_emoji} 本日損益: <b>¥{daily_pnl:,.0f}</b> ({daily_pnl_pct:+.2f}%)

📊 取引回数: {trades_count}回
📈 勝率: {win_rate:.1%}

【保有ポジション】
"""

        if open_positions:
            for pos in open_positions:
                message += f"\n• {pos['symbol']} {pos['side'].upper()}"
                message += f"\n  損益: ¥{pos['unrealized_pnl']:,.0f} ({pos['unrealized_pnl_pct']:+.2f}%)"
        else:
            message += "\nなし"

        message += f"\n\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        self.send_message(message.strip())
        logger.info("日次サマリー送信")

    def notify_alert(self, title: str, message: str):
        """
        アラート通知

        Args:
            title: タイトル
            message: メッセージ
        """
        full_message = f"""
⚠️ <b>{title}</b>

{message}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_message(full_message.strip())
        logger.warning(f"アラート送信: {title}")

    def notify_error(self, error_type: str, error_message: str):
        """
        エラー通知

        Args:
            error_type: エラータイプ
            error_message: エラーメッセージ
        """
        message = f"""
🚨 <b>エラー発生</b>

種類: {error_type}
詳細: {error_message}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_message(message.strip())
        logger.error(f"エラー通知送信: {error_type}")

    def notify_info(self, title: str, message: str):
        """
        情報通知

        Args:
            title: タイトル
            message: メッセージ
        """
        full_message = f"""
ℹ️ <b>{title}</b>

{message}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_message(full_message.strip())
        logger.info(f"情報通知送信: {title}")

    def notify_pair_trade_open(
        self,
        pair_id: str,
        symbol1: str,
        symbol2: str,
        direction: str,
        size1: float,
        size2: float,
        price1: float,
        price2: float,
        z_score: float,
        hedge_ratio: float
    ):
        """
        ペアトレード開始通知

        Args:
            pair_id: ペアID
            symbol1: 資産1シンボル
            symbol2: 資産2シンボル
            direction: 'long_spread' or 'short_spread'
            size1: 資産1サイズ
            size2: 資産2サイズ
            price1: 資産1価格
            price2: 資産2価格
            z_score: Zスコア
            hedge_ratio: ヘッジ比率
        """
        if direction == 'long_spread':
            dir_jp = "ロングスプレッド"
            emoji = "🟢"
        else:
            dir_jp = "ショートスプレッド"
            emoji = "🔴"

        total_value = size1 * price1 + size2 * price2

        message = f"""
{emoji} <b>ペアトレード開始</b>

📊 {pair_id}
方向: {dir_jp}

<b>{symbol1}</b>
├ 数量: {size1:.6f}
└ 価格: ¥{price1:,.0f}

<b>{symbol2}</b>
├ 数量: {size2:.6f}
└ 価格: ¥{price2:,.0f}

Zスコア: {z_score:.2f}
ヘッジ比率: {hedge_ratio:.4f}
投入資金: ¥{total_value:,.0f}

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_message(message.strip())
        logger.info(f"ペアトレード開始通知: {pair_id}")

    def notify_pair_trade_close(
        self,
        pair_id: str,
        symbol1: str,
        symbol2: str,
        pnl: float,
        reason: str,
        hold_duration: Optional[str] = None
    ):
        """
        ペアトレード終了通知

        Args:
            pair_id: ペアID
            symbol1: 資産1シンボル
            symbol2: 資産2シンボル
            pnl: 損益
            reason: 終了理由
            hold_duration: 保有期間
        """
        if pnl > 0:
            emoji = "🎉"
            result = "利益確定"
        else:
            emoji = "⚠️"
            result = "損切り"

        reason_jp = {
            'take_profit': '利益目標達成',
            'trailing_stop': 'トレーリングストップ',
            'mean_reversion': '平均回帰',
            'mean_reversion_profit': '平均回帰（利益）',
            'stop_loss': 'ストップロス',
            'direction_change': '方向転換'
        }.get(reason, reason)

        message = f"""
{emoji} <b>ペアトレード{result}</b>

📊 {pair_id}
{symbol1} / {symbol2}

💰 損益: <b>¥{pnl:,.0f}</b>
📝 理由: {reason_jp}
"""
        if hold_duration:
            message += f"⏱️ 保有期間: {hold_duration}\n"

        message += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        self.send_message(message.strip())
        logger.info(f"ペアトレード終了通知: {pair_id} 損益=¥{pnl:,.0f}")


# ヘルパー関数
def create_telegram_notifier(
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    enabled: bool = True
) -> TelegramNotifier:
    """
    Telegram通知インスタンスを作成

    Args:
        bot_token: Bot Token
        chat_id: Chat ID
        enabled: 有効化フラグ

    Returns:
        TelegramNotifierインスタンス
    """
    return TelegramNotifier(bot_token, chat_id, enabled)
