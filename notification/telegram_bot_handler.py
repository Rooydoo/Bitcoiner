"""Telegram Botコマンドハンドラー

ユーザーからのコマンドを受信し、システムを制御
"""

import logging
import threading
import time
from typing import Optional, Dict, Callable
from datetime import datetime
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)


class TelegramBotHandler:
    """Telegram Botコマンドハンドラークラス"""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        allowed_chat_ids: Optional[list] = None,
        trader_instance=None
    ):
        """
        Args:
            bot_token: Telegram Bot Token
            allowed_chat_ids: 許可するChat IDのリスト
            trader_instance: CryptoTraderインスタンス（制御用）
        """
        self.bot_token = bot_token
        self.allowed_chat_ids = allowed_chat_ids or []
        self.trader = trader_instance
        self.enabled = bool(bot_token and self.allowed_chat_ids)

        if not self.enabled:
            logger.warning("Telegram Bot機能が無効です（Token/Chat ID未設定）")
            return

        self.application = None
        self.bot_thread = None
        self.is_running = False

        logger.info(f"Telegram Botハンドラー初期化（許可Chat ID: {len(self.allowed_chat_ids)}件）")

    def _check_authorization(self, update: Update) -> bool:
        """チャットIDの認証確認"""
        chat_id = str(update.effective_chat.id)

        if chat_id not in [str(cid) for cid in self.allowed_chat_ids]:
            logger.warning(f"未認証アクセス試行: Chat ID {chat_id}")
            return False

        return True

    async def _send_reply(self, update: Update, message: str):
        """返信送信"""
        try:
            await update.message.reply_text(message, parse_mode='HTML')
        except Exception as e:
            logger.error(f"返信送信エラー: {e}")

    # ========== コマンドハンドラー ==========

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """システム状態確認コマンド"""
        if not self._check_authorization(update):
            await self._send_reply(update, "⛔ 認証エラー：このBotを使用する権限がありません")
            return

        try:
            if not self.trader:
                await self._send_reply(update, "⚠️ トレーダーインスタンスが未設定です")
                return

            # システム状態取得
            is_running = self.trader.is_running
            trading_paused = self.trader.risk_manager.trading_paused
            positions = self.trader.position_manager.get_all_positions()

            # 残高取得
            try:
                balance = self.trader.order_executor.get_balance('JPY')
                total_balance = balance.get('total', 0)
                available = balance.get('free', 0)
            except:
                total_balance = 0
                available = 0

            # ステータスメッセージ作成
            status_emoji = "🟢" if is_running else "🔴"
            pause_emoji = "⏸️" if trading_paused else "▶️"

            message = f"""
📊 <b>システム状態</b>
━━━━━━━━━━━━━━━━

{status_emoji} 稼働状態: {'稼働中' if is_running else '停止中'}
{pause_emoji} 取引状態: {'一時停止' if trading_paused else 'アクティブ'}

💰 <b>残高</b>
総資産: ¥{total_balance:,.0f}
利用可能: ¥{available:,.0f}

📈 <b>ポジション</b>
保有数: {len(positions)}件
"""

            if positions:
                for pos in positions:
                    try:
                        current_price = self.trader.order_executor.get_current_price(pos.symbol)
                        unrealized_pnl_pct = pos.calculate_unrealized_pnl_pct(current_price)
                        message += f"\n• {pos.symbol} {pos.side.upper()}: {unrealized_pnl_pct:+.2f}%"
                    except:
                        message += f"\n• {pos.symbol} {pos.side.upper()}"

            message += f"\n\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            await self._send_reply(update, message.strip())
            logger.info(f"ステータス確認: Chat ID {update.effective_chat.id}")

        except Exception as e:
            logger.error(f"statusコマンドエラー: {e}")
            await self._send_reply(update, f"⚠️ エラー: {str(e)}")

    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """取引一時停止コマンド"""
        if not self._check_authorization(update):
            await self._send_reply(update, "⛔ 認証エラー：このBotを使用する権限がありません")
            return

        try:
            if not self.trader:
                await self._send_reply(update, "⚠️ トレーダーインスタンスが未設定です")
                return

            self.trader.risk_manager.trading_paused = True
            self.trader.risk_manager.pause_timestamp = datetime.now()

            message = """
⏸️ <b>取引を一時停止しました</b>

新規エントリーを停止します。
既存ポジションは保持されます。

再開するには: /resume
"""
            await self._send_reply(update, message.strip())
            logger.warning(f"取引一時停止: Chat ID {update.effective_chat.id}")

        except Exception as e:
            logger.error(f"pauseコマンドエラー: {e}")
            await self._send_reply(update, f"⚠️ エラー: {str(e)}")

    async def cmd_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """取引再開コマンド"""
        if not self._check_authorization(update):
            await self._send_reply(update, "⛔ 認証エラー：このBotを使用する権限がありません")
            return

        try:
            if not self.trader:
                await self._send_reply(update, "⚠️ トレーダーインスタンスが未設定です")
                return

            self.trader.risk_manager.trading_paused = False
            self.trader.risk_manager.consecutive_losses = 0  # リセット

            message = """
▶️ <b>取引を再開しました</b>

取引が再開されました。
連続損失カウントをリセットしました。
"""
            await self._send_reply(update, message.strip())
            logger.info(f"取引再開: Chat ID {update.effective_chat.id}")

        except Exception as e:
            logger.error(f"resumeコマンドエラー: {e}")
            await self._send_reply(update, f"⚠️ エラー: {str(e)}")

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """保有ポジション確認コマンド"""
        if not self._check_authorization(update):
            await self._send_reply(update, "⛔ 認証エラー：このBotを使用する権限がありません")
            return

        try:
            if not self.trader:
                await self._send_reply(update, "⚠️ トレーダーインスタンスが未設定です")
                return

            positions = self.trader.position_manager.get_all_positions()

            if not positions:
                await self._send_reply(update, "📭 保有ポジションはありません")
                return

            message = "📈 <b>保有ポジション一覧</b>\n━━━━━━━━━━━━━━━━\n"

            total_unrealized_pnl = 0
            for pos in positions:
                try:
                    current_price = self.trader.order_executor.get_current_price(pos.symbol)
                    unrealized_pnl = pos.calculate_unrealized_pnl(current_price)
                    unrealized_pnl_pct = pos.calculate_unrealized_pnl_pct(current_price)
                    total_unrealized_pnl += unrealized_pnl

                    side_emoji = "🟢" if pos.side == "long" else "🔴"
                    pnl_emoji = "📈" if unrealized_pnl > 0 else "📉"

                    message += f"\n{side_emoji} <b>{pos.symbol}</b> {pos.side.upper()}\n"
                    message += f"数量: {pos.quantity:.6f}\n"
                    message += f"エントリー: ¥{pos.entry_price:,.0f}\n"
                    message += f"現在値: ¥{current_price:,.0f}\n"
                    message += f"{pnl_emoji} 損益: <b>¥{unrealized_pnl:,.0f}</b> ({unrealized_pnl_pct:+.2f}%)\n"
                except Exception as e:
                    logger.error(f"ポジション情報取得エラー: {e}")
                    message += f"\n⚠️ {pos.symbol} 情報取得失敗\n"

            message += f"\n━━━━━━━━━━━━━━━━"
            message += f"\n💰 合計未実現損益: <b>¥{total_unrealized_pnl:,.0f}</b>"
            message += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

            await self._send_reply(update, message.strip())
            logger.info(f"ポジション確認: Chat ID {update.effective_chat.id}")

        except Exception as e:
            logger.error(f"positionsコマンドエラー: {e}")
            await self._send_reply(update, f"⚠️ エラー: {str(e)}")

    async def cmd_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """現在の設定表示コマンド"""
        if not self._check_authorization(update):
            await self._send_reply(update, "⛔ 認証エラー：このBotを使用する権限がありません")
            return

        try:
            config_path = Path("config/config.yaml")
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            risk = config.get('risk_management', {})
            trading = config.get('trading', {})

            message = f"""
⚙️ <b>現在の設定</b>
━━━━━━━━━━━━━━━━

<b>リスク管理</b>
• 損切: {risk.get('stop_loss_pct', 10.0)}%
• 利確1: {risk.get('take_profit_first', 15.0)}% (50%決済)
• 利確2: {risk.get('take_profit_second', 25.0)}% (全決済)
• ポジションサイズ: {risk.get('max_position_size', 0.6):.0%}
• 日次損失上限: {risk.get('max_daily_loss_pct', 5.0)}%
• 連続損失制限: {risk.get('consecutive_loss_limit', 5)}回

<b>取引設定</b>
• 最小信頼度: {trading.get('min_confidence', 0.6)}
• 取引間隔: {trading.get('trading_interval_minutes', 5)}分

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            await self._send_reply(update, message.strip())
            logger.info(f"設定確認: Chat ID {update.effective_chat.id}")

        except Exception as e:
            logger.error(f"configコマンドエラー: {e}")
            await self._send_reply(update, f"⚠️ エラー: {str(e)}")

    async def cmd_set_stop_loss(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """損切ライン変更コマンド"""
        if not self._check_authorization(update):
            await self._send_reply(update, "⛔ 認証エラー：このBotを使用する権限がありません")
            return

        try:
            if len(context.args) != 1:
                await self._send_reply(update, "❌ 使い方: /set_stop_loss <値>\n例: /set_stop_loss 8.0")
                return

            new_value = float(context.args[0])

            if new_value < 1.0 or new_value > 30.0:
                await self._send_reply(update, "❌ 値は1.0～30.0の範囲で指定してください")
                return

            # 設定ファイル更新
            config_path = Path("config/config.yaml")
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            old_value = config['risk_management']['stop_loss_pct']
            config['risk_management']['stop_loss_pct'] = new_value

            # バックアップ作成
            backup_path = config_path.parent / f"config.yaml.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            with open(backup_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

            # 保存
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

            # 実行中インスタンスにも反映
            if self.trader:
                self.trader.risk_manager.stop_loss_pct = new_value

            message = f"""
