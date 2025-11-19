"""税務処理モジュール

取引履歴のCSVエクスポート、年間損益計算
"""

import logging
import csv
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path
from data.storage.sqlite_manager import SQLiteManager

logger = logging.getLogger(__name__)


class TaxReportGenerator:
    """税務レポート生成クラス"""

    def __init__(self, db_manager: SQLiteManager):
        """
        Args:
            db_manager: SQLiteManagerインスタンス
        """
        self.db_manager = db_manager
        logger.info("税務処理システム初期化")

    def export_trades_to_csv(
        self,
        output_path: str,
        year: Optional[int] = None
    ) -> str:
        """
        取引履歴をCSVエクスポート

        Args:
            output_path: 出力ファイルパス
            year: 対象年（Noneの場合は全期間）

        Returns:
            出力ファイルパス
        """
        # TODO: 実際のDB取得ロジック実装
        trades = self._get_trades_for_tax(year)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)

            # ヘッダー
            writer.writerow([
                '日時',
                '取引ペア',
                '売買区分',
                '数量',
                '価格',
                '金額',
                '手数料',
                '損益',
                '備考'
            ])

            # データ
            for trade in trades:
                writer.writerow([
                    trade['timestamp'],
                    trade['symbol'],
                    '買い' if trade['side'] == 'long' else '売り',
                    trade['amount'],
                    trade['price'],
                    trade['cost'],
                    trade['fee'],
                    trade['pnl'],
                    trade['note']
                ])

        logger.info(f"取引履歴CSV出力完了: {output_path} ({len(trades)}件)")
        return output_path

    def calculate_annual_pnl(self, year: int) -> Dict:
        """
        年間損益を計算

        Args:
            year: 対象年

        Returns:
            年間損益情報の辞書
        """
        # TODO: 実際のDB取得ロジック実装
        trades = self._get_trades_for_tax(year)

        # 損益集計
        total_profit = 0.0
        total_loss = 0.0
        total_fee = 0.0
        winning_trades = 0
        losing_trades = 0

        for trade in trades:
            pnl = trade.get('pnl', 0)
            fee = trade.get('fee', 0)

            if pnl > 0:
                total_profit += pnl
                winning_trades += 1
            elif pnl < 0:
                total_loss += abs(pnl)
                losing_trades += 1

            total_fee += fee

        net_pnl = total_profit - total_loss - total_fee

        result = {
            'year': year,
            'total_trades': len(trades),
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'total_profit': total_profit,
            'total_loss': total_loss,
            'total_fee': total_fee,
            'net_pnl': net_pnl,
            'tax_base': net_pnl if net_pnl > 0 else 0
        }

        logger.info(f"{year}年 年間損益計算完了: ¥{net_pnl:,.0f}")

        return result

    def generate_tax_report(self, year: int) -> str:
        """
        税務レポートを生成

        Args:
            year: 対象年

        Returns:
            レポートテキスト
        """
        annual_pnl = self.calculate_annual_pnl(year)

        # 所得税計算（雑所得として）
        tax_info = self._calculate_tax(annual_pnl['tax_base'])

        report = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【暗号資産 税務レポート】{year}年
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【取引サマリー】
総取引回数: {annual_pnl['total_trades']}回
勝ち: {annual_pnl['winning_trades']}回
負け: {annual_pnl['losing_trades']}回

【損益計算】
総利益: ¥{annual_pnl['total_profit']:,.0f}
総損失: ¥{annual_pnl['total_loss']:,.0f}
手数料合計: ¥{annual_pnl['total_fee']:,.0f}
─────────────────────
純損益: ¥{annual_pnl['net_pnl']:,.0f}

【課税対象額】
課税所得: ¥{annual_pnl['tax_base']:,.0f}

【参考: 所得税額（概算）】
※雑所得として計算（他の所得との合算により変動します）
※確定申告時は税理士にご相談ください

所得税（概算）: ¥{tax_info['income_tax']:,.0f}
住民税（概算）: ¥{tax_info['resident_tax']:,.0f}
─────────────────────
合計税額（概算）: ¥{tax_info['total_tax']:,.0f}

税引後利益: ¥{annual_pnl['net_pnl'] - tax_info['total_tax']:,.0f}

【注意事項】
• 暗号資産の売買益は雑所得として総合課税されます
• 他の所得と合算して税率が決定されます
• 上記は概算であり、実際の税額は確定申告時に確定します
• 詳細は税理士または税務署にご相談ください

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        logger.info(f"{year}年 税務レポート生成完了")
        return report.strip()

    def _get_trades_for_tax(self, year: Optional[int] = None) -> List[Dict]:
        """税務用取引データを取得（モック）"""
        # TODO: 実際のDB取得ロジック実装
        trades = [
            {
                'timestamp': '2025-11-01 10:00:00',
                'symbol': 'BTC/JPY',
                'side': 'long',
                'amount': 0.01,
                'price': 12000000,
                'cost': 120000,
                'fee': 180,
                'pnl': 5000,
                'note': '通常取引'
            },
            {
                'timestamp': '2025-11-05 15:00:00',
                'symbol': 'ETH/JPY',
                'side': 'long',
                'amount': 0.2,
                'price': 500000,
                'cost': 100000,
                'fee': 150,
                'pnl': 3000,
                'note': '通常取引'
            }
        ]

        # 年でフィルタ
        if year:
            trades = [t for t in trades if t['timestamp'].startswith(str(year))]

        return trades

    def _calculate_tax(self, taxable_income: float) -> Dict:
        """
        税額を計算（概算）

        Args:
            taxable_income: 課税所得

        Returns:
            税額情報の辞書
        """
        # 所得税（累進課税の簡易計算）
        # ※実際は他の所得と合算して計算されるため、ここでは概算
        if taxable_income <= 0:
            income_tax_rate = 0.0
        elif taxable_income <= 1950000:
            income_tax_rate = 0.05
        elif taxable_income <= 3300000:
            income_tax_rate = 0.10
        elif taxable_income <= 6950000:
            income_tax_rate = 0.20
        elif taxable_income <= 9000000:
            income_tax_rate = 0.23
        elif taxable_income <= 18000000:
            income_tax_rate = 0.33
        else:
            income_tax_rate = 0.45

        income_tax = taxable_income * income_tax_rate

        # 住民税（約10%）
        resident_tax = taxable_income * 0.10

        total_tax = income_tax + resident_tax

        return {
            'income_tax': income_tax,
            'income_tax_rate': income_tax_rate,
            'resident_tax': resident_tax,
            'total_tax': total_tax
        }


# ヘルパー関数
def create_tax_report_generator(db_manager: SQLiteManager) -> TaxReportGenerator:
    """
    税務レポート生成インスタンスを作成

    Args:
        db_manager: SQLiteManagerインスタンス

    Returns:
        TaxReportGeneratorインスタンス
    """
    return TaxReportGenerator(db_manager)
