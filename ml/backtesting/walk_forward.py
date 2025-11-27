"""ウォークフォワード検証エンジン

ローリングウィンドウ方式で時系列検証を実行
過学習を防ぎ、より現実的なパフォーマンス評価を実現
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, List, Optional, Tuple, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass

from ml.backtesting.backtest_engine import BacktestEngine

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardConfig:
    """ウォークフォワード設定"""
    train_period_days: int = 180      # 学習期間（日）
    test_period_days: int = 30        # 検証期間（日）
    step_days: int = 7                # ローリングステップ（日）
    min_train_samples: int = 500      # 最小学習サンプル数
    initial_capital: float = 200000   # 初期資金
    commission_rate: float = 0.0015   # 手数料率
    position_size: float = 0.95       # ポジションサイズ


class WalkForwardEngine:
    """ローリングウィンドウ方式のウォークフォワード検証エンジン"""

    def __init__(self, config: Optional[WalkForwardConfig] = None):
        """
        初期化

        Args:
            config: ウォークフォワード設定
        """
        self.config = config or WalkForwardConfig()
        self.results: List[Dict] = []
        self.summary: Dict = {}

        logger.info("ウォークフォワードエンジン初期化")
        logger.info(f"  - 学習期間: {self.config.train_period_days}日")
        logger.info(f"  - 検証期間: {self.config.test_period_days}日")
        logger.info(f"  - ステップ: {self.config.step_days}日")

    def run(
        self,
        df: pd.DataFrame,
        model_trainer: Callable[[pd.DataFrame], object],
        signal_generator: Callable[[object, pd.DataFrame], np.ndarray],
        timestamp_col: str = 'timestamp'
    ) -> Dict:
        """
        ウォークフォワード検証を実行

        Args:
            df: 全データ（timestamp, OHLCV, 特徴量を含む）
            model_trainer: モデル学習関数 (train_df) -> trained_model
            signal_generator: シグナル生成関数 (model, test_df) -> signals
            timestamp_col: タイムスタンプカラム名

        Returns:
            検証結果の辞書
        """
        logger.info("=" * 60)
        logger.info("ウォークフォワード検証開始")
        logger.info("=" * 60)

        self.results = []

        # タイムスタンプをインデックスに
        if timestamp_col in df.columns:
            df = df.copy()
            df[timestamp_col] = pd.to_datetime(df[timestamp_col])
            df = df.set_index(timestamp_col).sort_index()

        # 期間計算
        total_days = (df.index[-1] - df.index[0]).days
        min_required_days = self.config.train_period_days + self.config.test_period_days

        if total_days < min_required_days:
            logger.error(f"データ不足: {total_days}日 < 必要{min_required_days}日")
            return {'error': 'データ不足'}

        # ローリングウィンドウで検証
        current_start = df.index[0]
        fold_num = 0

        while True:
            train_start = current_start
            train_end = train_start + timedelta(days=self.config.train_period_days)
            test_start = train_end
            test_end = test_start + timedelta(days=self.config.test_period_days)

            # データ範囲外なら終了
            if test_end > df.index[-1]:
                break

            fold_num += 1
            logger.info(f"\n[Fold {fold_num}]")
            logger.info(f"  学習: {train_start.date()} → {train_end.date()}")
            logger.info(f"  検証: {test_start.date()} → {test_end.date()}")

            # データ分割
            train_df = df[train_start:train_end].copy()
            test_df = df[test_start:test_end].copy()

            # サンプル数チェック
            if len(train_df) < self.config.min_train_samples:
                logger.warning(f"  スキップ: 学習サンプル不足 ({len(train_df)} < {self.config.min_train_samples})")
                current_start += timedelta(days=self.config.step_days)
                continue

            if len(test_df) < 10:
                logger.warning(f"  スキップ: 検証サンプル不足 ({len(test_df)})")
                current_start += timedelta(days=self.config.step_days)
                continue

            try:
                # モデル学習
                logger.info(f"  モデル学習中... ({len(train_df)}サンプル)")
                model = model_trainer(train_df.reset_index())

                # シグナル生成
                logger.info(f"  シグナル生成中... ({len(test_df)}サンプル)")
                signals = signal_generator(model, test_df.reset_index())

                # バックテスト実行
                backtest = BacktestEngine(
                    initial_capital=self.config.initial_capital,
                    position_size=self.config.position_size,
                    commission_rate=self.config.commission_rate,
                    allow_short=False
                )

                prices = test_df['close'].values
                bt_results = backtest.run_backtest(test_df.reset_index(), signals, prices)

                # 結果記録
                fold_result = {
                    'fold': fold_num,
                    'train_start': train_start,
                    'train_end': train_end,
                    'test_start': test_start,
                    'test_end': test_end,
                    'train_samples': len(train_df),
                    'test_samples': len(test_df),
                    'total_trades': bt_results['total_trades'],
                    'win_rate': bt_results['win_rate'],
                    'total_return_pct': bt_results['total_return_pct'],
                    'max_drawdown_pct': bt_results['max_drawdown_pct'],
                    'profit_factor': bt_results['profit_factor'],
                    'sharpe_ratio': bt_results['sharpe_ratio']
                }
                self.results.append(fold_result)

                logger.info(f"  結果: 取引{bt_results['total_trades']}回, "
                           f"勝率{bt_results['win_rate']:.1%}, "
                           f"リターン{bt_results['total_return_pct']:+.2f}%")

            except Exception as e:
                logger.error(f"  エラー: {e}")
                fold_result = {
                    'fold': fold_num,
                    'train_start': train_start,
                    'test_start': test_start,
                    'error': str(e)
                }
                self.results.append(fold_result)

            # 次のウィンドウへ
            current_start += timedelta(days=self.config.step_days)

        # サマリー計算
        self.summary = self._calculate_summary()

        logger.info("\n" + "=" * 60)
        logger.info("ウォークフォワード検証完了")
        logger.info("=" * 60)

        return {
            'folds': self.results,
            'summary': self.summary
        }

    def _calculate_summary(self) -> Dict:
        """サマリー統計を計算"""
        valid_results = [r for r in self.results if 'error' not in r]

        if not valid_results:
            return {'error': '有効な結果なし'}

        # 各指標の統計
        returns = [r['total_return_pct'] for r in valid_results]
        win_rates = [r['win_rate'] for r in valid_results]
        drawdowns = [r['max_drawdown_pct'] for r in valid_results]
        profit_factors = [r['profit_factor'] for r in valid_results if r['profit_factor'] > 0]
        sharpe_ratios = [r['sharpe_ratio'] for r in valid_results]
        total_trades = sum(r['total_trades'] for r in valid_results)

        # 累積リターン計算
        cumulative_return = 1.0
        for r in returns:
            cumulative_return *= (1 + r / 100)
        cumulative_return_pct = (cumulative_return - 1) * 100

        summary = {
            'total_folds': len(self.results),
            'valid_folds': len(valid_results),
            'total_trades': total_trades,

            # リターン
            'avg_return_pct': np.mean(returns),
            'std_return_pct': np.std(returns),
            'min_return_pct': np.min(returns),
            'max_return_pct': np.max(returns),
            'cumulative_return_pct': cumulative_return_pct,

            # 勝率
            'avg_win_rate': np.mean(win_rates),
            'min_win_rate': np.min(win_rates),
            'max_win_rate': np.max(win_rates),

            # ドローダウン
            'avg_max_drawdown_pct': np.mean(drawdowns),
            'worst_drawdown_pct': np.max(drawdowns),

            # その他
            'avg_profit_factor': np.mean(profit_factors) if profit_factors else 0,
            'avg_sharpe_ratio': np.mean(sharpe_ratios),

            # 安定性指標
            'positive_folds': sum(1 for r in returns if r > 0),
            'negative_folds': sum(1 for r in returns if r <= 0),
            'consistency_ratio': sum(1 for r in returns if r > 0) / len(returns) if returns else 0
        }

        return summary

    def print_summary(self):
        """サマリーを表示"""
        if not self.summary:
            print("結果がありません。run()を先に実行してください。")
            return

        print("\n" + "=" * 70)
        print("ウォークフォワード検証 サマリー")
        print("=" * 70)

        s = self.summary

        print(f"\n【検証概要】")
        print(f"  総Fold数:          {s['total_folds']}")
        print(f"  有効Fold数:        {s['valid_folds']}")
        print(f"  総取引回数:        {s['total_trades']}")

        print(f"\n【リターン】")
        print(f"  平均リターン:      {s['avg_return_pct']:+.2f}%")
        print(f"  標準偏差:          {s['std_return_pct']:.2f}%")
        print(f"  最小リターン:      {s['min_return_pct']:+.2f}%")
        print(f"  最大リターン:      {s['max_return_pct']:+.2f}%")
        print(f"  累積リターン:      {s['cumulative_return_pct']:+.2f}%")

        print(f"\n【勝率】")
        print(f"  平均勝率:          {s['avg_win_rate']:.1%}")
        print(f"  最低勝率:          {s['min_win_rate']:.1%}")
        print(f"  最高勝率:          {s['max_win_rate']:.1%}")

        print(f"\n【リスク】")
        print(f"  平均最大DD:        {s['avg_max_drawdown_pct']:.2f}%")
        print(f"  最悪DD:            {s['worst_drawdown_pct']:.2f}%")

        print(f"\n【安定性】")
        print(f"  プラスFold:        {s['positive_folds']}/{s['valid_folds']}")
        print(f"  マイナスFold:      {s['negative_folds']}/{s['valid_folds']}")
        print(f"  一貫性比率:        {s['consistency_ratio']:.1%}")
        print(f"  平均PF:            {s['avg_profit_factor']:.2f}")
        print(f"  平均シャープ:      {s['avg_sharpe_ratio']:.2f}")

        print("=" * 70)

        # 判定
        print("\n【総合判定】")
        if s['cumulative_return_pct'] > 0 and s['consistency_ratio'] >= 0.6:
            print("  ✅ 戦略は安定してプラスリターンを生成")
        elif s['cumulative_return_pct'] > 0:
            print("  ⚠️ プラスリターンだが安定性に課題あり")
        else:
            print("  ❌ 戦略の見直しが必要")

        print()

    def get_fold_details(self) -> pd.DataFrame:
        """Fold別詳細をDataFrameで取得"""
        return pd.DataFrame(self.results)


def create_walk_forward_engine(
    train_days: int = 180,
    test_days: int = 30,
    step_days: int = 7,
    initial_capital: float = 200000
) -> WalkForwardEngine:
    """
    ウォークフォワードエンジンを作成

    Args:
        train_days: 学習期間（日）
        test_days: 検証期間（日）
        step_days: ローリングステップ（日）
        initial_capital: 初期資金

    Returns:
        WalkForwardEngineインスタンス
    """
    config = WalkForwardConfig(
        train_period_days=train_days,
        test_period_days=test_days,
        step_days=step_days,
        initial_capital=initial_capital
    )
    return WalkForwardEngine(config)