✅ <b>損切ライン変更完了</b>

{old_value}% → <b>{new_value}%</b>

次回取引から適用されます。
バックアップ: {backup_path.name}
"""
            await self._send_reply(update, message.strip())
            logger.info(f"損切ライン変更: {old_value}% → {new_value}% (Chat ID: {update.effective_chat.id})")

        except ValueError:
            await self._send_reply(update, "❌ 数値を正しく入力してください")
        except Exception as e:
            logger.error(f"set_stop_lossコマンドエラー: {e}")
            await self._send_reply(update, f"⚠️ エラー: {str(e)}")

    async def cmd_close_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """全ポジションクローズコマンド"""
        if not self._check_authorization(update):
            await self._send_reply(update, "⛔ 認証エラー：このBotを使用する権限がありません")
            return

        try:
            if not self.trader:
                await self._send_reply(update, "⚠️ トレーダーインスタンスが未設定です")
                return

            positions = self.trader.position_manager.get_all_positions()

            if not positions:
                await self._send_reply(update, "📭 クローズするポジションがありません")
                return

            # 確認メッセージ（引数なしの場合）
            if not context.args or context.args[0].lower() != 'confirm':
                message = f"""
⚠️ <b>全ポジションクローズ確認</b>

{len(positions)}件のポジションをクローズします。

