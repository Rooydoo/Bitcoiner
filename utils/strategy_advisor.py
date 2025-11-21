"""戦略アドバイザー

週次・月次のパフォーマンスを分析し、戦略パラメータの調整を提案
"""

import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta
import yaml
from pathlib import Path
import json
import os

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


class LLMStrategyAdvisor(StrategyAdvisor):
    """Claude Sonnetを使用した高度な戦略分析クラス"""

    def __init__(self, config_path: str = "config/config.yaml"):
        """
        Args:
            config_path: 設定ファイルパス
        """
        super().__init__(config_path)

        # Anthropic APIキーを確認
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            logger.warning("ANTHROPIC_API_KEYが設定されていません。ルールベース分析にフォールバックします。")
            self.client = None
        else:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
                logger.info("Claude Sonnet戦略アドバイザー初期化完了")
            except ImportError:
                logger.error("anthropicパッケージがインストールされていません。pip install anthropic")
                self.client = None
            except Exception as e:
                logger.error(f"Anthropic API初期化エラー: {e}")
                self.client = None

        # モデル設定
        config = self._load_current_config()
        advisor_config = config.get('strategy_advisor', {})
        self.model = advisor_config.get('model', 'claude-sonnet-4-5-20250929')
        self.fallback_to_rule_based = advisor_config.get('fallback_to_rule_based', True)

    def analyze_and_suggest(
        self,
        period_data: Dict,
        period_type: str = "weekly"
    ) -> Dict:
        """
        Claude Sonnetでパフォーマンスを分析し、戦略調整を提案

        Args:
            period_data: 期間データ（週次または月次）
            period_type: 期間タイプ（weekly/monthly）

        Returns:
            提案内容の辞書
        """
        # LLMが使用不可の場合、ルールベースにフォールバック
        if not self.client:
            if self.fallback_to_rule_based:
                logger.info("LLM使用不可のため、ルールベース分析を実行")
                return super().analyze_and_suggest(period_data, period_type)
            else:
                logger.error("LLM使用不可、フォールバック無効")
                return self._empty_suggestions()

        try:
            # プロンプトを作成
            prompt = self._create_analysis_prompt(period_data, period_type)

            # Claude Sonnetで分析
            logger.info(f"Claude Sonnetで{period_type}分析を実行中...")
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4000,
                temperature=0.3,  # 一貫性のある分析のため低めに設定
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            # レスポンスをパース
            response_text = response.content[0].text
            logger.debug(f"Claude Sonnet レスポンス: {response_text[:500]}...")

            # JSON部分を抽出
            suggestions = self._parse_llm_response(response_text)

            # 推奨設定を生成
            current_config = self._load_current_config()
            suggestions['recommended_config'] = self._generate_recommended_config(
                current_config, suggestions
            )

            logger.info(f"LLM分析完了: {len(suggestions['risk_management']) + len(suggestions['allocation']) + len(suggestions['trading'])}件の提案")
            return suggestions

        except Exception as e:
            logger.error(f"LLM分析エラー: {e}")
            if self.fallback_to_rule_based:
                logger.info("ルールベース分析にフォールバック")
                return super().analyze_and_suggest(period_data, period_type)
            else:
                return self._empty_suggestions()

    def _create_analysis_prompt(self, period_data: Dict, period_type: str) -> str:
        """分析プロンプトを作成"""
        current_config = self._load_current_config()
        risk_config = current_config.get('risk_management', {})
        trading_config = current_config.get('trading', {})
        trading_pairs = current_config.get('trading_pairs', [])

        period_label = "週次" if period_type == "weekly" else "月次"

        # 通貨ペア別パフォーマンスをフォーマット
        pair_perf_text = ""
        if 'pair_performance' in period_data:
            for symbol, perf in period_data['pair_performance'].items():
                pair_perf_text += f"""
  {symbol}:
    - 勝率: {perf.get('win_rate', 0):.1%}
    - プロフィットファクター: {perf.get('profit_factor', 0):.2f}
    - シャープレシオ: {perf.get('sharpe_ratio', 0):.2f}
    - 総PnL: {perf.get('total_pnl', 0):,.0f}円
    - 取引回数: {perf.get('trade_count', 0)}回
"""

        prompt = f"""あなたは仮想通貨トレーディングシステムの戦略アナリストです。
以下のパフォーマンスデータを詳細に分析し、戦略パラメータの調整を提案してください。

## {period_label}パフォーマンスデータ

### 全体パフォーマンス
- 期間: {period_type}
- 総取引数: {period_data.get('total_trades', 0)}回
- 勝率: {period_data.get('win_rate', 0):.2%}
- プロフィットファクター: {period_data.get('profit_factor', 0):.2f}
- シャープレシオ: {period_data.get('sharpe_ratio', 0):.2f}
- 最大ドローダウン: {period_data.get('max_drawdown_pct', 0):.2%}
- 総PnL: {period_data.get('total_pnl', 0):,.0f}円
- 平均利益: {period_data.get('avg_profit', 0):,.0f}円
- 平均損失: {period_data.get('avg_loss', 0):,.0f}円

### 通貨ペア別パフォーマンス
{pair_perf_text}

## 現在の戦略設定

### リスク管理
- 損切（stop_loss_pct）: {risk_config.get('stop_loss_pct', 10.0)}%
- 利確1（take_profit_first）: {risk_config.get('take_profit_first', 15.0)}% で50%決済
- 利確2（take_profit_second）: {risk_config.get('take_profit_second', 25.0)}% で全決済
- ポジションサイズ（max_position_size）: {risk_config.get('max_position_size', 0.6):.0%}
- 日次損失上限（max_daily_loss_pct）: {risk_config.get('max_daily_loss_pct', 5.0)}%
- 週次損失上限（max_weekly_loss_pct）: {risk_config.get('max_weekly_loss_pct', 10.0)}%
- 月次損失上限（max_monthly_loss_pct）: {risk_config.get('max_monthly_loss_pct', 15.0)}%

### 取引設定
- 最小信頼度（min_confidence）: {trading_config.get('min_confidence', 0.6)}
- 取引間隔: {trading_config.get('trading_interval_minutes', 5)}分

### 資産配分
{self._format_allocations(trading_pairs)}

## 分析と提案の要件

以下の観点から分析し、具体的な調整を提案してください：

1. **リスク管理パラメータ**:
   - ドローダウンが大きい場合: 損切ラインを早める、ポジションサイズを縮小
   - プロフィットファクターが低い場合: 利確ラインを早める
   - 勝率が低い場合: リスクリワードバランスを見直す

2. **資産配分**:
   - 通貨ペア別のパフォーマンス差を考慮
   - 優秀なペアに配分を増やし、低調なペアは減らす
   - ただし、極端な偏りは避ける（最小20%, 最大80%）

3. **取引パラメータ**:
   - 勝率が低い場合: エントリー条件を厳格化（min_confidence上げる）
   - パフォーマンス良好な場合: 取引機会を増やす（min_confidence下げる）

4. **優先度付け**:
   - high: 緊急性の高い調整（パフォーマンス悪化を防ぐ）
   - medium: 最適化のための調整
   - low: 微調整

以下のJSON形式で提案を返してください：

```json
{{
  "risk_management": [
    {{
      "param": "stop_loss_pct",
      "current": 10.0,
      "recommended": 8.0,
      "reason": "ドローダウンが15%と大きいため、損切りを早めに設定して資金保護を強化",
      "priority": "high"
    }}
  ],
  "allocation": [
    {{
      "param": "BTC/JPY_allocation",
      "current": 0.6,
      "recommended": 0.7,
      "reason": "BTC/JPYのパフォーマンスが優秀（勝率65%, PF2.5）のため配分を増やす",
      "priority": "medium"
    }}
  ],
  "trading": [
    {{
      "param": "min_confidence",
      "current": 0.6,
      "recommended": 0.65,
      "reason": "勝率が45%と低いため、エントリー条件を厳格化",
      "priority": "high"
    }}
  ],
  "summary": "総合的な分析サマリー（2-3文で状況と重要な提案を説明）"
}}
```

**注意事項**:
- 数値は実際のデータに基づいて具体的に提案してください
- 理由は明確で説得力のあるものにしてください
- 提案が無い場合は空配列[]を返してください
- JSON形式を厳守してください（コメント不要）
"""

        return prompt

    def _format_allocations(self, trading_pairs: List[Dict]) -> str:
        """資産配分をフォーマット"""
        result = ""
        for pair in trading_pairs:
            result += f"- {pair['symbol']}: {pair['allocation']:.0%}\n"
        return result.strip()

    def _parse_llm_response(self, response_text: str) -> Dict:
        """LLMレスポンスからJSON部分を抽出してパース"""
        try:
            # JSON部分を抽出（```json ... ``` または { ... } ）
            start_markers = ['```json', '{']
            end_markers = ['```', '}']

            json_text = response_text

            # ```json ... ``` 形式を探す
            if '```json' in response_text:
                start_idx = response_text.find('```json') + 7
                end_idx = response_text.find('```', start_idx)
                if end_idx > start_idx:
                    json_text = response_text[start_idx:end_idx].strip()
            # { ... } 形式を探す
            elif '{' in response_text:
                start_idx = response_text.find('{')
                # 最後の } を探す
                end_idx = response_text.rfind('}') + 1
                if end_idx > start_idx:
                    json_text = response_text[start_idx:end_idx].strip()

            # JSONをパース
            suggestions = json.loads(json_text)

            # 必須キーがあるか確認
            required_keys = ['risk_management', 'allocation', 'trading', 'summary']
            for key in required_keys:
                if key not in suggestions:
                    suggestions[key] = [] if key != 'summary' else ''

            return suggestions

        except json.JSONDecodeError as e:
            logger.error(f"JSON パースエラー: {e}")
            logger.debug(f"パース対象テキスト: {json_text}")
            return self._empty_suggestions()
        except Exception as e:
            logger.error(f"レスポンスパースエラー: {e}")
            return self._empty_suggestions()

    def _empty_suggestions(self) -> Dict:
        """空の提案を返す"""
        return {
            'risk_management': [],
            'allocation': [],
            'trading': [],
            'summary': 'エラーが発生したため、提案を生成できませんでした。',
            'recommended_config': {}
        }


def create_strategy_advisor(config_path: str = "config/config.yaml") -> StrategyAdvisor:
    """
    設定に基づいて適切な戦略アドバイザーを生成

    Args:
        config_path: 設定ファイルパス

    Returns:
        StrategyAdvisor または LLMStrategyAdvisor
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        advisor_config = config.get('strategy_advisor', {})
        use_llm = advisor_config.get('use_llm', False)

        if use_llm:
            logger.info("LLM戦略アドバイザーを使用")
            return LLMStrategyAdvisor(config_path)
        else:
            logger.info("ルールベース戦略アドバイザーを使用")
            return StrategyAdvisor(config_path)

    except Exception as e:
        logger.warning(f"設定読み込みエラー、デフォルトでルールベースを使用: {e}")
        return StrategyAdvisor(config_path)
