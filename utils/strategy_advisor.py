"""戦略アドバイザー

週次・月次のパフォーマンスを分析し、戦略パラメータの調整を提案
"""

import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)


class StrategyAdvisor:
    """戦略調整アドバイザークラス"""

    def __init__(self, config_path: str = "config/config.yaml"):
        """
        Args:
            config_path: 設定ファイルパス
        """
        self.config_path = Path(config_path)
        logger.info("戦略アドバイザー初期化")

    def analyze_and_suggest(
        self,
        period_data: Dict,
        period_type: str = "weekly"
    ) -> Dict:
        """
        パフォーマンスを分析し、戦略調整を提案

        Args:
            period_data: 期間データ（週次または月次）
            period_type: 期間タイプ（weekly/monthly）

        Returns:
            提案内容の辞書
        """
        suggestions = {
            'risk_management': [],  # リスク管理パラメータ
            'allocation': [],       # 資産配分
            'trading': [],          # 取引パラメータ
            'summary': '',          # サマリー
            'recommended_config': {}  # 推奨設定
        }

        # 勝率分析
        win_rate = period_data.get('win_rate', 0.5)
        profit_factor = period_data.get('profit_factor', 1.0)
        max_drawdown = period_data.get('max_drawdown_pct', 0)
        sharpe_ratio = period_data.get('sharpe_ratio', 0)

        # 現在の設定を読み込み
        current_config = self._load_current_config()

        # 1. リスク管理パラメータの提案
        risk_suggestions = self._suggest_risk_params(
            win_rate, profit_factor, max_drawdown, sharpe_ratio,
            current_config.get('risk_management', {})
        )
        suggestions['risk_management'] = risk_suggestions

        # 2. 資産配分の提案（通貨ペア別のパフォーマンスがある場合）
        if 'pair_performance' in period_data:
            allocation_suggestions = self._suggest_allocation(
                period_data['pair_performance'],
                current_config.get('trading_pairs', [])
            )
            suggestions['allocation'] = allocation_suggestions

        # 3. 取引パラメータの提案
        trading_suggestions = self._suggest_trading_params(
            win_rate, profit_factor,
            current_config.get('trading', {})
        )
        suggestions['trading'] = trading_suggestions

        # 4. 推奨設定を生成
        suggestions['recommended_config'] = self._generate_recommended_config(
            current_config, suggestions
        )

        # 5. サマリー生成
        suggestions['summary'] = self._generate_summary(
            suggestions, period_type, win_rate, profit_factor
        )

        return suggestions

    def _load_current_config(self) -> Dict:
        """現在の設定を読み込み"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"設定ファイル読み込みエラー: {e}")
            return {}

    def _suggest_risk_params(
        self,
        win_rate: float,
        profit_factor: float,
        max_drawdown: float,
        sharpe_ratio: float,
        current_risk: Dict
    ) -> List[Dict]:
        """リスク管理パラメータの調整を提案"""
        suggestions = []

        current_stop_loss = current_risk.get('stop_loss_pct', 10.0)
        current_tp_first = current_risk.get('take_profit_first', 15.0)
        current_tp_second = current_risk.get('take_profit_second', 25.0)

        # ストップロスの調整
        if max_drawdown > 15.0:  # ドローダウンが大きい
            new_stop_loss = max(5.0, current_stop_loss - 2.0)
            if new_stop_loss != current_stop_loss:
                suggestions.append({
                    'param': 'stop_loss_pct',
                    'current': current_stop_loss,
                    'recommended': new_stop_loss,
                    'reason': f'ドローダウンが大きいため、損切りを早めに設定（{max_drawdown:.1f}% → 目標15%以下）',
                    'priority': 'high'
                })
        elif max_drawdown < 5.0 and win_rate < 0.5:  # ドローダウンは小さいが勝率が低い
            new_stop_loss = min(15.0, current_stop_loss + 2.0)
            if new_stop_loss != current_stop_loss:
                suggestions.append({
                    'param': 'stop_loss_pct',
                    'current': current_stop_loss,
                    'recommended': new_stop_loss,
                    'reason': f'勝率が低いため、ストップロスを緩めて損切り回数を減らす（勝率: {win_rate:.1%}）',
                    'priority': 'medium'
                })

        # 利確ラインの調整
        if profit_factor < 1.5:  # 利益率が低い
            # 第1段階を早めに取る
            new_tp_first = max(10.0, current_tp_first - 3.0)
            if new_tp_first != current_tp_first:
                suggestions.append({
                    'param': 'take_profit_first',
                    'current': current_tp_first,
                    'recommended': new_tp_first,
                    'reason': f'プロフィットファクターが低いため、早めに利確（PF: {profit_factor:.2f}）',
                    'priority': 'high'
                })
        elif profit_factor > 2.5:  # 利益率が高い
            # 利確ラインを遠くして利益を伸ばす
            new_tp_first = min(20.0, current_tp_first + 3.0)
            new_tp_second = min(35.0, current_tp_second + 5.0)
            if new_tp_first != current_tp_first:
                suggestions.append({
                    'param': 'take_profit_first',
                    'current': current_tp_first,
                    'recommended': new_tp_first,
                    'reason': f'パフォーマンス良好のため、利益を伸ばす（PF: {profit_factor:.2f}）',
                    'priority': 'medium'
                })
            if new_tp_second != current_tp_second:
                suggestions.append({
                    'param': 'take_profit_second',
                    'current': current_tp_second,
                    'recommended': new_tp_second,
                    'reason': f'パフォーマンス良好のため、利益を伸ばす（PF: {profit_factor:.2f}）',
                    'priority': 'medium'
                })

        # 期間損失制限の調整
        if max_drawdown > 10.0:
            current_daily_loss = current_risk.get('max_daily_loss_pct', 5.0)
            new_daily_loss = max(3.0, current_daily_loss - 1.0)
            if new_daily_loss != current_daily_loss:
                suggestions.append({
                    'param': 'max_daily_loss_pct',
                    'current': current_daily_loss,
                    'recommended': new_daily_loss,
                    'reason': 'ドローダウン抑制のため、日次損失制限を厳格化',
                    'priority': 'high'
                })

        return suggestions

    def _suggest_allocation(
        self,
        pair_performance: Dict[str, Dict],
        current_pairs: List[Dict]
    ) -> List[Dict]:
        """資産配分の調整を提案"""
        suggestions = []

        # 各通貨ペアのパフォーマンスを比較
        performances = []
        for symbol, perf in pair_performance.items():
            win_rate = perf.get('win_rate', 0)
            profit_factor = perf.get('profit_factor', 0)
            sharpe = perf.get('sharpe_ratio', 0)

            # 総合スコア計算
            score = (win_rate * 0.3) + (min(profit_factor / 3, 1.0) * 0.4) + (min(sharpe / 2, 1.0) * 0.3)

            current_allocation = next(
                (p['allocation'] for p in current_pairs if p['symbol'] == symbol),
                0.5
            )

            performances.append({
                'symbol': symbol,
                'score': score,
                'win_rate': win_rate,
                'profit_factor': profit_factor,
                'current_allocation': current_allocation
            })

        if len(performances) >= 2:
            # スコアで並び替え
            performances.sort(key=lambda x: x['score'], reverse=True)

            best = performances[0]
            worst = performances[-1]

            # スコア差が大きい場合、配分を調整
            score_diff = best['score'] - worst['score']

            if score_diff > 0.2:  # 20%以上の差
                # 良いコインを増やし、悪いコインを減らす
                adjustment = min(0.1, score_diff * 0.2)  # 最大10%調整

                new_best_allocation = min(0.8, best['current_allocation'] + adjustment)
                new_worst_allocation = max(0.2, worst['current_allocation'] - adjustment)

                # 合計が1.0になるよう正規化
                total = new_best_allocation + new_worst_allocation
                new_best_allocation /= total
                new_worst_allocation /= total

                if abs(new_best_allocation - best['current_allocation']) > 0.01:
                    suggestions.append({
                        'param': f"{best['symbol']}_allocation",
                        'current': best['current_allocation'],
                        'recommended': new_best_allocation,
                        'reason': f"{best['symbol']}のパフォーマンスが優秀（勝率: {best['win_rate']:.1%}, PF: {best['profit_factor']:.2f}）",
                        'priority': 'medium'
                    })

                if abs(new_worst_allocation - worst['current_allocation']) > 0.01:
                    suggestions.append({
                        'param': f"{worst['symbol']}_allocation",
                        'current': worst['current_allocation'],
                        'recommended': new_worst_allocation,
                        'reason': f"{worst['symbol']}のパフォーマンスが低調（勝率: {worst['win_rate']:.1%}, PF: {worst['profit_factor']:.2f}）",
                        'priority': 'medium'
                    })

        return suggestions

    def _suggest_trading_params(
        self,
        win_rate: float,
        profit_factor: float,
        current_trading: Dict
    ) -> List[Dict]:
        """取引パラメータの調整を提案"""
        suggestions = []

        current_min_confidence = current_trading.get('min_confidence', 0.6)

        # エントリー条件の調整
        if win_rate < 0.45:  # 勝率が低い
            new_confidence = min(0.75, current_min_confidence + 0.05)
            if new_confidence != current_min_confidence:
                suggestions.append({
                    'param': 'min_confidence',
                    'current': current_min_confidence,
                    'recommended': new_confidence,
                    'reason': f'勝率が低いため、エントリー条件を厳格化（勝率: {win_rate:.1%}）',
                    'priority': 'high'
                })
        elif win_rate > 0.65 and profit_factor > 2.0:  # パフォーマンス良好
            new_confidence = max(0.5, current_min_confidence - 0.05)
            if new_confidence != current_min_confidence:
                suggestions.append({
                    'param': 'min_confidence',
                    'current': current_min_confidence,
                    'recommended': new_confidence,
                    'reason': f'パフォーマンス良好のため、取引機会を増やす（勝率: {win_rate:.1%}, PF: {profit_factor:.2f}）',
                    'priority': 'low'
                })

        return suggestions

    def _generate_recommended_config(
        self,
        current_config: Dict,
        suggestions: Dict
    ) -> Dict:
        """推奨設定を生成"""
        recommended = {}

        # リスク管理
        if suggestions['risk_management']:
            recommended['risk_management'] = current_config.get('risk_management', {}).copy()
            for sugg in suggestions['risk_management']:
                param = sugg['param']
                recommended['risk_management'][param] = sugg['recommended']

        # 取引パラメータ
        if suggestions['trading']:
            recommended['trading'] = current_config.get('trading', {}).copy()
            for sugg in suggestions['trading']:
                param = sugg['param']
                recommended['trading'][param] = sugg['recommended']

        # 資産配分
        if suggestions['allocation']:
            recommended['trading_pairs'] = current_config.get('trading_pairs', []).copy()
            for sugg in suggestions['allocation']:
                symbol = sugg['param'].replace('_allocation', '')
                for pair in recommended['trading_pairs']:
                    if pair['symbol'] == symbol:
                        pair['allocation'] = sugg['recommended']

        return recommended

    def _generate_summary(
        self,
        suggestions: Dict,
        period_type: str,
        win_rate: float,
        profit_factor: float
    ) -> str:
        """提案サマリーを生成"""
        period_label = "週次" if period_type == "weekly" else "月次"

        total_suggestions = (
            len(suggestions['risk_management']) +
            len(suggestions['allocation']) +
            len(suggestions['trading'])
        )

        if total_suggestions == 0:
            return f"【{period_label}評価】現在の戦略は適切です。パラメータ変更の必要はありません。"

        summary = f"【{period_label}評価】パフォーマンス分析の結果、{total_suggestions}件の調整を推奨します。\n"

        # パフォーマンス評価
        if win_rate < 0.5:
            summary += f"⚠️ 勝率が低め（{win_rate:.1%}）\n"
        elif win_rate > 0.65:
            summary += f"✅ 勝率良好（{win_rate:.1%}）\n"

        if profit_factor < 1.5:
            summary += f"⚠️ プロフィットファクター改善が必要（{profit_factor:.2f}）\n"
        elif profit_factor > 2.0:
            summary += f"✅ プロフィットファクター良好（{profit_factor:.2f}）\n"

        # 高優先度の提案
        high_priority = [
            s for s in suggestions['risk_management'] + suggestions['trading']
            if s.get('priority') == 'high'
        ]

        if high_priority:
            summary += f"\n🔴 優先度高の調整（{len(high_priority)}件）:\n"
            for sugg in high_priority[:3]:  # 最大3件
                summary += f"  • {sugg['reason']}\n"

        return summary.strip()

    def apply_recommendations(self, recommended_config: Dict) -> bool:
        """
        推奨設定を適用（config.yamlを更新）

        Args:
            recommended_config: 推奨設定

        Returns:
            成功フラグ
        """
        try:
            # 現在の設定を読み込み
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # 推奨設定をマージ
            for section, values in recommended_config.items():
                if section in config:
                    config[section].update(values)

            # バックアップを作成
            backup_path = self.config_path.parent / f"config.yaml.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            with open(backup_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

            # 設定を保存
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)

            logger.info(f"設定ファイルを更新しました（バックアップ: {backup_path}）")
            return True

        except Exception as e:
            logger.error(f"設定ファイル更新エラー: {e}")
            return False

    def format_suggestions_for_report(self, suggestions: Dict) -> str:
        """レポート用に提案をフォーマット"""
        report = "\n【戦略調整の提案】\n"
        report += "=" * 50 + "\n\n"

        report += suggestions['summary'] + "\n\n"

        # リスク管理パラメータ
        if suggestions['risk_management']:
            report += "【リスク管理パラメータ】\n"
            for sugg in suggestions['risk_management']:
                priority_icon = {
                    'high': '🔴',
                    'medium': '🟡',
                    'low': '🟢'
                }.get(sugg.get('priority', 'medium'), '⚪')

                report += f"{priority_icon} {sugg['param']}\n"
                report += f"  現在値: {sugg['current']}\n"
                report += f"  推奨値: {sugg['recommended']}\n"
                report += f"  理由: {sugg['reason']}\n\n"

        # 資産配分
        if suggestions['allocation']:
            report += "【資産配分】\n"
            for sugg in suggestions['allocation']:
                report += f"• {sugg['param']}\n"
                report += f"  現在値: {sugg['current']:.1%}\n"
                report += f"  推奨値: {sugg['recommended']:.1%}\n"
                report += f"  理由: {sugg['reason']}\n\n"

        # 取引パラメータ
        if suggestions['trading']:
            report += "【取引パラメータ】\n"
            for sugg in suggestions['trading']:
                priority_icon = {
                    'high': '🔴',
                    'medium': '🟡',
                    'low': '🟢'
                }.get(sugg.get('priority', 'medium'), '⚪')

                report += f"{priority_icon} {sugg['param']}\n"
                report += f"  現在値: {sugg['current']}\n"
                report += f"  推奨値: {sugg['recommended']}\n"
                report += f"  理由: {sugg['reason']}\n\n"

        # 推奨設定（YAML形式）
        if suggestions['recommended_config']:
            report += "【推奨設定（YAML）】\n"
            report += "```yaml\n"
            report += yaml.dump(
                suggestions['recommended_config'],
                allow_unicode=True,
                default_flow_style=False
            )
            report += "```\n"

        report += "\n" + "=" * 50 + "\n"
        report += "※ 設定を変更する場合は、config/config.yamlを編集してください\n"

        return report