"""
                for pos in positions:
                    message += f"• {pos.symbol} {pos.side.upper()}\n"

                message += """
<b>実行するには:</b>
/close_all confirm
"""
                await self._send_reply(update, message.strip())
                return

            # 実行
            closed_count = 0
            total_pnl = 0.0
            errors = []

            for pos in positions:
                try:
                    current_price = self.trader.order_executor.get_current_price(pos.symbol)

                    # クローズ注文
                    if pos.side == 'long':
                        order = self.trader.order_executor.create_market_sell(
                            pos.symbol, pos.quantity
                        )
                    else:
                        order = self.trader.order_executor.create_market_buy(
                            pos.symbol, pos.quantity
                        )

                    if order:
                        pnl = pos.calculate_unrealized_pnl(current_price)
                        total_pnl += pnl
                        self.trader.position_manager.close_position(pos.symbol)
                        closed_count += 1
                        logger.info(f"ポジションクローズ: {pos.symbol} PnL={pnl:.0f}")
                except Exception as e:
                    errors.append(f"{pos.symbol}: {str(e)}")
                    logger.error(f"クローズエラー: {pos.symbol} - {e}")

            # 取引一時停止
            self.trader.risk_manager.trading_paused = True

            pnl_emoji = "📈" if total_pnl >= 0 else "📉"
            message = f"""
