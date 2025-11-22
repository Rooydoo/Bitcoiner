"""レポート生成モジュール

日次/週次/月次レポートを定型フォーマットで生成
"""

import logging
import sys
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import pandas as pd
from data.storage.sqlite_manager import SQLiteManager

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.strategy_advisor import create_strategy_advisor
from utils.performance_ratio import create_performance_analyzer

logger = logging.getLogger(__name__)


class ReportGenerator:
    """レポート生成クラス"""

    def __init__(self, db_manager: SQLiteManager, data_collector=None):
        """
        Args:
            db_manager: SQLiteManagerインスタンス
            data_collector: データ収集インスタンス（パフォーマンス比較用）
        """
        self.db_manager = db_manager
        self.data_collector = data_collector
        self.strategy_advisor = create_strategy_advisor()
        self.performance_analyzer = create_performance_analyzer(data_collector)
        logger.info("レポート生成システム初期化")

    def generate_daily_report(self, date: Optional[datetime] = None) -> str:
        """
        日次レポートを生成

        Args:
            date: 対象日（Noneの場合は今日）

        Returns:
            レポートテキスト
        """
        if date is None:
            date = datetime.now()

        date_str = date.strftime('%Y-%m-%d')

        # 日次データ取得（DBから）
        daily_data = self._get_daily_data(date)

        report = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【日次レポート】{date_str}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【資産状況】
総資産: ¥{daily_data['total_equity']:,.0f}
前日比: ¥{daily_data['daily_pnl']:,.0f} ({daily_data['daily_pnl_pct']:+.2f}%)
初期資金: ¥{daily_data['initial_capital']:,.0f}
総損益: ¥{daily_data['total_pnl']:,.0f} ({daily_data['total_pnl_pct']:+.2f}%)

【取引実績】
取引回数: {daily_data['trades_count']}回
勝ち: {daily_data['winning_trades']}回
負け: {daily_data['losing_trades']}回
勝率: {daily_data['win_rate']:.1%}

平均利益: ¥{daily_data['avg_win']:,.0f}
平均損失: ¥{daily_data['avg_loss']:,.0f}
プロフィット率: {daily_data['profit_factor']:.2f}

【保有ポジション】
"""

        if daily_data['open_positions']:
            for pos in daily_data['open_positions']:
                report += f"""
• {pos['symbol']} {pos['side'].upper()}
  エントリー: ¥{pos['entry_price']:,.0f}
  現在価格: ¥{pos['current_price']:,.0f}
  数量: {pos['quantity']:.6f}
  未実現損益: ¥{pos['unrealized_pnl']:,.0f} ({pos['unrealized_pnl_pct']:+.2f}%)
  保有時間: {pos['holding_hours']:.1f}時間
"""
        else:
            report += "\nなし\n"

        report += f"""
【本日の取引】
"""

        if daily_data['today_trades']:
            for i, trade in enumerate(daily_data['today_trades'], 1):
                pnl_emoji = "📈" if trade['pnl'] > 0 else "📉"
                report += f"""
{i}. {trade['symbol']} {trade['side'].upper()}
   {pnl_emoji} 損益: ¥{trade['pnl']:,.0f} ({trade['pnl_pct']:+.2f}%)
   {trade['entry_time']} → {trade['exit_time']}
"""
        else:
            report += "\nなし\n"

        report += f"""
【リスク指標】
最大ドローダウン: {daily_data['max_drawdown_pct']:.2f}%
シャープレシオ: {daily_data['sharpe_ratio']:.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        logger.info(f"日次レポート生成完了: {date_str}")
        return report.strip()

    def generate_weekly_report(self, end_date: Optional[datetime] = None) -> str:
        """
        週次レポートを生成

        Args:
            end_date: 終了日（Noneの場合は今日）

        Returns:
            レポートテキスト
        """
        if end_date is None:
            end_date = datetime.now()

        start_date = end_date - timedelta(days=7)

        period_str = f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}"

        # 週次データ取得
        weekly_data = self._get_weekly_data(start_date, end_date)

        report = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【週次レポート】{period_str}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【資産状況】
