"""レポート生成モジュール

日次/週次/月次レポートを定型フォーマットで生成
"""

import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta
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
        # TODO: 実際のDB取得ロジック実装
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
        統計サマリーを生成

        Returns:
            統計情報の辞書
        """
        # TODO: 実際のDB取得ロジック
        stats = {
            'total_trades': 10,
            'winning_trades': 7,
            'losing_trades': 3,
            'win_rate': 0.7,
            'total_pnl': 10000,
            'total_pnl_pct': 5.0,
            'avg_win': 2000,
            'avg_loss': -1000,
            'profit_factor': 2.0,
            'max_drawdown_pct': 5.0,
            'sharpe_ratio': 1.5,
            'avg_holding_hours': 12.5
        }

        return stats

    def _get_daily_data(self, date: datetime) -> Dict:
        """日次データを取得（モック）"""
        # TODO: 実際のDB取得ロジック実装
        return {
            'total_equity': 205000,
            'daily_pnl': 5000,
            'daily_pnl_pct': 2.5,
            'initial_capital': 200000,
            'total_pnl': 5000,
            'total_pnl_pct': 2.5,
            'trades_count': 2,
            'winning_trades': 2,
            'losing_trades': 0,
            'win_rate': 1.0,
            'avg_win': 2500,
            'avg_loss': 0,
            'profit_factor': 0,
            'open_positions': [],
            'today_trades': [
                {
                    'symbol': 'BTC/JPY',
                    'side': 'long',
                    'pnl': 3000,
                    'pnl_pct': 2.5,
                    'entry_time': '09:00',
                    'exit_time': '15:00'
                },
                {
                    'symbol': 'ETH/JPY',
                    'side': 'long',
                    'pnl': 2000,
                    'pnl_pct': 2.0,
                    'entry_time': '10:00',
                    'exit_time': '16:00'
                }
            ],
            'max_drawdown_pct': 3.0,
            'sharpe_ratio': 1.2
        }

    def _get_weekly_data(self, start_date: datetime, end_date: datetime) -> Dict:
        """週次データを取得（モック）"""
        # TODO: 実際のDB取得ロジック実装
        daily_pnl_list = []
        current_date = start_date

        while current_date <= end_date:
            daily_pnl_list.append({
                'date': current_date.strftime('%Y-%m-%d'),
                'pnl': 1000 if current_date.weekday() < 5 else 0
            })
            current_date += timedelta(days=1)

        return {
            'total_equity': 210000,
            'weekly_pnl': 10000,
            'weekly_pnl_pct': 5.0,
            'total_pnl': 10000,
            'total_pnl_pct': 5.0,
            'trades_count': 10,
            'winning_trades': 7,
            'losing_trades': 3,
            'win_rate': 0.7,
            'total_profit': 14000,
            'total_loss': 4000,
            'profit_factor': 3.5,
            'avg_holding_hours': 15.0,
            'daily_pnl_list': daily_pnl_list,
            'max_drawdown_pct': 5.0,
            'sharpe_ratio': 1.5,
            # 通貨ペア別パフォーマンス
            'pair_performance': {
                'BTC/JPY': {
                    'win_rate': 0.75,
                    'profit_factor': 4.0,
                    'sharpe_ratio': 1.8,
                    'trades': 6
                },
                'ETH/JPY': {
                    'win_rate': 0.60,
                    'profit_factor': 2.5,
                    'sharpe_ratio': 1.2,
                    'trades': 4
                }
            }
        }

    def _get_monthly_data(self, start_date: datetime, end_date: datetime) -> Dict:
        """月次データを取得（モック）"""
        # TODO: 実際のDB取得ロジック実装
        weekly_pnl_list = []

        for week in range(1, 5):
            weekly_pnl_list.append({
                'week': week,
                'pnl': 5000 + (week * 1000),
                'pnl_pct': 2.5 + (week * 0.5)
            })

        return {
            'total_equity': 230000,
            'monthly_pnl': 30000,
            'monthly_pnl_pct': 15.0,
            'total_pnl': 30000,
            'total_pnl_pct': 15.0,
            'trades_count': 40,
            'winning_trades': 28,
            'losing_trades': 12,
            'win_rate': 0.7,
            'total_profit': 50000,
            'total_loss': 20000,
            'profit_factor': 2.5,
            'avg_holding_hours': 18.0,
            'weekly_pnl_list': weekly_pnl_list,
            'max_drawdown_pct': 8.0,
            'sharpe_ratio': 1.8,
            'volatility': 12.5,
            'best_trade': {
                'symbol': 'BTC/JPY',
                'side': 'long',
                'pnl': 15000,
                'pnl_pct': 12.5
            },
            'worst_trade': {
                'symbol': 'ETH/JPY',
                'side': 'short',
                'pnl': -5000,
                'pnl_pct': -4.2
            },
            # 通貨ペア別パフォーマンス
            'pair_performance': {
                'BTC/JPY': {
                    'win_rate': 0.72,
                    'profit_factor': 3.2,
                    'sharpe_ratio': 2.0,
                    'trades': 24
                },
                'ETH/JPY': {
                    'win_rate': 0.67,
                    'profit_factor': 1.8,
                    'sharpe_ratio': 1.5,
                    'trades': 16
                }
            }
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