🔴 <b>全ポジションクローズ完了</b>

クローズ: {closed_count}/{len(positions)}件
{pnl_emoji} 実現損益: <b>¥{total_pnl:,.0f}</b>

⏸️ 取引を一時停止しました
再開: /resume
"""
            if errors:
                message += f"\n⚠️ エラー: {len(errors)}件\n"
                for err in errors[:3]:
                    message += f"• {err}\n"

            await self._send_reply(update, message.strip())
            logger.warning(f"全ポジションクローズ実行: {closed_count}件 (Chat ID: {update.effective_chat.id})")

        except Exception as e:
            logger.error(f"close_allコマンドエラー: {e}")
            await self._send_reply(update, f"⚠️ エラー: {str(e)}")

    async def cmd_rebalance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """リバランスコマンド（配分に合わせて超過分を売却）"""
        if not self._check_authorization(update):
            await self._send_reply(update, "⛔ 認証エラー：このBotを使用する権限がありません")
            return

        try:
            if not self.trader:
                await self._send_reply(update, "⚠️ トレーダーインスタンスが未設定です")
                return

            # 設定読み込み
            config_path = Path("config/config.yaml")
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            alloc = config.get('strategy_allocation', {})
            crypto_ratio = alloc.get('crypto_ratio', 0.5)

            # 実際の総資産を計算（現金 + ポジション評価額）
            cash_balance = 0.0
            try:
                balance = self.trader.order_executor.get_balance('JPY')
                cash_balance = balance.get('free', 0) + balance.get('used', 0)
            except:
                pass

            # 現在のポジション価値を計算
            positions = self.trader.position_manager.get_all_positions()
            current_crypto = 0.0

            for pos in positions:
                try:
                    current_price = self.trader.order_executor.get_current_price(pos.symbol)
                    current_crypto += pos.quantity * current_price
                except:
                    pass

            total_assets = cash_balance + current_crypto
            target_crypto = total_assets * crypto_ratio

            excess = current_crypto - target_crypto

            # 確認メッセージ（引数なしの場合）
            if not context.args or context.args[0].lower() != 'confirm':
                if excess <= 0:
                    message = f"""
✅ <b>リバランス不要</b>

総資産: ¥{total_assets:,.0f}
目標コイン: ¥{target_crypto:,.0f} ({crypto_ratio:.0%})
現在コイン: ¥{current_crypto:,.0f}

超過分はありません。
"""
                else:
                    message = f"""
⚖️ <b>リバランス確認</b>

総資産: ¥{total_assets:,.0f}
目標コイン: ¥{target_crypto:,.0f} ({crypto_ratio:.0%})
現在コイン: ¥{current_crypto:,.0f}
超過分: <b>¥{excess:,.0f}</b>

超過分を売却してリバランスします。