総資産: ¥{weekly_data['total_equity']:,.0f}
週次損益: ¥{weekly_data['weekly_pnl']:,.0f} ({weekly_data['weekly_pnl_pct']:+.2f}%)
総損益: ¥{weekly_data['total_pnl']:,.0f} ({weekly_data['total_pnl_pct']:+.2f}%)

【取引実績】
取引回数: {weekly_data['trades_count']}回
勝ち: {weekly_data['winning_trades']}回
負け: {weekly_data['losing_trades']}回
勝率: {weekly_data['win_rate']:.1%}

総利益: ¥{weekly_data['total_profit']:,.0f}
総損失: ¥{weekly_data['total_loss']:,.0f}
プロフィット率: {weekly_data['profit_factor']:.2f}

平均保有時間: {weekly_data['avg_holding_hours']:.1f}時間

【日別損益】
"""

        for day_pnl in weekly_data['daily_pnl_list']:
            emoji = "📈" if day_pnl['pnl'] > 0 else "📉" if day_pnl['pnl'] < 0 else "➖"
            report += f"{day_pnl['date']}: {emoji} ¥{day_pnl['pnl']:,.0f}\n"

        report += f"""
【リスク指標】
最大ドローダウン: {weekly_data['max_drawdown_pct']:.2f}%
シャープレシオ: {weekly_data['sharpe_ratio']:.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        # 戦略調整の提案を追加
        try:
            suggestions = self.strategy_advisor.analyze_and_suggest(weekly_data, period_type='weekly')
            report += "\n" + self.strategy_advisor.format_suggestions_for_report(suggestions)
        except Exception as e:
            logger.error(f"戦略提案生成エラー: {e}")

        # パフォーマンス比較を追加
        try:
            if self.data_collector:
                # 取引中のペアを取得（config.yamlから）
                import yaml
                from pathlib import Path
                config_path = Path("config/config.yaml")
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                trading_pairs = [p['symbol'] for p in config.get('trading_pairs', [])]

                # パフォーマンス比較分析
                performance_results = self.performance_analyzer.calculate_performance_ratios(
                    trading_pairs=trading_pairs,
                    period_days=7
                )

                if performance_results:
                    report += "\n" + self.performance_analyzer.format_report(performance_results)
        except Exception as e:
            logger.error(f"パフォーマンス比較エラー: {e}")

        logger.info(f"週次レポート生成完了: {period_str}")
        return report.strip()

    def generate_monthly_report(self, end_date: Optional[datetime] = None) -> str:
        """
        月次レポートを生成

        Args:
            end_date: 終了日（Noneの場合は今日）

        Returns:
            レポートテキスト
        """
        if end_date is None:
            end_date = datetime.now()

        # 月初を計算
        start_date = end_date.replace(day=1)

        period_str = f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}"
        month_str = end_date.strftime('%Y年%m月')

        # 月次データ取得
        monthly_data = self._get_monthly_data(start_date, end_date)

        report = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【月次レポート】{month_str}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【資産状況】
総資産: ¥{monthly_data['total_equity']:,.0f}
月次損益: ¥{monthly_data['monthly_pnl']:,.0f} ({monthly_data['monthly_pnl_pct']:+.2f}%)
総損益: ¥{monthly_data['total_pnl']:,.0f} ({monthly_data['total_pnl_pct']:+.2f}%)

【取引実績】
取引回数: {monthly_data['trades_count']}回
勝ち: {monthly_data['winning_trades']}回
負け: {monthly_data['losing_trades']}回
勝率: {monthly_data['win_rate']:.1%}

総利益: ¥{monthly_data['total_profit']:,.0f}
総損失: ¥{monthly_data['total_loss']:,.0f}
プロフィット率: {monthly_data['profit_factor']:.2f}

平均保有時間: {monthly_data['avg_holding_hours']:.1f}時間

