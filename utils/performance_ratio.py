"""パフォーマンス比較モジュール

複数のコイン間での相対的なパフォーマンスを分析
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class PerformanceRatioAnalyzer:
    """コイン間のパフォーマンス比較クラス"""

    def __init__(self, data_collector=None):
        """
        Args:
            data_collector: データ収集インスタンス（bitFlyerAPI等）
        """
        self.data_collector = data_collector

        # bitFlyerでサポートされている主要コイン
        self.supported_coins = [
            'BTC/JPY',
            'ETH/JPY',
            'XRP/JPY',
            'BCH/JPY',  # ビットコインキャッシュ
            'LTC/JPY',  # ライトコイン
            'MONA/JPY'  # モナコイン
        ]

        logger.info("パフォーマンス比較アナライザー初期化")

    def calculate_performance_ratios(
        self,
        trading_pairs: List[str],
        benchmark_pairs: Optional[List[str]] = None,
        period_days: int = 7
    ) -> Dict:
        """
        複数コイン間のパフォーマンス比較を計算

        Args:
            trading_pairs: 取引中のペア（例: ['BTC/JPY', 'ETH/JPY']）
            benchmark_pairs: 比較対象のペア（指定なしで全サポートコイン）
            period_days: 比較期間（日数）

        Returns:
            パフォーマンス比較データ
        """
        if benchmark_pairs is None:
            benchmark_pairs = self.supported_coins

        try:
            # 各コインの価格データ取得
            price_data = {}
            for symbol in set(trading_pairs + benchmark_pairs):
                try:
                    data = self._fetch_price_history(symbol, period_days)
                    if data is not None and len(data) > 0:
                        price_data[symbol] = data
                except Exception as e:
                    logger.warning(f"{symbol} データ取得失敗: {e}")

            if not price_data:
                logger.error("価格データ取得失敗")
                return {}

            # パフォーマンス指標計算
            results = {
                'period_days': period_days,
                'timestamp': datetime.now().isoformat(),
                'coins': {},
                'relative_strength': {},
                'recommendations': []
            }

            # 各コインの基本指標
            for symbol, data in price_data.items():
                metrics = self._calculate_metrics(data, symbol)
                results['coins'][symbol] = metrics

            # 相対強度（Relative Strength）計算
            results['relative_strength'] = self._calculate_relative_strength(
                results['coins'], trading_pairs
            )

            # 推奨事項生成
            results['recommendations'] = self._generate_recommendations(
                results['coins'],
                results['relative_strength'],
                trading_pairs
            )

            return results

        except Exception as e:
            logger.error(f"パフォーマンス比較エラー: {e}")
            return {}

    def _fetch_price_history(
        self,
        symbol: str,
        days: int
    ) -> Optional[pd.DataFrame]:
        """
        過去の価格データを取得

        Args:
            symbol: 取引ペア
            days: 取得日数

        Returns:
            OHLCV DataFrame
        """
        if not self.data_collector:
            logger.warning("データコレクター未設定")
            return None

        try:
            # 1時間足で過去データ取得
            limit = days * 24  # 時間数
            ohlcv = self.data_collector.fetch_ohlcv(symbol, '1h', limit)

            if ohlcv is None or len(ohlcv) == 0:
                return None

            df = pd.DataFrame(
                ohlcv,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

            return df

        except Exception as e:
            logger.error(f"{symbol} 価格履歴取得エラー: {e}")
            return None

    def _calculate_metrics(self, data: pd.DataFrame, symbol: str) -> Dict:
        """
        コイン個別のパフォーマンス指標を計算

        Args:
            data: 価格DataFrame
            symbol: コインシンボル

        Returns:
            指標辞書
        """
        try:
            # 価格変化率
            first_price = data['close'].iloc[0]
            last_price = data['close'].iloc[-1]
            price_change_pct = ((last_price - first_price) / first_price) * 100

            # ボラティリティ（標準偏差）
            returns = data['close'].pct_change().dropna()
            volatility = returns.std() * 100

            # シャープレシオ（簡易版）
            avg_return = returns.mean()
            sharpe = (avg_return / returns.std() * np.sqrt(24)) if returns.std() != 0 else 0

            # 最大ドローダウン
            cumulative = (1 + returns).cumprod()
            running_max = cumulative.cummax()
            drawdown = (cumulative - running_max) / running_max
            max_drawdown = drawdown.min() * 100

            # トレンド強度（価格の傾き）
            x = np.arange(len(data))
            y = data['close'].values
            slope = np.polyfit(x, y, 1)[0]
            trend_strength = (slope / first_price) * 100 * len(data)

            return {
                'symbol': symbol,
                'current_price': float(last_price),
                'price_change_pct': float(price_change_pct),
                'volatility': float(volatility),
                'sharpe_ratio': float(sharpe),
                'max_drawdown_pct': float(max_drawdown),
                'trend_strength': float(trend_strength),
                'is_uptrend': slope > 0,
                'data_points': len(data)
            }

        except Exception as e:
            logger.error(f"{symbol} 指標計算エラー: {e}")
            return {
                'symbol': symbol,
                'error': str(e)
            }

    def _calculate_relative_strength(
        self,
        all_metrics: Dict,
        trading_pairs: List[str]
    ) -> Dict:
        """
        相対強度を計算

        Args:
            all_metrics: 全コインの指標
            trading_pairs: 取引中のペア

        Returns:
            相対強度データ
        """
        results = {}

        # 取引中のコインをベンチマークとして使用
        for trading_pair in trading_pairs:
            if trading_pair not in all_metrics:
                continue

            trading_metrics = all_metrics[trading_pair]
            results[trading_pair] = {'vs': {}}

            # 他のコインとの比較
            for symbol, metrics in all_metrics.items():
                if symbol == trading_pair or 'error' in metrics:
                    continue

                # 相対的なパフォーマンス
                relative_return = (
                    metrics['price_change_pct'] -
                    trading_metrics['price_change_pct']
                )

                # 相対的なシャープレシオ
                relative_sharpe = (
                    metrics['sharpe_ratio'] -
                    trading_metrics['sharpe_ratio']
                )

                # 相対的なボラティリティ
                relative_volatility = (
                    metrics['volatility'] -
                    trading_metrics['volatility']
                )

                # 総合スコア（リターン重視、ボラティリティペナルティ）
                score = (
                    relative_return * 0.5 +
                    relative_sharpe * 30 +  # Sharpe比率を重視
                    (-relative_volatility * 0.2)  # 低ボラティリティが良い
                )

                results[trading_pair]['vs'][symbol] = {
                    'relative_return': float(relative_return),
                    'relative_sharpe': float(relative_sharpe),
                    'relative_volatility': float(relative_volatility),
                    'score': float(score),
                    'is_stronger': score > 0
                }

        return results

    def _generate_recommendations(
        self,
        all_metrics: Dict,
        relative_strength: Dict,
        trading_pairs: List[str]
    ) -> List[Dict]:
        """
        推奨事項を生成

        Args:
            all_metrics: 全コインの指標
            relative_strength: 相対強度
            trading_pairs: 取引中のペア

        Returns:
            推奨事項リスト
        """
        recommendations = []

        # 取引していないコインで強いものを検出
        for trading_pair in trading_pairs:
            if trading_pair not in relative_strength:
                continue

            stronger_coins = []
            for symbol, data in relative_strength[trading_pair]['vs'].items():
                if data['is_stronger'] and data['score'] > 5.0:  # 閾値: スコア5以上
                    stronger_coins.append({
                        'symbol': symbol,
                        'score': data['score'],
                        'metrics': all_metrics.get(symbol, {})
                    })

            # スコア順にソート
            stronger_coins.sort(key=lambda x: x['score'], reverse=True)

            # 上位のみ推奨
            for coin in stronger_coins[:3]:  # 最大3つ
                recommendations.append({
                    'type': 'consider_adding',
                    'current': trading_pair,
                    'suggested': coin['symbol'],
                    'score': coin['score'],
                    'reason': (
                        f"{coin['symbol']}が{trading_pair}より強いパフォーマンス "
                        f"(リターン差: {coin['metrics'].get('price_change_pct', 0) - all_metrics[trading_pair]['price_change_pct']:+.2f}%, "
                        f"Sharpe: {coin['metrics'].get('sharpe_ratio', 0):.2f})"
                    ),
                    'priority': 'high' if coin['score'] > 10 else 'medium'
                })

        # 取引中のコインで弱いものを検出
        if len(trading_pairs) >= 2:
            performances = []
            for symbol in trading_pairs:
                if symbol in all_metrics and 'error' not in all_metrics[symbol]:
                    performances.append({
                        'symbol': symbol,
                        'price_change': all_metrics[symbol]['price_change_pct'],
                        'sharpe': all_metrics[symbol]['sharpe_ratio']
                    })

            performances.sort(key=lambda x: x['price_change'], reverse=True)

            # 最弱のコイン
            if len(performances) >= 2:
                weakest = performances[-1]
                strongest = performances[0]

                if weakest['price_change'] < strongest['price_change'] - 10:  # 10%以上差
                    recommendations.append({
                        'type': 'consider_reducing',
                        'current': weakest['symbol'],
                        'reason': (
                            f"{weakest['symbol']}のパフォーマンスが低調 "
                            f"({weakest['price_change']:+.2f}% vs {strongest['symbol']} {strongest['price_change']:+.2f}%)"
                        ),
                        'priority': 'medium'
                    })

        return recommendations

    def format_report(self, analysis_results: Dict) -> str:
        """
        分析結果をレポート形式でフォーマット

        Args:
            analysis_results: analyze_performance_ratios()の結果

        Returns:
            フォーマットされたレポート
        """
        if not analysis_results:
            return "パフォーマンス比較データなし"

        report = f"\n📊 コインパフォーマンス比較 ({analysis_results['period_days']}日間)\n"
        report += "=" * 60 + "\n\n"

        # 各コインのパフォーマンス
        report += "【個別パフォーマンス】\n"

        # リターン順にソート
        coins = list(analysis_results['coins'].items())
        coins.sort(key=lambda x: x[1].get('price_change_pct', 0), reverse=True)

        for symbol, metrics in coins:
            if 'error' in metrics:
                report += f"  ⚠️ {symbol}: データ取得エラー\n"
                continue

            trend_emoji = "📈" if metrics['is_uptrend'] else "📉"
            report += f"\n  {trend_emoji} {symbol}\n"
            report += f"    価格変動: {metrics['price_change_pct']:+.2f}%\n"
            report += f"    Sharpe Ratio: {metrics['sharpe_ratio']:.2f}\n"
            report += f"    ボラティリティ: {metrics['volatility']:.2f}%\n"
            report += f"    最大DD: {metrics['max_drawdown_pct']:.2f}%\n"

        # 推奨事項
        if analysis_results.get('recommendations'):
            report += "\n【推奨事項】\n"

            for rec in analysis_results['recommendations']:
                priority_icon = "🔴" if rec['priority'] == 'high' else "🟡"

                if rec['type'] == 'consider_adding':
                    report += f"\n  {priority_icon} 追加検討: {rec['suggested']}\n"
                    report += f"    現在: {rec['current']}\n"
                    report += f"    理由: {rec['reason']}\n"
                    report += f"    スコア: {rec['score']:.2f}\n"

                elif rec['type'] == 'consider_reducing':
                    report += f"\n  {priority_icon} 配分縮小検討: {rec['current']}\n"
                    report += f"    理由: {rec['reason']}\n"

        report += "\n" + "=" * 60 + "\n"

        return report


def create_performance_analyzer(data_collector=None) -> PerformanceRatioAnalyzer:
    """
    パフォーマンスアナライザーを生成

    Args:
        data_collector: データ収集インスタンス

    Returns:
        PerformanceRatioAnalyzer
    """
    return PerformanceRatioAnalyzer(data_collector)