<b>実行するには:</b>
/rebalance confirm
"""
                await self._send_reply(update, message.strip())
                return

            if excess <= 0:
                await self._send_reply(update, "✅ リバランス不要です（超過分なし）")
                return

            # リバランス実行（超過分を売却）
            sold_amount = 0.0
            errors = []

            # ポジションを価値順にソート（大きいものから売却）
            pos_with_value = []
            for pos in positions:
                try:
                    current_price = self.trader.order_executor.get_current_price(pos.symbol)
                    value = pos.quantity * current_price
                    pos_with_value.append((pos, current_price, value))
                except Exception as e:
                    errors.append(f"{pos.symbol}: 価格取得失敗")

            pos_with_value.sort(key=lambda x: x[2], reverse=True)

            remaining_excess = excess
            for pos, current_price, value in pos_with_value:
                if remaining_excess <= 0:
                    break

                # 売却数量を計算
                sell_value = min(remaining_excess, value)
                sell_qty = sell_value / current_price

                try:
                    if pos.side == 'long':
                        order = self.trader.order_executor.create_market_sell(
                            pos.symbol, sell_qty
                        )
                    else:
                        order = self.trader.order_executor.create_market_buy(
                            pos.symbol, sell_qty
                        )

                    if order:
                        sold_amount += sell_value
                        remaining_excess -= sell_value

                        # ポジション更新
                        if sell_qty >= pos.quantity:
                            self.trader.position_manager.close_position(pos.symbol)
                        else:
                            pos.quantity -= sell_qty

                        logger.info(f"リバランス売却: {pos.symbol} ¥{sell_value:,.0f}")
                except Exception as e:
                    errors.append(f"{pos.symbol}: {str(e)}")

            message = f"""
⚖️ <b>リバランス完了</b>

売却額: <b>¥{sold_amount:,.0f}</b>
目標との差: ¥{remaining_excess:,.0f}

/allocation で確認できます
"""
            if errors:
                message += f"\n⚠️ エラー: {len(errors)}件\n"
                for err in errors[:3]:
                    message += f"• {err}\n"

            await self._send_reply(update, message.strip())
            logger.info(f"リバランス実行: ¥{sold_amount:,.0f} (Chat ID: {update.effective_chat.id})")

        except Exception as e:
            logger.error(f"rebalanceコマンドエラー: {e}")
            await self._send_reply(update, f"⚠️ エラー: {str(e)}")

    async def cmd_allocation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """戦略配分確認コマンド"""
        if not self._check_authorization(update):
            await self._send_reply(update, "⛔ 認証エラー：このBotを使用する権限がありません")
            return

        try:
            config_path = Path("config/config.yaml")
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            alloc = config.get('strategy_allocation', {})

            # 実際の総資産を計算（現金 + ポジション評価額）
            cash_balance = 0.0
            position_value = 0.0

            if self.trader:
                try:
                    balance = self.trader.order_executor.get_balance('JPY')
                    cash_balance = balance.get('free', 0) + balance.get('used', 0)
                except:
                    pass

                positions = self.trader.position_manager.get_all_positions()
                for pos in positions:
                    try:
                        current_price = self.trader.order_executor.get_current_price(pos.symbol)
                        position_value += pos.quantity * current_price
                    except:
                        pass

            total_assets = cash_balance + position_value

            crypto_ratio = alloc.get('crypto_ratio', 0.5)
            trend_ratio = alloc.get('trend_ratio', 0.5)
            coint_ratio = alloc.get('cointegration_ratio', 0.5)

            target_crypto = total_assets * crypto_ratio
            target_trend = target_crypto * trend_ratio
            target_coint = target_crypto * coint_ratio
            target_cash = total_assets - target_crypto

            message = f"""
📊 <b>戦略配分</b>
━━━━━━━━━━━━━━━━

💰 総資産: ¥{total_assets:,.0f}
├ 現金: ¥{cash_balance:,.0f}
└ ポジション: ¥{position_value:,.0f}

<b>配分比率</b>
• コイン投資: {crypto_ratio:.0%}
• └ トレンド: {trend_ratio:.0%}
• └ 共和分: {coint_ratio:.0%}