【週別損益】
"""

        for week_pnl in monthly_data['weekly_pnl_list']:
            emoji = "📈" if week_pnl['pnl'] > 0 else "📉" if week_pnl['pnl'] < 0 else "➖"
            report += f"第{week_pnl['week']}週: {emoji} ¥{week_pnl['pnl']:,.0f} ({week_pnl['pnl_pct']:+.2f}%)\n"

        report += f"""
【リスク指標】
最大ドローダウン: {monthly_data['max_drawdown_pct']:.2f}%
シャープレシオ: {monthly_data['sharpe_ratio']:.2f}
ボラティリティ: {monthly_data['volatility']:.2f}%

【ベストトレード】
{monthly_data['best_trade']['symbol']} {monthly_data['best_trade']['side'].upper()}
損益: ¥{monthly_data['best_trade']['pnl']:,.0f} ({monthly_data['best_trade']['pnl_pct']:+.2f}%)

【ワーストトレード】
{monthly_data['worst_trade']['symbol']} {monthly_data['worst_trade']['side'].upper()}
損益: ¥{monthly_data['worst_trade']['pnl']:,.0f} ({monthly_data['worst_trade']['pnl_pct']:+.2f}%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        # 戦略調整の提案を追加（月次は詳細分析）
        try:
            suggestions = self.strategy_advisor.analyze_and_suggest(monthly_data, period_type='monthly')
            report += "\n" + self.strategy_advisor.format_suggestions_for_report(suggestions)
        except Exception as e:
            logger.error(f"戦略提案生成エラー: {e}")

        # パフォーマンス比較を追加
        try:
            if self.data_collector:
                # 取引中のペアを取得（config.yamlから）
                import yaml
                from pathlib import Path
                config_path = Path("config/config.yaml")
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                trading_pairs = [p['symbol'] for p in config.get('trading_pairs', [])]

                # パフォーマンス比較分析（月次は30日間）
                performance_results = self.performance_analyzer.calculate_performance_ratios(
                    trading_pairs=trading_pairs,
                    period_days=30
                )

                if performance_results:
                    report += "\n" + self.performance_analyzer.format_report(performance_results)
        except Exception as e:
            logger.error(f"パフォーマンス比較エラー: {e}")

        logger.info(f"月次レポート生成完了: {period_str}")
        return report.strip()

    def generate_summary_stats(self) -> Dict:
        """
        統計サマリーを生成（実DB）

        Returns:
            統計情報の辞書
        """
        import sqlite3

        initial_capital = 200000
        try:
            from pathlib import Path
            import yaml
            config_path = Path("config/config.yaml")
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    initial_capital = config.get('trading', {}).get('initial_capital', 200000)
        except Exception:
            pass

        # 全期間の日次損益を取得
        today_str = datetime.now().strftime('%Y-%m-%d')
        all_pnl_df = self.db_manager.get_daily_pnl('2000-01-01', today_str)

        # 集計値
        total_trades = int(all_pnl_df['total_trades'].sum()) if not all_pnl_df.empty else 0
        winning_trades = int(all_pnl_df['winning_trades'].sum()) if not all_pnl_df.empty else 0
        losing_trades = int(all_pnl_df['losing_trades'].sum()) if not all_pnl_df.empty else 0
        total_profit = float(all_pnl_df['total_profit'].sum()) if not all_pnl_df.empty else 0
        total_loss = float(all_pnl_df['total_loss'].sum()) if not all_pnl_df.empty else 0
        total_pnl = float(all_pnl_df['net_pnl'].sum()) if not all_pnl_df.empty else 0
        win_rate = winning_trades / total_trades if total_trades > 0 else 0

        # 全ポジション（決済済み）を取得
        # BLOCKER-3: 安全な接続メソッドを使用
        conn = self.db_manager.get_connection(self.db_manager.trades_db)

        query = "SELECT * FROM positions WHERE status = 'closed'"
        positions_df = pd.read_sql_query(query, conn)
        conn.close()

        # 平均保有時間
        avg_holding_hours = 0.0
        if not positions_df.empty:
            avg_holding_hours = float(positions_df['hold_time_hours'].mean())

        # 平均勝利/損失
        avg_win = total_profit / winning_trades if winning_trades > 0 else 0
        avg_loss = total_loss / losing_trades if losing_trades > 0 else 0

        # プロフィットファクター
        profit_factor = abs(total_profit / total_loss) if total_loss != 0 else 0

        stats = {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_pnl_pct': (total_pnl / initial_capital * 100) if initial_capital > 0 else 0,
            'avg_win': avg_win,
            'avg_loss': -avg_loss,  # 負の値で表示
            'profit_factor': profit_factor,
            'max_drawdown_pct': 0.0,  # 簡易実装
            'sharpe_ratio': 0.0,  # 簡易実装
            'avg_holding_hours': avg_holding_hours
        }

        return stats

    def _get_daily_data(self, date: datetime) -> Dict:
        """日次データを取得（実DB）"""
        import sqlite3

        date_str = date.strftime('%Y-%m-%d')
        initial_capital = 200000  # デフォルト値

        try:
            # 設定ファイルから初期資本を取得
            from pathlib import Path
            import yaml
            config_path = Path("config/config.yaml")
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    initial_capital = config.get('trading', {}).get('initial_capital', 200000)
        except Exception:
            pass

        # 日次損益データ取得
        daily_pnl_df = self.db_manager.get_daily_pnl(date_str, date_str)

        if not daily_pnl_df.empty:
            row = daily_pnl_df.iloc[0]
            trades_count = int(row.get('total_trades', 0))
            winning_trades = int(row.get('winning_trades', 0))
            losing_trades = int(row.get('losing_trades', 0))
            total_profit = float(row.get('total_profit', 0))
            total_loss = float(row.get('total_loss', 0))
            daily_pnl = float(row.get('net_pnl', 0))
            win_rate = float(row.get('win_rate', 0))
        else:
            trades_count = winning_trades = losing_trades = 0
            total_profit = total_loss = daily_pnl = win_rate = 0.0

        # 累積損益を計算（全期間の日次損益を合計）
        all_pnl_df = self.db_manager.get_daily_pnl('2000-01-01', date_str)
        total_pnl = float(all_pnl_df['net_pnl'].sum()) if not all_pnl_df.empty else 0.0
        total_equity = initial_capital + total_pnl

        # オープンポジション取得
        open_positions_df = self.db_manager.get_open_positions()
        open_positions = []

        for _, pos in open_positions_df.iterrows():
            # 現在価格を取得（実際にはAPI呼び出しが必要だがここでは簡易実装）
            current_price = float(pos.get('entry_price', 0))  # 仮に entry_price を使用
            entry_price = float(pos.get('entry_price', 0))
            quantity = float(pos.get('entry_amount', 0))

            unrealized_pnl = (current_price - entry_price) * quantity
            unrealized_pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

            entry_time = pd.to_datetime(pos.get('entry_time', 0), unit='s')
            holding_hours = (datetime.now() - entry_time).total_seconds() / 3600

            open_positions.append({
                'symbol': str(pos.get('symbol', '')),
                'side': str(pos.get('side', '')),
                'entry_price': entry_price,
                'current_price': current_price,
                'quantity': quantity,
                'unrealized_pnl': unrealized_pnl,
                'unrealized_pnl_pct': unrealized_pnl_pct,
                'holding_hours': holding_hours
            })

        # 当日の決済済み取引を取得
        # BLOCKER-3: 安全な接続メソッドを使用
        conn = self.db_manager.get_connection(self.db_manager.trades_db)

        # 日付の開始・終了タイムスタンプ
        start_ts = int(date.replace(hour=0, minute=0, second=0).timestamp())
        end_ts = int(date.replace(hour=23, minute=59, second=59).timestamp())

        query = """
        SELECT * FROM positions
        WHERE status = 'closed'
        AND exit_time >= ? AND exit_time <= ?
        ORDER BY exit_time ASC
        """

        trades_df = pd.read_sql_query(query, conn, params=[start_ts, end_ts])
        conn.close()

        today_trades = []
        for _, trade in trades_df.iterrows():
            entry_time = pd.to_datetime(trade.get('entry_time', 0), unit='s').strftime('%H:%M')
            exit_time = pd.to_datetime(trade.get('exit_time', 0), unit='s').strftime('%H:%M')

            today_trades.append({
                'symbol': str(trade.get('symbol', '')),
                'side': str(trade.get('side', '')),
                'pnl': float(trade.get('profit_loss', 0)),
                'pnl_pct': float(trade.get('profit_loss_pct', 0)),
                'entry_time': entry_time,
                'exit_time': exit_time
            })

        # 平均勝利/損失
        avg_win = total_profit / winning_trades if winning_trades > 0 else 0
        avg_loss = abs(total_loss) / losing_trades if losing_trades > 0 else 0
        profit_factor = abs(total_profit / total_loss) if total_loss != 0 else 0

        return {
            'total_equity': total_equity,
            'daily_pnl': daily_pnl,
            'daily_pnl_pct': (daily_pnl / initial_capital * 100) if initial_capital > 0 else 0,
            'initial_capital': initial_capital,
            'total_pnl': total_pnl,
            'total_pnl_pct': (total_pnl / initial_capital * 100) if initial_capital > 0 else 0,
            'trades_count': trades_count,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'open_positions': open_positions,
            'today_trades': today_trades,
            'max_drawdown_pct': 0.0,  # 計算は複雑なので簡易実装
            'sharpe_ratio': 0.0  # 計算は複雑なので簡易実装
        }

    def _get_weekly_data(self, start_date: datetime, end_date: datetime) -> Dict:
        """週次データを取得（実DB）"""
        import sqlite3

        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')

        initial_capital = 200000
        try:
            from pathlib import Path
            import yaml
            config_path = Path("config/config.yaml")
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    initial_capital = config.get('trading', {}).get('initial_capital', 200000)
        except Exception:
            pass

        # 期間内の日次損益を取得
        daily_pnl_df = self.db_manager.get_daily_pnl(start_str, end_str)

        # 日別損益リスト作成
        daily_pnl_list = []
        for _, row in daily_pnl_df.iterrows():
            daily_pnl_list.append({
                'date': str(row.get('date', '')),
                'pnl': float(row.get('net_pnl', 0))
            })

        # 集計値
        trades_count = int(daily_pnl_df['total_trades'].sum())
        winning_trades = int(daily_pnl_df['winning_trades'].sum())
        losing_trades = int(daily_pnl_df['losing_trades'].sum())
        total_profit = float(daily_pnl_df['total_profit'].sum())
        total_loss = float(daily_pnl_df['total_loss'].sum())
        weekly_pnl = float(daily_pnl_df['net_pnl'].sum())
        win_rate = winning_trades / trades_count if trades_count > 0 else 0

        # 累積損益
        all_pnl_df = self.db_manager.get_daily_pnl('2000-01-01', end_str)
        total_pnl = float(all_pnl_df['net_pnl'].sum()) if not all_pnl_df.empty else 0.0
        total_equity = initial_capital + total_pnl

        # 期間内のポジションを取得して平均保有時間を計算
        # BLOCKER-3: 安全な接続メソッドを使用
        conn = self.db_manager.get_connection(self.db_manager.trades_db)

        start_ts = int(start_date.timestamp())
        end_ts = int(end_date.timestamp())

        query = """
        SELECT * FROM positions
        WHERE status = 'closed'
        AND exit_time >= ? AND exit_time <= ?
        """

        positions_df = pd.read_sql_query(query, conn, params=[start_ts, end_ts])

        avg_holding_hours = 0.0
        if not positions_df.empty:
            avg_holding_hours = float(positions_df['hold_time_hours'].mean())

        # 通貨ペア別パフォーマンス
        pair_performance = {}

        for symbol in ['BTC/JPY', 'ETH/JPY']:
            symbol_positions = positions_df[positions_df['symbol'] == symbol]

            if not symbol_positions.empty:
                wins = len(symbol_positions[symbol_positions['profit_loss'] > 0])
                total = len(symbol_positions)
                profits = symbol_positions[symbol_positions['profit_loss'] > 0]['profit_loss'].sum()
                losses = abs(symbol_positions[symbol_positions['profit_loss'] < 0]['profit_loss'].sum())

                pair_performance[symbol] = {
                    'win_rate': wins / total if total > 0 else 0,
                    'profit_factor': profits / losses if losses > 0 else 0,
                    'sharpe_ratio': 0.0,  # 簡易実装
                    'trades': total
                }

        conn.close()

        profit_factor = abs(total_profit / total_loss) if total_loss != 0 else 0

        return {
            'total_equity': total_equity,
            'weekly_pnl': weekly_pnl,
            'weekly_pnl_pct': (weekly_pnl / initial_capital * 100) if initial_capital > 0 else 0,
            'total_pnl': total_pnl,
            'total_pnl_pct': (total_pnl / initial_capital * 100) if initial_capital > 0 else 0,
            'trades_count': trades_count,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'total_profit': total_profit,
            'total_loss': abs(total_loss),
            'profit_factor': profit_factor,
            'avg_holding_hours': avg_holding_hours,
            'daily_pnl_list': daily_pnl_list,
            'max_drawdown_pct': 0.0,  # 簡易実装
            'sharpe_ratio': 0.0,  # 簡易実装
            'pair_performance': pair_performance
        }

    def _get_monthly_data(self, start_date: datetime, end_date: datetime) -> Dict:
        """月次データを取得（実DB）"""
        import sqlite3

        start_str = start_date.strftime('%Y-%m-%d')
        end_str = end_date.strftime('%Y-%m-%d')

        initial_capital = 200000
        try:
            from pathlib import Path
            import yaml
            config_path = Path("config/config.yaml")
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    initial_capital = config.get('trading', {}).get('initial_capital', 200000)
        except Exception:
            pass

        # 期間内の日次損益を取得
        daily_pnl_df = self.db_manager.get_daily_pnl(start_str, end_str)

        # 週別損益リスト作成
        weekly_pnl_list = []
        if not daily_pnl_df.empty:
            daily_pnl_df['date'] = pd.to_datetime(daily_pnl_df['date'])
            daily_pnl_df['week'] = daily_pnl_df['date'].dt.isocalendar().week

            for week, group in daily_pnl_df.groupby('week'):
                week_pnl = float(group['net_pnl'].sum())
                weekly_pnl_list.append({
                    'week': int(week),
                    'pnl': week_pnl,
                    'pnl_pct': (week_pnl / initial_capital * 100) if initial_capital > 0 else 0
                })

        # 集計値
        trades_count = int(daily_pnl_df['total_trades'].sum()) if not daily_pnl_df.empty else 0
        winning_trades = int(daily_pnl_df['winning_trades'].sum()) if not daily_pnl_df.empty else 0
        losing_trades = int(daily_pnl_df['losing_trades'].sum()) if not daily_pnl_df.empty else 0
        total_profit = float(daily_pnl_df['total_profit'].sum()) if not daily_pnl_df.empty else 0
        total_loss = float(daily_pnl_df['total_loss'].sum()) if not daily_pnl_df.empty else 0
        monthly_pnl = float(daily_pnl_df['net_pnl'].sum()) if not daily_pnl_df.empty else 0
        win_rate = winning_trades / trades_count if trades_count > 0 else 0

        # 累積損益
        all_pnl_df = self.db_manager.get_daily_pnl('2000-01-01', end_str)
        total_pnl = float(all_pnl_df['net_pnl'].sum()) if not all_pnl_df.empty else 0.0
        total_equity = initial_capital + total_pnl

        # 期間内のポジションを取得
        # BLOCKER-3: 安全な接続メソッドを使用
        conn = self.db_manager.get_connection(self.db_manager.trades_db)

        start_ts = int(start_date.timestamp())
        end_ts = int(end_date.timestamp())

        query = """
        SELECT * FROM positions
        WHERE status = 'closed'
        AND exit_time >= ? AND exit_time <= ?
        """

        positions_df = pd.read_sql_query(query, conn, params=[start_ts, end_ts])

        # 平均保有時間
        avg_holding_hours = 0.0
        if not positions_df.empty:
            avg_holding_hours = float(positions_df['hold_time_hours'].mean())

        # ベスト・ワーストトレード
        best_trade = {'symbol': '-', 'side': '-', 'pnl': 0, 'pnl_pct': 0}
        worst_trade = {'symbol': '-', 'side': '-', 'pnl': 0, 'pnl_pct': 0}

        if not positions_df.empty:
            best_idx = positions_df['profit_loss'].idxmax()
            worst_idx = positions_df['profit_loss'].idxmin()

            if pd.notna(best_idx):
                best = positions_df.loc[best_idx]
                best_trade = {
                    'symbol': str(best.get('symbol', '-')),
                    'side': str(best.get('side', '-')),
                    'pnl': float(best.get('profit_loss', 0)),
                    'pnl_pct': float(best.get('profit_loss_pct', 0))
                }

            if pd.notna(worst_idx):
                worst = positions_df.loc[worst_idx]
                worst_trade = {
                    'symbol': str(worst.get('symbol', '-')),
                    'side': str(worst.get('side', '-')),
                    'pnl': float(worst.get('profit_loss', 0)),
                    'pnl_pct': float(worst.get('profit_loss_pct', 0))
                }

        # 通貨ペア別パフォーマンス
        pair_performance = {}

        for symbol in ['BTC/JPY', 'ETH/JPY']:
            symbol_positions = positions_df[positions_df['symbol'] == symbol]

            if not symbol_positions.empty:
                wins = len(symbol_positions[symbol_positions['profit_loss'] > 0])
                total = len(symbol_positions)
                profits = symbol_positions[symbol_positions['profit_loss'] > 0]['profit_loss'].sum()
                losses = abs(symbol_positions[symbol_positions['profit_loss'] < 0]['profit_loss'].sum())

                pair_performance[symbol] = {
                    'win_rate': wins / total if total > 0 else 0,
                    'profit_factor': profits / losses if losses > 0 else 0,
                    'sharpe_ratio': 0.0,  # 簡易実装
                    'trades': total
                }

        conn.close()

        # ボラティリティ（日次損益の標準偏差）
        volatility = 0.0
        if not daily_pnl_df.empty and len(daily_pnl_df) > 1:
            volatility = float(daily_pnl_df['net_pnl'].std())

        profit_factor = abs(total_profit / total_loss) if total_loss != 0 else 0

        return {
            'total_equity': total_equity,
            'monthly_pnl': monthly_pnl,
            'monthly_pnl_pct': (monthly_pnl / initial_capital * 100) if initial_capital > 0 else 0,
            'total_pnl': total_pnl,
            'total_pnl_pct': (total_pnl / initial_capital * 100) if initial_capital > 0 else 0,
            'trades_count': trades_count,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'total_profit': total_profit,
            'total_loss': abs(total_loss),
            'profit_factor': profit_factor,
            'avg_holding_hours': avg_holding_hours,
            'weekly_pnl_list': weekly_pnl_list,
            'max_drawdown_pct': 0.0,  # 簡易実装
            'sharpe_ratio': 0.0,  # 簡易実装
            'volatility': volatility,
            'best_trade': best_trade,
            'worst_trade': worst_trade,
            'pair_performance': pair_performance
        }


# ヘルパー関数
def create_report_generator(db_manager: SQLiteManager) -> ReportGenerator:
    """
    レポート生成インスタンスを作成

    Args:
        db_manager: SQLiteManagerインスタンス

    Returns:
        ReportGeneratorインスタンス
    """
    return ReportGenerator(db_manager)