<b>目標配分金額</b>
• コイン: ¥{target_crypto:,.0f}
• └ トレンド: ¥{target_trend:,.0f}
• └ 共和分: ¥{target_coint:,.0f}
• 現金保持: ¥{target_cash:,.0f}

<b>変更方法</b>
/set_alloc crypto 0.6
/set_alloc trend 0.5
/set_alloc coint 0.5
"""
            await self._send_reply(update, message.strip())
            logger.info(f"配分確認: Chat ID {update.effective_chat.id}")

        except Exception as e:
            logger.error(f"allocationコマンドエラー: {e}")
            await self._send_reply(update, f"⚠️ エラー: {str(e)}")

    async def cmd_set_allocation(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """戦略配分変更コマンド"""
        if not self._check_authorization(update):
            await self._send_reply(update, "⛔ 認証エラー：このBotを使用する権限がありません")
            return

        try:
            if len(context.args) != 2:
                await self._send_reply(update, """❌ 使い方: /set_alloc <種類> <値>

種類:
• crypto - コイン投資比率
• trend - トレンド戦略比率
• coint - 共和分戦略比率

例: /set_alloc crypto 0.6""")
                return

            alloc_type = context.args[0].lower()
            new_value = float(context.args[1])

            if new_value < 0.0 or new_value > 1.0:
                await self._send_reply(update, "❌ 値は0.0～1.0の範囲で指定してください")
                return

            type_map = {
                'crypto': 'crypto_ratio',
                'trend': 'trend_ratio',
                'coint': 'cointegration_ratio',
                'cointegration': 'cointegration_ratio'
            }

            if alloc_type not in type_map:
                await self._send_reply(update, "❌ 種類は crypto, trend, coint のいずれかを指定してください")
                return

            config_key = type_map[alloc_type]

            # 設定ファイル更新
            config_path = Path("config/config.yaml")
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            if 'strategy_allocation' not in config:
                config['strategy_allocation'] = {}

            old_value = config['strategy_allocation'].get(config_key, 0.5)
            config['strategy_allocation'][config_key] = new_value

            # バックアップ作成
            backup_path = config_path.parent / f"config.yaml.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            with open(backup_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

            # 保存
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

            type_names = {
                'crypto': 'コイン投資比率',
                'trend': 'トレンド戦略比率',
                'coint': '共和分戦略比率'
            }

            message = f"""
✅ <b>配分変更完了</b>

{type_names[alloc_type]}:
{old_value:.0%} → <b>{new_value:.0%}</b>

次回取引から適用されます。
/allocation で確認できます
"""
            await self._send_reply(update, message.strip())
            logger.info(f"配分変更: {alloc_type} {old_value} → {new_value} (Chat ID: {update.effective_chat.id})")

        except ValueError:
            await self._send_reply(update, "❌ 数値を正しく入力してください（例: 0.5）")
        except Exception as e:
            logger.error(f"set_allocationコマンドエラー: {e}")
            await self._send_reply(update, f"⚠️ エラー: {str(e)}")

    async def cmd_commands(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """コマンド一覧（簡潔版）"""
        if not self._check_authorization(update):
            await self._send_reply(update, "⛔ 認証エラー：このBotを使用する権限がありません")
            return

        message = """
📋 <b>コマンド一覧</b>

/status - 状態確認
/positions - ポジション
/config - 設定表示
/allocation - 戦略配分確認
/pause - 一時停止
/resume - 再開
/close_all - 全ポジション売却
/rebalance - 配分に合わせてリバランス
/set_stop_loss <値> - 損切変更
/set_alloc <種類> <値> - 配分変更
/commands - この一覧
/help - 詳細ヘルプ

💡 「/」を入力するとコマンド候補が表示されます
"""
        await self._send_reply(update, message.strip())

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ヘルプコマンド（詳細版）"""
        if not self._check_authorization(update):
            await self._send_reply(update, "⛔ 認証エラー：このBotを使用する権限がありません")
            return

        message = """
🤖 <b>利用可能なコマンド</b>
━━━━━━━━━━━━━━━━

📊 <b>情報取得</b>
/status - システム状態確認
/positions - 保有ポジション一覧
/config - 現在の設定表示

⚙️ <b>制御</b>
/pause - 取引一時停止
/resume - 取引再開

🔧 <b>設定変更</b>
/set_stop_loss <値> - 損切ライン変更
例: /set_stop_loss 8.0

❓ <b>その他</b>
/commands - コマンド一覧（簡潔版）
/help - この詳細ヘルプ

💡 <b>ヒント</b>
チャット入力欄で「/」を入力すると
コマンド候補が自動的に表示されます！
"""
        await self._send_reply(update, message.strip())

    # ========== Bot起動・停止 ==========

    def start(self):
        """Bot起動（別スレッドで実行）"""
        if not self.enabled:
            logger.warning("Bot機能が無効のため起動できません")
            return

        if self.is_running:
            logger.warning("Bot既に起動中")
            return

        async def setup_bot():
            """Bot初期設定"""
            try:
                # コマンドリスト設定（Telegram UIでコマンド候補を表示）
                commands = [
                    BotCommand("status", "システム状態確認"),
                    BotCommand("positions", "保有ポジション一覧"),
                    BotCommand("config", "現在の設定表示"),
                    BotCommand("allocation", "戦略配分確認"),
                    BotCommand("pause", "取引一時停止"),
                    BotCommand("resume", "取引再開"),
                    BotCommand("close_all", "全ポジション売却"),
                    BotCommand("rebalance", "配分に合わせてリバランス"),
                    BotCommand("set_stop_loss", "損切ライン変更"),
                    BotCommand("set_alloc", "戦略配分変更"),
                    BotCommand("commands", "コマンド一覧"),
                    BotCommand("help", "詳細ヘルプ"),
                ]
                await self.application.bot.set_my_commands(commands)
                logger.info("Botコマンドリスト設定完了")
            except Exception as e:
                logger.warning(f"Botコマンドリスト設定エラー: {e}")

        def run_bot():
            """Botメインループ"""
            try:
                # Application作成
                self.application = Application.builder().token(self.bot_token).build()

                # コマンドハンドラー登録
                self.application.add_handler(CommandHandler("status", self.cmd_status))
                self.application.add_handler(CommandHandler("pause", self.cmd_pause))
                self.application.add_handler(CommandHandler("resume", self.cmd_resume))
                self.application.add_handler(CommandHandler("positions", self.cmd_positions))
                self.application.add_handler(CommandHandler("config", self.cmd_config))
                self.application.add_handler(CommandHandler("allocation", self.cmd_allocation))
                self.application.add_handler(CommandHandler("close_all", self.cmd_close_all))
                self.application.add_handler(CommandHandler("rebalance", self.cmd_rebalance))
                self.application.add_handler(CommandHandler("set_stop_loss", self.cmd_set_stop_loss))
                self.application.add_handler(CommandHandler("set_alloc", self.cmd_set_allocation))
                self.application.add_handler(CommandHandler("commands", self.cmd_commands))
                self.application.add_handler(CommandHandler("help", self.cmd_help))
                self.application.add_handler(CommandHandler("start", self.cmd_commands))

                logger.info("Telegram Bot起動中...")

                # 起動時初期設定
                self.application.job_queue.run_once(
                    lambda context: setup_bot(),
                    when=0
                )

                # Polling開始
                self.application.run_polling(allowed_updates=Update.ALL_TYPES)

            except Exception as e:
                logger.error(f"Bot実行エラー: {e}")
                self.is_running = False

        self.is_running = True
        self.bot_thread = threading.Thread(target=run_bot, daemon=True)
        self.bot_thread.start()
        logger.info("Telegram Botスレッド起動完了")

    def stop(self):
        """Bot停止"""
        if not self.is_running:
            return

        logger.info("Telegram Bot停止中...")
        self.is_running = False

        if self.application:
            try:
                self.application.stop()
            except:
                pass

        logger.info("Telegram Bot停止完了")
