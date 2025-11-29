"""メイン取引ボット - 全コンポーネント統合

Phase 1-4の全機能を統合したメイントレーディングシステム
"""

import sys
import time
import traceback
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional
import pandas as pd
import numpy as np

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

# Phase 1: Data Infrastructure
from data.collector.bitflyer_api import BitflyerDataCollector
from data.storage.sqlite_manager import SQLiteManager
from data.processor.indicators import TechnicalIndicators

# Phase 2: ML Models
from ml.training.feature_engineering import FeatureEngineer
from ml.models.hmm_model import MarketRegimeHMM
from ml.models.lightgbm_model import PriceDirectionLGBM
from ml.models.ensemble_model import EnsembleModel

# Phase 3: Trading Engine
from trading.order_executor import OrderExecutor
from trading.position_manager import PositionManager
from trading.risk_manager import RiskManager
from trading.strategy.pair_trading_strategy import PairTradingStrategy, PairTradingConfig, PairPosition

# Phase 4: Reporting & Notification
from notification.telegram_notifier import TelegramNotifier
from notification.telegram_bot_handler import TelegramBotHandler
from reporting.daily_report import ReportGenerator

# Utils
from utils.logger import setup_logger
from utils.config_loader import ConfigLoader
from utils.env_validator import validate_environment
from utils.config_validator import validate_config
from utils.health_check import HealthChecker, run_health_check
from utils.performance_tracker import PerformanceTracker
from utils.constants import (
    PRICE_SLIP_WARNING_THRESHOLD,
    PRICE_SLIP_ERROR_THRESHOLD,
    PARTIAL_FILL_THRESHOLD,
    API_FAILURE_THRESHOLD,
    POSITION_RECONCILE_CYCLES,
    WAL_CHECKPOINT_CYCLES,
    DB_CONNECTION_REFRESH_CYCLES,
    ORDER_STATUS_RETRY_DELAYS,
    ORDER_SUCCESS_STATUSES,
    ORDER_FINAL_STATUSES,
    MAX_ROLLBACK_RETRIES,
    MAX_CONSECUTIVE_API_ERRORS,
    SIDE_LONG,
    SIDE_SHORT,
    ORDER_BUY,
    ORDER_SELL,
    PAIR_LONG_SPREAD,
    PAIR_SHORT_SPREAD,
    ROLLBACK_RETRY_WAIT_BASE,
    ERROR_RECOVERY_WAIT
)

# ロガー設定
logger = setup_logger('main_trader', 'main_trader.log', console=True)


class CryptoTrader:
    """暗号資産自動売買システム メインクラス"""

    def __init__(
        self,
        config_path: str = "config/config.yaml",
        test_mode: bool = True
    ):
        """
        Args:
            config_path: 設定ファイルパス
            test_mode: テストモード（APIキーなしで動作）
        """
        self.test_mode = test_mode
        self.safe_mode = False  # API障害時の安全モード
        self.api_failure_count = 0  # API失敗回数カウンター
        self.api_failure_threshold = API_FAILURE_THRESHOLD  # 定数から読み込み
        logger.info("=" * 70)
        logger.info("CryptoTrader 起動中...")
        logger.info(f"モード: {'テスト' if test_mode else '本番'}")
        logger.info("=" * 70)

        # 起動前検証
        logger.info("\n[検証] 環境変数・設定ファイルをチェック中...")

        # 環境変数検証
        if not validate_environment(test_mode=test_mode, exit_on_error=True):
            raise RuntimeError("環境変数の検証に失敗しました")

        # 設定ファイル検証
        if not validate_config(config_path, exit_on_error=True):
            raise RuntimeError("設定ファイルの検証に失敗しました")

        logger.info("\n[検証] 全ての検証に合格しました ✓\n")

        # 設定読み込み
        self.config = ConfigLoader(config_path)
        self.trading_pairs = self.config.get('trading_pairs', [])

        # 取引設定を保存（DRY: 複数箇所での重複取得を防ぐ）
        trading_config = self.config.get('trading', {})
        self.initial_capital = trading_config.get('initial_capital', 200000)
        self.min_confidence = trading_config.get('min_confidence', 0.6)

        # ヘルスチェッカー・パフォーマンストラッカー初期化
        self.health_checker = HealthChecker()
        self.performance_tracker = None  # 後で初期化

        # Phase 1: データインフラ初期化
        logger.info("\n[Phase 1] データインフラ初期化")
        self.db_manager = SQLiteManager()

        # BLOCKER-2: 起動時に不完全なペアポジションをチェック
        logger.info("\n[BLOCKER-2 チェック] 不完全なペアポジションを確認中...")
        incomplete_pairs = self.db_manager.recover_incomplete_pairs()
        if incomplete_pairs and not test_mode:
            logger.critical("\n" + "=" * 70)
            logger.critical("🚨 起動中止: 不完全なペアポジションが存在します")
            logger.critical("=" * 70)
            logger.critical("取引所で以下のポジションを手動確認し、")
            logger.critical("pair_position_states テーブルから該当レコードを削除してください。")
            logger.critical("=" * 70 + "\n")
            raise RuntimeError(
                f"不完全なペアポジションが{len(incomplete_pairs)}件存在します。"
                "手動で取引所を確認し、調整が必要です。"
            )
        elif incomplete_pairs and test_mode:
            logger.warning(f"⚠️  テストモード: 不完全なペアポジション{len(incomplete_pairs)}件を検出しましたが続行します")
        else:
            logger.info("  ✓ 不完全なペアポジションなし")

        self.data_collector = BitflyerDataCollector()
        self.indicators = TechnicalIndicators()
        logger.info("  ✓ データベース、API、指標計算モジュール初期化完了")

        # Phase 2: MLモデル初期化
        logger.info("\n[Phase 2] MLモデル初期化")
        self.feature_engineer = FeatureEngineer()
        self.hmm_model = MarketRegimeHMM(n_states=3)
        self.lgbm_model = PriceDirectionLGBM()
        self.ensemble_model = EnsembleModel(self.hmm_model, self.lgbm_model)
        logger.info("  ✓ 特徴量エンジニアリング、HMM、LightGBM、アンサンブルモデル初期化完了")

        # Phase 3: 取引エンジン初期化
        logger.info("\n[Phase 3] 取引エンジン初期化")
        self.order_executor = OrderExecutor(test_mode=test_mode)
        self.position_manager = PositionManager(self.db_manager)

        # 設定値の安全性強制（危険な値を安全な範囲に修正）
        risk_config = self._enforce_safe_config(self.config.get('risk_management', {}))

        self.risk_manager = RiskManager(
            max_position_size=risk_config.get('max_position_size', 0.95),
            stop_loss_pct=risk_config.get('stop_loss_pct', 10.0),
            max_drawdown_pct=risk_config.get('max_drawdown_pct', 20.0),
            profit_taking_enabled=risk_config.get('profit_taking_enabled', True),
            consecutive_loss_limit=risk_config.get('consecutive_loss_limit', 5),
            max_daily_loss_pct=risk_config.get('max_daily_loss_pct', 5.0),
            max_weekly_loss_pct=risk_config.get('max_weekly_loss_pct', 10.0),
            max_monthly_loss_pct=risk_config.get('max_monthly_loss_pct', 15.0)
        )

        # ペアトレーディング戦略初期化（設定ファイルから読み込み）
        pt_config = self.config.get('pair_trading', {})

        # CONFIG-1, MEDIUM-6: 設定値の検証
        z_score_entry = pt_config.get('z_score_entry', 2.0)
        z_score_exit = pt_config.get('z_score_exit', 0.5)
        max_pairs = pt_config.get('max_pairs', 3)
        position_size_pct = pt_config.get('position_size_pct', 0.1)

        if z_score_entry <= 0 or z_score_entry > 10:
            logger.warning(f"⚠️ z_score_entry={z_score_entry}は範囲外。デフォルト2.0使用")
            z_score_entry = 2.0
        if z_score_exit < 0 or z_score_exit >= z_score_entry:
            logger.warning(f"⚠️ z_score_exit={z_score_exit}は不正。デフォルト0.5使用")
            z_score_exit = 0.5
        if max_pairs < 0 or max_pairs > 100:
            logger.warning(f"⚠️ max_pairs={max_pairs}は範囲外。デフォルト3使用")
            max_pairs = 3
        if position_size_pct <= 0 or position_size_pct > 1.0:
            logger.warning(f"⚠️ position_size_pct={position_size_pct}は範囲外。デフォルト0.1使用")
            position_size_pct = 0.1

        pair_trading_config = PairTradingConfig(
            z_score_entry=z_score_entry,
            z_score_exit=z_score_exit,
            z_score_stop_loss=pt_config.get('z_score_stop_loss', 4.0),
            max_pairs=max_pairs,
            position_size_pct=position_size_pct,
            lookback_period=pt_config.get('lookback_period', 252),
            rebalance_interval=pt_config.get('rebalance_interval', 24),
            min_half_life=pt_config.get('min_half_life', 5.0),
            max_half_life=pt_config.get('max_half_life', 60.0),
            take_profit_pct=pt_config.get('take_profit_pct', 0.03),
            trailing_stop_pct=pt_config.get('trailing_stop_pct', 0.015),
            min_profit_pct=pt_config.get('min_profit_pct', 0.005)
        )
        self.pair_trading_strategy = PairTradingStrategy(config=pair_trading_config)

        # DBからオープン中のペアポジションを復元
        self._restore_pair_positions()

        # DBからオープン中の通常ポジションを復元
        self._restore_regular_positions()

        # 戦略配分設定
        self.strategy_allocation = self.config.get('strategy_allocation', {
            'crypto_ratio': 0.5,
            'trend_ratio': 0.5,
            'cointegration_ratio': 0.5
        })

        logger.info("  ✓ 注文実行、ポジション管理、リスク管理、ペアトレーディングモジュール初期化完了")

        # Phase 4: レポート・通知初期化
        logger.info("\n[Phase 4] レポート・通知初期化")
        telegram_config = self.config.get('telegram', {})
        self.notifier = TelegramNotifier(
            bot_token=telegram_config.get('bot_token'),
            chat_id=telegram_config.get('chat_id'),
            enabled=telegram_config.get('enabled', False)
        )

        # Telegram Botハンドラー初期化（コマンド受信用）
        chat_id = telegram_config.get('chat_id')
        self.telegram_bot = TelegramBotHandler(
            bot_token=telegram_config.get('bot_token'),
            allowed_chat_ids=[chat_id] if chat_id else [],
            trader_instance=self
        )

        self.report_generator = ReportGenerator(self.db_manager, self.data_collector)
        logger.info("  ✓ Telegram通知、Botハンドラー、レポート生成モジュール初期化完了")

        # 状態管理
        self.is_running = False
        self.last_prediction_time = {}
        self.models_loaded = False

        # ✨ 並行処理ロック（競合状態を防止）
        self.order_lock = threading.Lock()  # 注文実行の排他制御
        self.position_lock = threading.Lock()  # ポジション操作の排他制御
        self.balance_lock = threading.Lock()  # 残高チェックの排他制御
        self.api_failure_lock = threading.Lock()  # MEDIUM-5: API失敗カウンターの排他制御
        self.safe_mode_lock = threading.Lock()  # CRITICAL-4: safe_modeフラグの排他制御
        logger.info("  ✓ 並行処理ロック機構を初期化")

        logger.info("\n" + "=" * 70)
        logger.info("CryptoTrader 初期化完了")
        logger.info("=" * 70 + "\n")

    def _check_models_exist(self) -> bool:
        """モデルファイルの存在確認

        Returns:
            全てのモデルが存在する場合True
        """
        ml_models_dir = Path('ml_models')
        ml_models_dir.mkdir(exist_ok=True)

        all_exist = True
        for pair_config in self.trading_pairs:
            symbol = pair_config['symbol']
            symbol_safe = symbol.replace("/", "_")

            hmm_path = ml_models_dir / f'hmm_{symbol_safe}.pkl'
            lgbm_path = ml_models_dir / f'lgbm_{symbol_safe}.pkl'

            if not hmm_path.exists() or not lgbm_path.exists():
                logger.info(f"  ⚠ {symbol} のモデルファイルが存在しません")
                all_exist = False

        return all_exist

    def _restore_pair_positions(self):
        """DBからオープン中のペアポジションを復元"""
        failed_positions = []
        try:
            open_positions = self.db_manager.get_open_pair_positions()

            if not open_positions:
                logger.info("  復元するペアポジションはありません")
                return

            restored_count = 0
            for pos_data in open_positions:
                try:
                    position = PairPosition(
                        pair_id=pos_data['pair_id'],
                        symbol1=pos_data['symbol1'],
                        symbol2=pos_data['symbol2'],
                        direction=pos_data['direction'],
                        hedge_ratio=pos_data['hedge_ratio'],
                        entry_spread=pos_data['entry_spread'],
                        entry_z_score=pos_data['entry_z_score'],
                        entry_time=datetime.fromtimestamp(pos_data['entry_time']),
                        size1=pos_data['size1'],
                        size2=pos_data['size2'],
                        entry_price1=pos_data['entry_price1'],
                        entry_price2=pos_data['entry_price2'],
                        unrealized_pnl=pos_data.get('unrealized_pnl', 0.0),
                        max_pnl=pos_data.get('max_pnl', 0.0),
                        entry_capital=pos_data['entry_capital']
                    )

                    self.pair_trading_strategy.positions[position.pair_id] = position
                    restored_count += 1

                    logger.info(f"  ✓ ペアポジション復元: {position.pair_id}")

                except Exception as e:
                    logger.error(f"  ✗ ポジション復元エラー: {pos_data.get('pair_id', 'unknown')} - {e}")
                    failed_positions.append(pos_data.get('pair_id', 'unknown'))

            if restored_count > 0:
                logger.info(f"  ✓ {restored_count}件のペアポジションを復元しました")

            # ✨ 復元失敗が1件以上ある場合はセーフモードに移行
            if failed_positions:
                logger.error(f"  🚨 {len(failed_positions)}件のペアポジション復元に失敗 → セーフモード移行")
                self._set_safe_mode(True, "ポジション復元失敗")
                self.notifier.notify_error(
                    '起動時ポジション復元失敗',
                    f'{len(failed_positions)}件のペアポジション復元に失敗しました。\n'
                    f'失敗ポジション: {", ".join(failed_positions)}\n'
                    f'セーフモードで起動します（新規エントリー停止）。\n'
                    f'手動で取引所を確認してください。'
                )

        except Exception as e:
            logger.error(f"ペアポジション復元エラー: {e}")
            # 復元プロセス全体が失敗した場合もセーフモード
            self._set_safe_mode(True, "ポジション復元失敗")
            self.notifier.notify_error(
                '起動時ポジション復元失敗',
                f'ペアポジション復元プロセスが失敗しました。\n'
                f'エラー: {e}\n'
                f'セーフモードで起動します。'
            )

    def _restore_regular_positions(self):
        """DBからオープン中の通常ポジションを復元"""
        failed_positions = []
        try:
            df = self.db_manager.get_open_positions()

            if df.empty:
                logger.info("  復元する通常ポジションはありません")
                return

            # pending_execution状態のポジションを古い順にチェック
            now_timestamp = int(datetime.now().timestamp())
            five_minutes_ago = now_timestamp - 300  # 5分前

            restored_count = 0
            for _, row in df.iterrows():
                try:
                    # 5分以上前のpending_executionは失敗とみなす
                    if row['status'] == 'pending_execution':
                        if row['entry_time'] < five_minutes_ago:
                            logger.warning(f"  ⚠ 古い保留ポジションを失敗扱いに: {row['position_id']}")
                            self.db_manager.update_position(
                                row['position_id'],
                                {'status': 'execution_failed'}
                            )
                            continue
                        else:
                            # 最近のpending_executionはスキップ（まだ処理中の可能性）
                            logger.info(f"  → 保留中ポジションをスキップ: {row['position_id']}")
                            continue

                    # execution_failed状態もスキップ
                    if row['status'] == 'execution_failed':
                        continue

                    # openステータスのポジションのみ復元
                    if row['status'] == 'open':
                        position = Position(
                            symbol=row['symbol'],
                            side=row['side'],
                            entry_price=row['entry_price'],
                            quantity=row['entry_amount'],
                            entry_time=datetime.fromtimestamp(row['entry_time']),
                            position_id=row['position_id']
                        )

                        # ストップロス・利確レベルを復元
                        if pd.notna(row.get('stop_loss')):
                            position.stop_loss = row['stop_loss']
                        if pd.notna(row.get('take_profit')):
                            position.take_profit = row['take_profit']

                        # メモリに追加
                        self.position_manager.open_positions[row['symbol']] = position
                        restored_count += 1

                        logger.info(f"  ✓ ポジション復元: {row['symbol']} {row['side']} "
                                   f"{row['entry_amount']:.6f} @ ¥{row['entry_price']:,.0f}")

                except Exception as e:
                    logger.error(f"  ✗ ポジション復元エラー: {row.get('position_id', 'unknown')} - {e}")
                    if row.get('status') == 'open':  # openステータスの復元失敗のみカウント
                        failed_positions.append(row.get('position_id', 'unknown'))

            if restored_count > 0:
                logger.info(f"  ✓ {restored_count}件の通常ポジションを復元しました")

            # ✨ 復元失敗が1件以上ある場合はセーフモードに移行
            if failed_positions:
                logger.error(f"  🚨 {len(failed_positions)}件の通常ポジション復元に失敗 → セーフモード移行")
                self._set_safe_mode(True, "ポジション復元失敗")
                self.notifier.notify_error(
                    '起動時ポジション復元失敗',
                    f'{len(failed_positions)}件の通常ポジション復元に失敗しました。\n'
                    f'失敗ポジション: {", ".join(failed_positions)}\n'
                    f'セーフモードで起動します（新規エントリー停止）。\n'
                    f'手動で取引所を確認してください。'
                )

        except Exception as e:
            logger.error(f"通常ポジション復元エラー: {e}")
            # 復元プロセス全体が失敗した場合もセーフモード
            self._set_safe_mode(True, "ポジション復元失敗")
            self.notifier.notify_error(
                '起動時ポジション復元失敗',
                f'通常ポジション復元プロセスが失敗しました。\n'
                f'エラー: {e}\n'
                f'セーフモードで起動します。'
            )

    def reconcile_unknown_positions(self):
        """✨ execution_unknown状態のポジションを調整（定期実行）"""
        try:
            # execution_unknown状態のポジションを取得
            # BLOCKER-3: 安全な接続メソッドを使用
            conn = self.db_manager.get_connection(self.db_manager.trades_db)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT position_id, symbol, side, entry_amount, entry_price, entry_time
                FROM positions
                WHERE status = 'execution_unknown'
                ORDER BY entry_time DESC
                LIMIT 10
            """)
            unknown_positions = cursor.fetchall()
            # HIGH-1: 接続キャッシュ使用のため close() は不要（削除）

            if not unknown_positions:
                return  # unknown状態のポジションがない

            logger.info(f"\n[調整] execution_unknown状態のポジション: {len(unknown_positions)}件")

            now_timestamp = int(datetime.now().timestamp())

            for pos in unknown_positions:
                position_id, symbol, side, entry_amount, entry_price, entry_time = pos
                age_minutes = (now_timestamp - entry_time) / 60

                logger.info(f"  調整中: {position_id} ({symbol}, {age_minutes:.1f}分経過)")

                try:
                    # 取引所の現在の残高を確認
                    if symbol and '/' in symbol:
                        base_currency = symbol.split('/')[0]
                        balance = self.order_executor.get_balance(base_currency)
                        current_balance = balance.get('total', 0)

                        logger.info(f"    現在の{base_currency}残高: {current_balance:.6f}")

                        # 残高からポジションの存在を推定
                        # 注: 完全な推定は不可能だが、明らかなケースは判定できる
                        # より正確には取引所APIで注文履歴を照会する必要がある

                        # 10分以上経過したunknown状態は失敗扱いにする
                        if age_minutes > 10:
                            logger.warning(f"    → 10分経過のため失敗扱いに変更")
                            self.db_manager.update_position(
                                position_id,
                                {'status': 'execution_failed'}
                            )
                        else:
                            logger.info(f"    → まだ最近のため継続監視")

                except Exception as check_error:
                    logger.error(f"    ✗ 調整エラー: {check_error}")

            logger.info(f"  ✓ unknown状態の調整完了")

        except Exception as e:
            logger.error(f"unknown位置調整エラー: {e}")

    def _train_initial_models(self):
        """初回起動時のモデル学習"""
        logger.info("=" * 70)
        logger.info("初回モデル学習を開始します")
        logger.info("=" * 70 + "\n")

        ml_config = self.config.get('machine_learning', {})
        training_days = ml_config.get('initial_training_days', 730)

        for pair_config in self.trading_pairs:
            symbol = pair_config['symbol']
            symbol_safe = symbol.replace("/", "_")

            logger.info(f"\n[{symbol}] モデル学習開始（過去{training_days}日間のデータ使用）")

            try:
                # 学習データ取得（1時間足）
                limit = training_days * 24  # 時間数
                logger.info(f"  → データ取得中: {limit}本の1時間足データ")

                ohlcv_data = self.data_collector.fetch_ohlcv(symbol, '1h', limit)

                if ohlcv_data is None or len(ohlcv_data) < 100:
                    logger.error(f"  ✗ {symbol} データ取得失敗またはデータ不足")
                    continue

                # DataFrame作成
                df = pd.DataFrame(
                    ohlcv_data,
                    columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
                )
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

                # テクニカル指標計算
                logger.info(f"  → テクニカル指標計算中")
                df = self.indicators.calculate_all(df)

                # 特徴量エンジニアリング
                logger.info(f"  → 特徴量エンジニアリング実行中")
                df = self.feature_engineer.engineer_features(df)

                # NaN除去
                df = df.dropna()

                if len(df) < 100:
                    logger.error(f"  ✗ {symbol} 特徴量計算後のデータ不足")
                    continue

                logger.info(f"  → 学習データ準備完了: {len(df)}件")

                # HMMモデル学習
                logger.info(f"  → HMMモデル学習中...")
                hmm_model = MarketRegimeHMM(n_states=3)
                hmm_model.fit(df)
                hmm_path = f'ml_models/hmm_{symbol_safe}.pkl'
                hmm_model.save_model(hmm_path)
                logger.info(f"  ✓ HMMモデル保存: {hmm_path}")

                # LightGBMモデル学習
                logger.info(f"  → LightGBMモデル学習中...")
                lgbm_model = PriceDirectionLGBM()

                # ターゲット作成（次のN時間後の価格方向）
                df['target'] = (df['close'].shift(-1) > df['close']).astype(int)
                df = df.dropna()

                # 特徴量とターゲット分離
                feature_cols = [col for col in df.columns if col not in [
                    'timestamp', 'target', 'open', 'high', 'low', 'close', 'volume'
                ]]
                X = df[feature_cols]
                y = df['target']

                lgbm_model.fit(X, y)
                lgbm_path = f'ml_models/lgbm_{symbol_safe}.pkl'
                lgbm_model.save_model(lgbm_path)
                logger.info(f"  ✓ LightGBMモデル保存: {lgbm_path}")

                logger.info(f"\n[{symbol}] モデル学習完了 ✓\n")

            except Exception as e:
                logger.error(f"  ✗ {symbol} モデル学習エラー: {e}")
                logger.error(traceback.format_exc())
                continue

        logger.info("=" * 70)
        logger.info("初回モデル学習完了")
        logger.info("=" * 70 + "\n")

    def load_models(self):
        """保存済みMLモデルを読み込み"""
        logger.info("MLモデル読み込み中...")

        try:
            for pair_config in self.trading_pairs:
                symbol = pair_config['symbol']

                # HMMモデル読み込み
                hmm_loaded = self.hmm_model.load_model(f'ml_models/hmm_{symbol.replace("/", "_")}.pkl')

                # LightGBMモデル読み込み
                lgbm_loaded = self.lgbm_model.load_model(f'ml_models/lgbm_{symbol.replace("/", "_")}.pkl')

                if hmm_loaded and lgbm_loaded:
                    logger.info(f"  ✓ {symbol} モデル読み込み成功")
                else:
                    logger.warning(f"  ⚠ {symbol} モデルが見つかりません（未学習）")

            self.models_loaded = True
            logger.info("MLモデル読み込み完了\n")
            return True

        except Exception as e:
            logger.error(f"モデル読み込み失敗: {e}")
            logger.warning("モデル未読み込みで続行します（予測は無効）\n")
            return False

    def collect_and_store_data(self, symbol: str, timeframe: str = '1m', limit: int = 500):
        """データ収集とDB保存

        Args:
            symbol: 取引ペア
            timeframe: 時間足
            limit: 取得本数

        Returns:
            DataFrame or None
        """
        try:
            # OHLCV取得
            ohlcv_data = self.data_collector.fetch_ohlcv(symbol, timeframe, limit)

            if ohlcv_data is None or len(ohlcv_data) == 0:
                logger.warning(f"{symbol} データ取得失敗")
                return None

            df = pd.DataFrame(
                ohlcv_data,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

            # テクニカル指標計算
            df = self.indicators.calculate_all(df)

            # DB保存
            for _, row in df.iterrows():
                ohlcv_dict = {
                    'timestamp': int(row['timestamp'].timestamp()),  # Unix timestamp (INTEGER)
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'open': row['open'],
                    'high': row['high'],
                    'low': row['low'],
                    'close': row['close'],
                    'volume': row['volume']
                }
                self.db_manager.insert_ohlcv(ohlcv_dict)

            logger.info(f"  ✓ {symbol} データ収集・保存完了 ({len(df)}件)")
            return df

        except Exception as e:
            logger.error(f"{symbol} データ収集エラー: {e}")
            return None

    def generate_trading_signal(self, symbol: str) -> Optional[Dict]:
        """取引シグナル生成（トレンド戦略用）

        Args:
            symbol: 取引ペア

        Returns:
            シグナル情報 or None
        """
        if not self.models_loaded:
            logger.debug(f"{symbol} モデル未読み込み - シグナル生成スキップ")
            return None

        try:
            # 最新データ取得
            df = self.collect_and_store_data(symbol, limit=500)

            if df is None or len(df) < 100:
                logger.warning(f"{symbol} データ不足（最低100件必要）")
                return None

            # 特徴量生成
            try:
                df = self.feature_engineer.create_all_features(df)
                original_len = len(df)
                df = df.dropna()

                if len(df) == 0:
                    logger.warning(f"{symbol} 特徴量生成後データなし（NaN除去前: {original_len}件）")
                    return None

                if len(df) < 50:
                    logger.warning(f"{symbol} 特徴量生成後データ不足（{len(df)}件 < 50件）")
                    return None

            except Exception as fe_error:
                logger.error(f"{symbol} 特徴量エンジニアリングエラー: {fe_error}")
                return None

            # アンサンブルモデルで予測
            try:
                signal = self.ensemble_model.generate_trading_signal(
                    df,
                    confidence_threshold=self.min_confidence
                )
            except Exception as model_error:
                logger.error(f"{symbol} モデル予測エラー: {model_error}")
                # フォールバック: HOLDシグナル
                return {'signal': 'HOLD', 'confidence': 0.0, 'error': str(model_error)}

            logger.info(f"  ✓ {symbol} シグナル: {signal['signal']} (信頼度: {signal['confidence']:.2%})")

            return signal

        except Exception as e:
            logger.error(f"{symbol} シグナル生成エラー: {e}")
            logger.error(traceback.format_exc())
            return None

    def execute_trading_decision(self, symbol: str, signal: Dict):
        """取引判断と実行

        Args:
            symbol: 取引ペア
            signal: シグナル情報
        """
        try:
            # 現在価格取得
            current_price = self.order_executor.get_current_price(symbol)

            if current_price is None:
                logger.warning(f"{symbol} 価格取得失敗")
                return

            # 既存ポジション確認
            existing_position = self.position_manager.get_open_position(symbol)

            # ========== ポジション保有中 ==========
            if existing_position:
                self._manage_existing_position(existing_position, current_price, signal)
                return

            # ========== 新規エントリー判定 ==========
            if signal['signal'] == 'BUY':
                self._enter_new_position(symbol, SIDE_LONG, current_price, signal)
            elif signal['signal'] == 'SELL':
                self._enter_new_position(symbol, SIDE_SHORT, current_price, signal)
            else:
                logger.debug(f"{symbol} HOLD - エントリーなし")

        except Exception as e:
            logger.error(f"{symbol} 取引実行エラー: {e}")
            logger.error(traceback.format_exc())
            self.notifier.notify_error('取引実行エラー', str(e))

    def _manage_existing_position(self, position, current_price: float, signal: Dict):
        """既存ポジション管理

        Args:
            position: ポジションオブジェクト
            current_price: 現在価格
            signal: シグナル情報
        """
        symbol = position.symbol

        # 未実現損益計算
        unrealized_pnl = position.calculate_unrealized_pnl(current_price)
        unrealized_pnl_pct = position.calculate_unrealized_pnl_pct(current_price)

        logger.info(f"  {symbol} ポジション保有中: {position.side.upper()}")
        logger.info(f"    未実現損益: ¥{unrealized_pnl:,.0f} ({unrealized_pnl_pct:+.2f}%)")

        # リスク管理チェック
        exit_action = self.risk_manager.get_exit_action(position, current_price)

        if exit_action:
            action = exit_action['action']
            reason = exit_action['reason']

            logger.info(f"  → {action}: {reason}")

            # ストップロス or フル決済
            if action in ['stop_loss', 'full_close']:
                self._close_position(symbol, current_price, reason)

            # 部分決済
            elif action == 'partial_close':
                close_ratio = exit_action['close_ratio']
                level = exit_action.get('level', 1)

                logger.info(f"  → 部分決済（第{level}段階）: {close_ratio:.0%}")

                # 部分決済を実行
                self._partial_close_position(symbol, current_price, close_ratio, level, unrealized_pnl_pct)

    def _get_available_capital(self, strategy_type: str = 'trend') -> float:
        """利用可能資金を取得（戦略配分を考慮）

        Args:
            strategy_type: 'trend' or 'cointegration'

        Returns:
            利用可能資金
        """
        try:
            balance = self.order_executor.get_balance('JPY')
            total_free = balance.get('free', 0)

            if total_free <= 0:
                logger.warning("利用可能残高がありません")
                return 0.0

            # 戦略配分を適用
            alloc = self.config.get('strategy_allocation', {})
            crypto_ratio = alloc.get('crypto_ratio', 0.5)

            # コイン投資に割り当てられた資金
            crypto_capital = total_free * crypto_ratio

            # 戦略タイプに応じた配分
            if strategy_type == 'trend':
                trend_ratio = alloc.get('trend_ratio', 0.5)
                return crypto_capital * trend_ratio
            elif strategy_type == 'cointegration':
                coint_ratio = alloc.get('cointegration_ratio', 0.5)
                return crypto_capital * coint_ratio
            else:
                return crypto_capital

        except Exception as e:
            logger.error(f"残高取得エラー: {e}")
            return 0.0

    # ========== CRITICAL-4: safe_modeスレッドセーフアクセス ==========

    def _set_safe_mode(self, value: bool, reason: str = ""):
        """safe_modeをスレッドセーフに設定"""
        with self.safe_mode_lock:
            old_value = self.safe_mode
            self.safe_mode = value
            if old_value != value:
                status = "発動" if value else "解除"
                logger.info(f"セーフモード{status}: {reason}" if reason else f"セーフモード{status}")

    def _is_safe_mode(self) -> bool:
        """safe_modeをスレッドセーフに取得"""
        with self.safe_mode_lock:
            return self.safe_mode

    # ========== API障害ハンドリング ==========

    def _handle_api_failure(self, operation: str = "API操作"):
        """
        API失敗時の処理

        Args:
            operation: 失敗した操作名
        """
        # MEDIUM-5: API失敗カウンターをスレッドセーフに更新
        with self.api_failure_lock:
            # CRITICAL-7: カウンター上限設定（無制限増加防止）
            if self.api_failure_count < 9999:
                self.api_failure_count += 1
            current_count = self.api_failure_count

        logger.warning(f"⚠️  API失敗: {operation} ({current_count}/{self.api_failure_threshold}回)")

        # CRITICAL-4: スレッドセーフにsafe_modeをチェック・設定
        if current_count >= self.api_failure_threshold and not self._is_safe_mode():
            self._set_safe_mode(True, f"API障害検出（連続{current_count}回失敗）")
            logger.error("=" * 70)
            logger.error("🚨 セーフモード発動: API障害を検出しました")
            logger.error(f"   連続{current_count}回のAPI失敗")
            logger.error("   → 新規ポジションエントリーを停止します")
            logger.error("   → 既存ポジションの決済のみ許可します")
            logger.error("=" * 70)

            # Telegram通知
            if hasattr(self, 'notifier'):
                try:
                    self.notifier.send_message(
                        "🚨 *セーフモード発動*\n\n"
                        f"API障害を検出しました（連続{current_count}回失敗）\n"
                        "新規エントリーを停止し、既存ポジションの決済のみ許可します。"
                    )
                except Exception as e:
                    logger.error(f"Telegram通知失敗: {e}")

    def _handle_api_success(self):
        """API成功時の処理（カウンターリセット）"""
        # MEDIUM-5: API失敗カウンターをスレッドセーフにリセット
        with self.api_failure_lock:
            if self.api_failure_count > 0:
                old_count = self.api_failure_count
                self.api_failure_count = 0
                logger.info(f"✓ API復旧: 失敗カウンターをリセット（{old_count} → 0）")

        # CRITICAL-4: スレッドセーフにsafe_modeを解除
        if self._is_safe_mode():
            self._set_safe_mode(False, "API復旧")
            logger.info("=" * 70)
            logger.info("✅ セーフモード解除: API接続が回復しました")
            logger.info("   → 通常取引を再開します")
            logger.info("=" * 70)

            # Telegram通知
            if hasattr(self, 'notifier'):
                try:
                    self.notifier.send_message(
                        "✅ *セーフモード解除*\n\n"
                        "API接続が回復しました。\n"
                        "通常取引を再開します。"
                    )
                except Exception as e:
                    logger.error(f"Telegram通知失敗: {e}")

    def _enforce_safe_config(self, config: dict) -> dict:
        """
        設定値を安全な範囲に強制

        Args:
            config: 設定値の辞書

        Returns:
            安全な範囲に修正された設定値
        """
        safe_config = config.copy()
        modified = []

        # max_position_size: 0.1 ~ 0.95 に制限
        if 'max_position_size' in safe_config:
            original = safe_config['max_position_size']
            safe_config['max_position_size'] = max(0.1, min(0.95, original))
            if safe_config['max_position_size'] != original:
                modified.append(f"max_position_size: {original} → {safe_config['max_position_size']}")

        # stop_loss_pct: 1.0 ~ 50.0% に制限
        if 'stop_loss_pct' in safe_config:
            original = safe_config['stop_loss_pct']
            safe_config['stop_loss_pct'] = max(1.0, min(50.0, original))
            if safe_config['stop_loss_pct'] != original:
                modified.append(f"stop_loss_pct: {original}% → {safe_config['stop_loss_pct']}%")

        # max_drawdown_pct: 5.0 ~ 50.0% に制限
        if 'max_drawdown_pct' in safe_config:
            original = safe_config['max_drawdown_pct']
            safe_config['max_drawdown_pct'] = max(5.0, min(50.0, original))
            if safe_config['max_drawdown_pct'] != original:
                modified.append(f"max_drawdown_pct: {original}% → {safe_config['max_drawdown_pct']}%")

        # 損失制限: 0.1 ~ 50.0% に制限
        for key in ['max_daily_loss_pct', 'max_weekly_loss_pct', 'max_monthly_loss_pct']:
            if key in safe_config:
                original = safe_config[key]
                safe_config[key] = max(0.1, min(50.0, original))
                if safe_config[key] != original:
                    modified.append(f"{key}: {original}% → {safe_config[key]}%")

        # take_profit: 1.0 ~ 200.0% に制限
        for key in ['take_profit_first', 'take_profit_second']:
            if key in safe_config:
                original = safe_config[key]
                safe_config[key] = max(1.0, min(200.0, original))
                if safe_config[key] != original:
                    modified.append(f"{key}: {original}% → {safe_config[key]}%")

        # consecutive_loss_limit: 1 ~ 20 に制限
        if 'consecutive_loss_limit' in safe_config:
            original = safe_config['consecutive_loss_limit']
            safe_config['consecutive_loss_limit'] = max(1, min(20, int(original)))
            if safe_config['consecutive_loss_limit'] != original:
                modified.append(f"consecutive_loss_limit: {original} → {safe_config['consecutive_loss_limit']}")

        # max_positions: 1 ~ 10 に制限
        if 'max_positions' in safe_config:
            original = safe_config['max_positions']
            safe_config['max_positions'] = max(1, min(10, int(original)))
            if safe_config['max_positions'] != original:
                modified.append(f"max_positions: {original} → {safe_config['max_positions']}")

        # 修正があった場合は警告
        if modified:
            logger.warning("=" * 70)
            logger.warning("⚠️  設定値が危険な範囲にあったため、安全な値に修正しました:")
            for mod in modified:
                logger.warning(f"   • {mod}")
            logger.warning("=" * 70)

        return safe_config

    def _enter_new_position(self, symbol: str, side: str, current_price: float, signal: Dict, strategy_type: str = 'trend'):
        """新規ポジションエントリー

        Args:
            symbol: 取引ペア
            side: 'long' or 'short'
            current_price: 現在価格
            signal: シグナル情報
            strategy_type: 戦略タイプ（'trend' or 'cointegration'）
        """
        try:
            # セーフモードチェック
            if self._is_safe_mode():
                logger.warning(f"  🚨 {symbol} エントリー拒否: セーフモード中（新規エントリー停止）")
                return

            # ポジション数制限チェック
            max_positions = self.config.get('risk_management', {}).get('max_positions', 2)
            current_positions = len(self.position_manager.get_all_positions())

            if current_positions >= max_positions:
                logger.info(f"  {symbol} エントリー見送り: 最大ポジション数到達（{current_positions}/{max_positions}）")
                return

            # ✨ 並行処理ロック取得: 残高チェック〜注文実行を排他制御
            with self.order_lock:
                # 資産情報取得（戦略配分を考慮）
                available_capital = self._get_available_capital(strategy_type)

                if available_capital <= 0:
                    logger.warning(f"  {symbol} エントリー見送り: 利用可能資金なし")
                    return

                # エントリー可否チェック
                should_enter, reason = self.risk_manager.should_enter_trade(
                    signal_confidence=signal['confidence'],
                    min_confidence=self.min_confidence,
                    current_equity=available_capital,
                    initial_capital=self.initial_capital
                )

                if not should_enter:
                    logger.info(f"  {symbol} エントリー見送り: {reason}")
                    return

                # ポジションサイズ計算
                pair_config = next((p for p in self.trading_pairs if p['symbol'] == symbol), None)
                allocation = pair_config['allocation'] if pair_config else 0.5

                # 利用可能資本の割り当て（アロケーション × ポジションサイズ上限）
                position_capital = available_capital * allocation
                quantity = self.order_executor.calculate_position_size(
                    symbol,
                    position_capital,
                    position_ratio=self.risk_manager.max_position_size
                )

                if quantity <= 0:
                    logger.warning(f"  {symbol} ポジションサイズ不足")
                    return

                # 注文実行（二段階コミット）
                logger.info(f"  → 新規エントリー: {side.upper()} {quantity:.6f} {symbol} @ ¥{current_price:,.0f}")

                # 価格スリッページ保護: 注文直前に価格を再取得
                try:
                    latest_price = self.order_executor.get_current_price(symbol)
                    price_change_pct = abs(latest_price - current_price) / current_price * 100

                    # LOW-1: 定数化したスリッページ閾値を使用
                    if price_change_pct > PRICE_SLIP_WARNING_THRESHOLD * 100:
                        logger.warning(f"  ⚠️  価格スリッページ検出: {price_change_pct:.2f}% "
                                     f"(¥{current_price:,.0f} → ¥{latest_price:,.0f})")

                        if price_change_pct > PRICE_SLIP_ERROR_THRESHOLD * 100:
                            logger.error(f"  ✗ スリッページ過大 ({price_change_pct:.2f}%) - 注文中止")
                            return

                        # WARNING～ERROR範囲の場合は警告のみ、最新価格で続行
                        current_price = latest_price
                        logger.info(f"  → 最新価格で続行: ¥{current_price:,.0f}")

                        # 数量を再計算
                        quantity = self.order_executor.calculate_position_size(
                            symbol,
                            position_capital,
                            position_ratio=self.risk_manager.max_position_size
                        )
                        logger.info(f"  → 数量再計算: {quantity:.6f}")

                except Exception as price_error:
                    logger.warning(f"  ⚠️  最新価格取得失敗: {price_error} - 元の価格で続行")

                pending_position = None  # 例外ハンドリング用に初期化

                # 1. 保留ポジション作成（DB記録）
                pending_position = self.position_manager.create_pending_position(
                    symbol=symbol,
                    side=side,
                    entry_price=current_price,
                    quantity=quantity
                )

                if not pending_position:
                    logger.error(f"  ✗ 保留ポジション作成失敗: {symbol}")
                    return

                # 2. 注文実行（API障害検出機能付き）
                order = None
                try:
                    order = self.order_executor.create_market_order(
                        symbol,
                        ORDER_BUY if side == SIDE_LONG else ORDER_SELL,
                        quantity
                    )

                    # API成功
                    self._handle_api_success()

                except (TimeoutError, Exception) as api_error:
                    error_type = type(api_error).__name__

                    # タイムアウトの場合は注文状態を再確認
                    if 'timeout' in str(api_error).lower() or isinstance(api_error, TimeoutError):
                        logger.warning(f"  ⏱️  API タイムアウト: {api_error}")
                        logger.info(f"  → 注文状態を再確認します（指数バックオフリトライ）...")

                        # ✨ 指数バックオフで注文状態確認リトライ（定数から読み込み）
                        order_status = None

                        # タイムアウト時も一応orderがあるかチェック
                        if order and order.get('id'):
                            for attempt, delay in enumerate(ORDER_STATUS_RETRY_DELAYS, 1):
                                try:
                                    logger.info(f"    試行{attempt}/{len(ORDER_STATUS_RETRY_DELAYS)}: {delay}秒待機後に状態確認...")
                                    time.sleep(delay)

                                    # 注文状態を取得
                                    order_status = self.order_executor.get_order_status(order['id'], symbol)
                                    status = order_status.get('status', 'unknown')
                                    logger.info(f"    → 状態: {status}")

                                    # 確定状態なら成功
                                    if status in ORDER_FINAL_STATUSES:
                                        logger.info(f"  ✓ 注文状態確定: {status}")
                                        order = order_status
                                        break  # ループ脱出
                                    elif status == 'pending' or status == 'open':
                                        logger.info(f"    まだ処理中({status})、次回リトライ...")
                                        continue
                                    else:
                                        logger.warning(f"    不明な状態: {status}")
                                        continue

                                except Exception as status_error:
                                    logger.warning(f"    試行{attempt}失敗: {status_error}")
                                    if attempt == len(ORDER_STATUS_RETRY_DELAYS):
                                        # 全リトライ失敗
                                        logger.error(f"  ✗ 全リトライ失敗 - 状態不明")
                                        self.db_manager.update_position(
                                            pending_position.position_id,
                                            {'status': 'execution_unknown'}
                                        )
                                        return

                            # ループ後も状態が確定していない場合
                            if not order_status or order_status.get('status') not in ORDER_FINAL_STATUSES:
                                logger.error(f"  ✗ タイムアウト後も注文状態が確定せず")
                                self.db_manager.update_position(
                                    pending_position.position_id,
                                    {'status': 'execution_unknown'}
                                )
                                return
                        else:
                            # orderがない場合は失敗扱い
                            self._handle_api_failure(operation=f"{symbol} 注文実行（タイムアウト）")
                            self.position_manager.cancel_pending_position(
                                pending_position,
                                reason=f"タイムアウト: order_id不明"
                            )
                            logger.error(f"  ✗ タイムアウトかつorder_id取得失敗")
                            return
                    else:
                        # その他のAPI障害
                        self._handle_api_failure(operation=f"{symbol} 注文実行")
                        self.position_manager.cancel_pending_position(
                            pending_position,
                            reason=f"API障害: {error_type} - {str(api_error)}"
                        )
                        logger.error(f"  ✗ API障害により注文失敗: {api_error}")
                        return

                # 3. 注文結果に応じて確定またはキャンセル
                if order:
                    filled_amount = order.get('filled', 0)
                    requested_amount = order.get('amount', quantity)
                    order_status = order.get('status', 'unknown')

                    # 約定チェック（完全約定または部分約定）
                    if filled_amount > 0:
                        # HIGH-3: 実際の約定価格を取得（averageを優先、なければprice、最終的にcurrent_price）
                        actual_price = order.get('average') or order.get('price') or current_price

                        # 部分約定の警告
                        # LOW-1: 定数化した閾値を使用
                        if filled_amount < requested_amount * PARTIAL_FILL_THRESHOLD:
                            logger.warning(f"  ⚠️  部分約定: {filled_amount:.8f}/{requested_amount:.8f} "
                                         f"({filled_amount/requested_amount*100:.1f}%)")
                            # HIGH-4: 部分約定の数量でポジション確定
                            # この変更は confirm_pending_position() でDBに反映される
                            pending_position.quantity = filled_amount
                            pending_position.entry_price = actual_price  # 実際の約定価格も更新

                        # ポジション確定（完全約定または部分約定の数量で）
                        if self.position_manager.confirm_pending_position(pending_position, actual_price):
                            logger.info(f"  ✓ エントリー成功: {filled_amount:.8f} {symbol.split('/')[0]} "
                                       f"(ポジションID={pending_position.position_id})")
                            position = pending_position
                        else:
                            logger.error(f"  ✗ ポジション確定失敗")
                            return
                    else:
                        # 約定数量ゼロ = 完全失敗
                        self.position_manager.cancel_pending_position(
                            pending_position,
                            reason=f"約定ゼロ: status={order_status}"
                        )
                        logger.error(f"  ✗ 注文未約定: status={order_status}")
                        return

                    # Telegram通知（実際に約定した数量で通知）
                    self.notifier.notify_trade_open(
                        symbol,
                        side,
                        actual_price,
                        filled_amount  # 実際の約定数量
                    )
                else:
                    # order=None: 注文が全く作成されなかった
                    self.position_manager.cancel_pending_position(
                        pending_position,
                        reason="注文作成失敗: order=None"
                    )
                    logger.error(f"  ✗ 注文作成失敗: orderがNone")

        except Exception as e:
            # 例外発生時も保留ポジションをキャンセル
            if pending_position and pending_position.status == 'pending_execution':
                self.position_manager.cancel_pending_position(
                    pending_position,
                    reason=f"例外発生: {str(e)}"
                )
            logger.error(f"{symbol} エントリーエラー: {e}")
            logger.error(traceback.format_exc())

    def _partial_close_position(
        self,
        symbol: str,
        exit_price: float,
        close_ratio: float,
        level: int,
        unrealized_pnl_pct: float
    ):
        """ポジション部分決済

        Args:
            symbol: 取引ペア
            exit_price: 決済価格
            close_ratio: 決済比率（0.0-1.0）
            level: 利益確定段階（1 or 2）
            unrealized_pnl_pct: 未実現損益率
        """
        try:
            position = self.position_manager.get_open_position(symbol)

            if not position:
                logger.warning(f"{symbol} 部分決済対象ポジションなし")
                return

            # 部分決済する数量を計算
            partial_quantity = position.quantity * close_ratio

            logger.info(f"  → 部分決済実行: {partial_quantity:.6f} {symbol} ({close_ratio:.0%})")

            # 注文実行（部分決済）
            order = self.order_executor.create_market_order(
                symbol,
                ORDER_SELL if position.side == SIDE_LONG else ORDER_BUY,
                partial_quantity
            )

            # HIGH-4: order status field validation
            if order and order.get('status') in ORDER_SUCCESS_STATUSES:
                # ポジションマネージャーで部分決済処理
                partial_info = self.position_manager.partial_close_position(
                    symbol,
                    exit_price,
                    close_ratio
                )

                if partial_info:
                    logger.info(f"  ✓ 部分決済成功（第{level}段階）")
                    logger.info(f"    決済数量: {partial_info['partial_quantity']:.6f}")
                    logger.info(f"    残存数量: {partial_info['remaining_quantity']:.6f}")
                    logger.info(f"    部分損益: ¥{partial_info['partial_pnl']:,.0f} ({partial_info['partial_pnl_pct']:+.2f}%)")

                    # リスク管理に取引結果を記録（部分決済）
                    self.risk_manager.record_trade_result(partial_info['partial_pnl'], self.initial_capital)

                    # Telegram通知
                    self.notifier.notify_take_profit(
                        symbol,
                        level=level,
                        close_ratio=close_ratio,
                        pnl_pct=unrealized_pnl_pct
                    )
            else:
                logger.error(f"  ✗ 部分決済注文失敗: {order}")

        except Exception as e:
            logger.error(f"{symbol} 部分決済エラー: {e}")
            logger.error(traceback.format_exc())

    def _close_position(self, symbol: str, exit_price: float, reason: str):
        """ポジションクローズ

        Args:
            symbol: 取引ペア
            exit_price: 決済価格
            reason: 決済理由
        """
        try:
            position = self.position_manager.get_open_position(symbol)

            if not position:
                logger.warning(f"{symbol} クローズ対象ポジションなし")
                return

            # 注文実行
            order = self.order_executor.create_market_order(
                symbol,
                ORDER_SELL if position.side == SIDE_LONG else ORDER_BUY,
                position.quantity
            )

            # HIGH-4: order status field validation
            if order and order.get('status') in ORDER_SUCCESS_STATUSES:
                # ポジションクローズ
                closed_position = self.position_manager.close_position(symbol, exit_price)

                if closed_position:
                    pnl = closed_position.realized_pnl
                    pnl_pct = closed_position.calculate_unrealized_pnl_pct(exit_price)

                    logger.info(f"  ✓ ポジションクローズ: {reason}")
                    logger.info(f"    実現損益: ¥{pnl:,.0f} ({pnl_pct:+.2f}%)")

                    # リスク管理に取引結果を記録
                    self.risk_manager.record_trade_result(pnl, self.initial_capital)

                    # 利益確定トラッキングをリセット
                    self.risk_manager.reset_profit_tracking(symbol)

                    # Telegram通知
                    self.notifier.notify_trade_close(
                        symbol,
                        position.side,
                        position.entry_price,
                        exit_price,
                        position.quantity,
                        pnl,
                        pnl_pct
                    )
            else:
                logger.error(f"  ✗ 決済注文失敗: {order}")

        except Exception as e:
            logger.error(f"{symbol} クローズエラー: {e}")
            logger.error(traceback.format_exc())

    def run_cointegration_trading(self):
        """共和分（ペアトレーディング）の取引処理"""
        alloc = self.config.get('strategy_allocation', {})
        coint_ratio = alloc.get('cointegration_ratio', 0.5)

        if coint_ratio <= 0:
            logger.debug("共和分戦略は無効（配分0%）")
            return

        logger.info("\n[共和分戦略] 処理開始")

        try:
            # 価格データ収集（ペアトレーディング用）
            symbols = [p['symbol'] for p in self.trading_pairs]
            price_data = {}

            for symbol in symbols:
                df = self.collect_and_store_data(symbol, timeframe='1h', limit=300)
                if df is not None and len(df) > 0:
                    price_data[symbol] = df['close']

            if len(price_data) < 2:
                logger.warning("  共和分分析に必要なデータが不足")
                return

            # 共和分ペアを更新
            self.pair_trading_strategy.update_cointegration(price_data)

            if not self.pair_trading_strategy.cointegrated_pairs:
                logger.info("  共和分ペアが見つかりませんでした")
                return

            # シグナル生成
            signals = self.pair_trading_strategy.generate_signals(price_data)

            # 現在価格を収集（未実現損益更新用）
            current_prices = {}
            for symbol in symbols:
                price = self.order_executor.get_current_price(symbol)
                if price:
                    current_prices[symbol] = price

            # 未実現損益を更新
            self.pair_trading_strategy.update_unrealized_pnl(current_prices)

            # 既存ポジションの管理
            for pair_id, position in list(self.pair_trading_strategy.positions.items()):
                if pair_id in signals:
                    signal = signals[pair_id]
                    price1 = current_prices.get(position.symbol1)
                    price2 = current_prices.get(position.symbol2)

                    if price1 and price2:
                        # エグジット判定
                        should_exit, reason = self.pair_trading_strategy.should_exit(signal, position)
                        if should_exit:
                            logger.info(f"  ペアポジションクローズ: {pair_id} ({reason})")
                            self._close_pair_position(position, price1, price2, reason)

            # 新規エントリー判定
            for pair in self.pair_trading_strategy.cointegrated_pairs:
                pair_id = f"{pair.symbol1}_{pair.symbol2}"

                if pair_id not in signals:
                    continue

                signal = signals[pair_id]

                if self.pair_trading_strategy.should_enter(signal, pair_id):
                    price1 = self.order_executor.get_current_price(pair.symbol1)
                    price2 = self.order_executor.get_current_price(pair.symbol2)

                    if price1 and price2:
                        available_capital = self._get_available_capital('cointegration')
                        if available_capital > 0:
                            logger.info(f"  ペアエントリー: {pair_id} ({signal.signal})")
                            self._enter_pair_position(pair, signal, price1, price2, available_capital)

            logger.info("  ✓ 共和分戦略処理完了")

        except Exception as e:
            logger.error(f"共和分取引エラー: {e}")
            logger.error(traceback.format_exc())

    def _enter_pair_position(self, pair, signal, price1: float, price2: float, capital: float):
        """ペアポジションエントリー"""
        try:
            # ✨ 並行処理ロック取得: ペア取引の両方の注文を排他制御
            with self.order_lock:
                position = self.pair_trading_strategy.open_position(
                    pair, signal, price1, price2, capital
                )

                if position:
                    logger.info(f"    ✓ ペアポジション開始: {position.pair_id}")
                    logger.info(f"      {position.symbol1}: {position.size1:.6f}")
                    logger.info(f"      {position.symbol2}: {position.size2:.6f}")

                    # 残高チェック（空売り防止）
                    symbol1_base = position.symbol1.split('/')[0]  # BTC/JPY -> BTC
                    symbol2_base = position.symbol2.split('/')[0]  # ETH/JPY -> ETH

                    balance_ok = True

                    if position.direction == 'long_spread':
                        # symbol1買い、symbol2売り
                        # symbol2の保有量をチェック
                        balance2 = self.order_executor.get_balance(symbol2_base)
                        available2 = balance2.get('free', 0)

                        if available2 < position.size2:
                            logger.error(f"      ✗ {symbol2_base} 残高不足: 必要{position.size2:.6f}, 保有{available2:.6f}")
                            balance_ok = False
                    else:
                        # symbol1売り、symbol2買い
                        # symbol1の保有量をチェック
                        balance1 = self.order_executor.get_balance(symbol1_base)
                        available1 = balance1.get('free', 0)

                        if available1 < position.size1:
                            logger.error(f"      ✗ {symbol1_base} 残高不足: 必要{position.size1:.6f}, 保有{available1:.6f}")
                            balance_ok = False

                    if not balance_ok:
                        logger.error(f"      ✗ 残高不足のためペアエントリー中止")
                        # ポジションを削除
                        if position.pair_id in self.pair_trading_strategy.positions:
                            del self.pair_trading_strategy.positions[position.pair_id]
                        return

                    # ✨ CRITICAL: 注文実行の前にDBに保存（孤立ポジション防止）
                    # 注文成功後にDB保存が失敗すると、取引所にポジションが残るがボットは追跡できない
                    try:
                        self.db_manager.create_pair_position({
                            'pair_id': position.pair_id,
                            'symbol1': position.symbol1,
                            'symbol2': position.symbol2,
                            'direction': position.direction,
                            'hedge_ratio': position.hedge_ratio,
                            'entry_spread': position.entry_spread,
                            'entry_z_score': position.entry_z_score,
                            'entry_time': int(position.entry_time.timestamp()),
                            'size1': position.size1,
                            'size2': position.size2,
                            'entry_price1': position.entry_price1,
                            'entry_price2': position.entry_price2,
                            'entry_capital': position.entry_capital,
                            'status': 'pending_execution'  # 保留状態で保存
                        })
                        logger.debug(f"      ✓ ペアポジションをDB保存（保留状態）")
                    except Exception as db_error:
                        logger.error(f"      ✗ DB保存失敗（注文前）: {db_error}")
                        # DB保存失敗時は注文を実行しない
                        if position.pair_id in self.pair_trading_strategy.positions:
                            del self.pair_trading_strategy.positions[position.pair_id]
                        self.notifier.notify_error(
                            'ペアポジションDB保存失敗',
                            f'ペア {position.pair_id} のDB保存に失敗しました。\n'
                            f'安全のため注文は実行していません。\n'
                            f'エラー: {db_error}'
                        )
                        return

                    # 実際の注文実行
                    orders_success = True

                    # 注文1: symbol1
                    if position.direction == PAIR_LONG_SPREAD:
                        # long_spread: symbol1を買い、symbol2を売り
                        order1 = self.order_executor.create_market_order(position.symbol1, ORDER_BUY, position.size1)
                    else:
                        # short_spread: symbol1を売り、symbol2を買い
                        order1 = self.order_executor.create_market_order(position.symbol1, ORDER_SELL, position.size1)

                    if not order1 or order1.get('status') not in ORDER_SUCCESS_STATUSES:
                        logger.error(f"      ✗ {position.symbol1} 注文失敗")
                        orders_success = False

                    # 注文2: symbol2
                    if orders_success:
                        if position.direction == PAIR_LONG_SPREAD:
                            # long_spread: symbol2を売り
                            order2 = self.order_executor.create_market_order(position.symbol2, ORDER_SELL, position.size2)
                        else:
                            # short_spread: symbol2を買い
                            order2 = self.order_executor.create_market_order(position.symbol2, ORDER_BUY, position.size2)

                        if not order2 or order2.get('status') not in ORDER_SUCCESS_STATUSES:
                            logger.error(f"      ✗ {position.symbol2} 注文失敗")
                            orders_success = False

                            # ✨ CRITICAL: order1をロールバック（order1は成功していたが、order2が失敗）
                            logger.warning(f"      ⚠️  order1ロールバック開始: {position.symbol1}")
                            logger.warning(f"         → order2失敗により、order1を反対売買して相殺します")

                            try:
                                # BLOCKER-1: リトライロジック付きロールバック（間に合わせ対応）
                                rollback_side = ORDER_SELL if position.direction == PAIR_LONG_SPREAD else ORDER_BUY
                                rollback_success = False

                                for retry_attempt in range(MAX_ROLLBACK_RETRIES):
                                    if retry_attempt > 0:
                                        wait_time = ROLLBACK_RETRY_WAIT_BASE ** retry_attempt  # 指数バックオフ: 2s, 4s
                                        logger.warning(f"      リトライ {retry_attempt}/{MAX_ROLLBACK_RETRIES-1}: {wait_time}秒待機...")
                                        time.sleep(wait_time)

                                    rollback_order = self.order_executor.create_market_order(
                                        position.symbol1,
                                        rollback_side,
                                        position.size1
                                    )

                                    if rollback_order and rollback_order.get('status') in ORDER_SUCCESS_STATUSES:
                                        logger.warning(f"      ✓ ロールバック成功（試行{retry_attempt+1}回目）: {position.symbol1} {rollback_side}")
                                        rollback_success = True

                                        # ロールバック成功を通知
                                        self.notifier.notify_error(
                                            'ペア取引ロールバック',
                                            f'ペア: {position.pair_id}\n'
                                            f'Order2失敗のため、Order1をロールバックしました（{retry_attempt+1}回目で成功）。\n'
                                            f'{position.symbol1}: {rollback_side} {position.size1:.6f}'
                                        )
                                        break  # 成功したらループ脱出
                                    else:
                                        logger.warning(f"      ✗ ロールバック失敗（試行{retry_attempt+1}回目）")

                                if not rollback_success:
                                    # 全リトライ失敗 → CRITICAL
                                    logger.error(f"      ✗✗✗ ロールバック全{MAX_ROLLBACK_RETRIES}回失敗: {position.symbol1}")
                                    logger.error(f"         → 未ヘッジポジションが残っています！")

                                    # 緊急通知
                                    self.notifier.notify_error(
                                        '🚨 CRITICAL: ペア取引ロールバック失敗',
                                        f'ペア: {position.pair_id}\n'
                                        f'Order2が失敗し、Order1のロールバックも失敗しました。\n'
                                        f'未ヘッジポジション: {position.symbol1} {position.size1:.6f}\n'
                                        f'**手動で取引所を確認し、即座にポジションをクローズしてください**'
                                    )

                                    # HIGH-4: セーフモード移行（新規エントリー停止）
                                    self._set_safe_mode(True, "ペア取引ロールバック失敗")
                                    logger.critical("🚨 セーフモード移行: ロールバック失敗のため新規エントリーを停止")
                            except Exception as rollback_error:
                                # LOW-2: スタックトレース付きでログ
                                logger.error(f"      ✗✗✗ ロールバック処理エラー: {rollback_error}", exc_info=True)

                                # 緊急通知
                                self.notifier.notify_error(
                                    '🚨 CRITICAL: ペア取引ロールバックエラー',
                                    f'ペア: {position.pair_id}\n'
                                    f'Order2失敗後のロールバック処理でエラーが発生しました。\n'
                                    f'未ヘッジポジション: {position.symbol1} {position.size1:.6f}\n'
                                    f'エラー: {rollback_error}\n'
                                    f'**手動で取引所を確認し、即座にポジションをクローズしてください**'
                                )

                                # HIGH-4: セーフモード移行（新規エントリー停止）
                                self._set_safe_mode(True, "ポジション復元失敗")
                                logger.critical("🚨 セーフモード移行: ロールバック処理エラーのため新規エントリーを停止")

                    # 注文結果に応じてステータスを更新
                    if orders_success:
                        logger.info(f"      ✓ 両方の注文実行成功")

                        # ステータスを'open'に更新
                        try:
                            self.db_manager.update_pair_position(
                                position.pair_id,
                                {'status': 'open'}
                            )
                            logger.debug(f"      ✓ ペアポジションステータスを'open'に更新")
                        except Exception as update_error:
                            logger.error(f"      ✗ HIGH-3: ステータス更新失敗: {update_error}")
                            # HIGH-3: DB不整合の可能性があるため警告通知
                            self.notifier.notify_error(
                                'ペアポジションDB更新失敗',
                                f'ペア {position.pair_id} のステータス更新に失敗しました。\n'
                                f'ポジションは作成されていますが、ステータスが不正です。\n'
                                f'エラー: {update_error}'
                            )

                        # Telegram通知
                        self.notifier.notify_pair_trade_open(
                            pair_id=position.pair_id,
                            symbol1=position.symbol1,
                            symbol2=position.symbol2,
                            direction=position.direction,
                            size1=position.size1,
                            size2=position.size2,
                            price1=price1,
                            price2=price2,
                            z_score=signal.z_score,
                            hedge_ratio=signal.hedge_ratio
                        )
                    else:
                        # 注文失敗時はステータスを'execution_failed'に更新
                        logger.error(f"      ✗ 注文失敗")
                        try:
                            self.db_manager.update_pair_position(
                                position.pair_id,
                                {'status': 'execution_failed'}
                            )
                            logger.debug(f"      ✓ ペアポジションステータスを'execution_failed'に更新")
                        except Exception as update_error:
                            logger.error(f"      ✗ HIGH-3: ステータス更新失敗: {update_error}")
                            # HIGH-3: DB不整合の可能性があるため警告通知
                            self.notifier.notify_error(
                                'ペアポジション失敗状態の記録失敗',
                                f'ペア {position.pair_id} の失敗ステータス更新に失敗しました。\n'
                                f'エラー: {update_error}'
                            )

                        # メモリからも削除
                        if position.pair_id in self.pair_trading_strategy.positions:
                            del self.pair_trading_strategy.positions[position.pair_id]

        except Exception as e:
            logger.error(f"ペアエントリーエラー: {e}")
            logger.error(traceback.format_exc())

    def _close_pair_position(self, position, price1: float, price2: float, reason: str):
        """ペアポジションクローズ"""
        try:
            # 保有期間計算
            hold_duration = None
            if hasattr(position, 'entry_time') and position.entry_time:
                duration = datetime.now() - position.entry_time
                hours = int(duration.total_seconds() // 3600)
                minutes = int((duration.total_seconds() % 3600) // 60)
                hold_duration = f"{hours}時間{minutes}分"

            # 実際の決済注文実行
            logger.info(f"    ペアポジション決済開始: {position.pair_id}")
            orders_success = True

            # 注文1: symbol1を決済
            if position.direction == PAIR_LONG_SPREAD:
                # long_spread時にsymbol1を買っていた → 売却
                order1 = self.order_executor.create_market_order(position.symbol1, ORDER_SELL, position.size1)
            else:
                # short_spread時にsymbol1を売っていた → 買い戻し
                order1 = self.order_executor.create_market_order(position.symbol1, ORDER_BUY, position.size1)

            if not order1 or order1.get('status') not in ORDER_SUCCESS_STATUSES:
                logger.error(f"      ✗ {position.symbol1} 決済注文失敗")
                orders_success = False

            # 注文2: symbol2を決済
            if orders_success:
                if position.direction == PAIR_LONG_SPREAD:
                    # long_spread時にsymbol2を売っていた → 買い戻し
                    order2 = self.order_executor.create_market_order(position.symbol2, ORDER_BUY, position.size2)
                else:
                    # short_spread時にsymbol2を買っていた → 売却
                    order2 = self.order_executor.create_market_order(position.symbol2, ORDER_SELL, position.size2)

                if not order2 or order2.get('status') not in ORDER_SUCCESS_STATUSES:
                    logger.error(f"      ✗ {position.symbol2} 決済注文失敗")
                    orders_success = False

                    # ✨ CRITICAL: order1をロールバック（order1の決済は成功したが、order2の決済が失敗）
                    # → order1を再オープンしてヘッジ状態に戻す
                    logger.warning(f"      ⚠️  order1ロールバック開始: {position.symbol1}")
                    logger.warning(f"         → order2決済失敗により、order1を反対売買してヘッジ状態に戻します")

                    try:
                        # BLOCKER-1: リトライロジック付きロールバック（クローズ時も同様）
                        if position.direction == PAIR_LONG_SPREAD:
                            rollback_side = ORDER_BUY
                        else:
                            rollback_side = ORDER_SELL

                        rollback_success = False

                        for retry_attempt in range(MAX_ROLLBACK_RETRIES):
                            if retry_attempt > 0:
                                wait_time = ROLLBACK_RETRY_WAIT_BASE ** retry_attempt
                                logger.warning(f"      リトライ {retry_attempt}/{MAX_ROLLBACK_RETRIES-1}: {wait_time}秒待機...")
                                time.sleep(wait_time)

                            rollback_order = self.order_executor.create_market_order(
                                position.symbol1,
                                rollback_side,
                                position.size1
                            )

                            if rollback_order and rollback_order.get('status') in ORDER_SUCCESS_STATUSES:
                                logger.warning(f"      ✓ ロールバック成功（試行{retry_attempt+1}回目）: {position.symbol1} {rollback_side}")
                                logger.warning(f"         → ヘッジ状態を復元しました")
                                rollback_success = True

                                # ロールバック成功を通知
                                self.notifier.notify_error(
                                    'ペア取引クローズ・ロールバック',
                                    f'ペア: {position.pair_id}\n'
                                    f'Order2決済失敗のため、Order1をロールバックしました（{retry_attempt+1}回目で成功）。\n'
                                    f'{position.symbol1}: {rollback_side} {position.size1:.6f}\n'
                                    f'ヘッジ状態を維持しています。'
                                )
                                break
                            else:
                                logger.warning(f"      ✗ ロールバック失敗（試行{retry_attempt+1}回目）")

                        if not rollback_success:
                            # 全リトライ失敗 → CRITICAL
                            logger.error(f"      ✗✗✗ ロールバック全{MAX_ROLLBACK_RETRIES}回失敗: {position.symbol1}")
                            logger.error(f"         → 片側だけクローズされています！")

                            # 緊急通知
                            self.notifier.notify_error(
                                '🚨 CRITICAL: ペア取引クローズ・ロールバック失敗',
                                f'ペア: {position.pair_id}\n'
                                f'Order2決済が失敗し、Order1のロールバックも失敗しました。\n'
                                f'片側クローズ状態: {position.symbol1} のみクローズ済み\n'
                                f'{position.symbol2} はまだオープン中\n'
                                f'**手動で取引所を確認し、ヘッジ状態を復元してください**'
                            )

                            # HIGH-4: セーフモード移行（新規エントリー停止）
                            self._set_safe_mode(True, "ポジション復元失敗")
                            logger.critical("🚨 セーフモード移行: ロールバック失敗のため新規エントリーを停止")
                    except Exception as rollback_error:
                        # LOW-2: スタックトレース付きでログ
                        logger.error(f"      ✗✗✗ ロールバック処理エラー: {rollback_error}", exc_info=True)

                        # 緊急通知
                        self.notifier.notify_error(
                            '🚨 CRITICAL: ペア取引クローズ・ロールバックエラー',
                            f'ペア: {position.pair_id}\n'
                            f'Order2決済失敗後のロールバック処理でエラーが発生しました。\n'
                            f'片側クローズ状態: {position.symbol1} のみクローズ済み\n'
                            f'{position.symbol2} はまだオープン中\n'
                            f'エラー: {rollback_error}\n'
                            f'**手動で取引所を確認し、ヘッジ状態を復元してください**'
                        )

                        # HIGH-4: セーフモード移行（新規エントリー停止）
                        self._set_safe_mode(True, "ポジション復元失敗")
                        logger.critical("🚨 セーフモード移行: ロールバック処理エラーのため新規エントリーを停止")

            # 両方の決済注文が成功した場合のみ処理を続行
            if not orders_success:
                logger.error(f"      ✗ ペアポジション決済失敗: {position.pair_id}")
                logger.error(f"      ロールバック処理を実行しました（上記ログ参照）")
                return

            # 決済成功 - メモリから削除、損益計算
            logger.info(f"      ✓ 両方の決済注文実行成功")

            closed_position, pnl = self.pair_trading_strategy.close_position(
                position.pair_id, price1, price2, reason
            )

            logger.info(f"    ✓ ペアポジション終了: {position.pair_id}")
            logger.info(f"      損益: ¥{pnl:,.0f} ({reason})")

            # データベースに永続化
            try:
                self.db_manager.close_pair_position(position.pair_id, {
                    'exit_price1': price1,
                    'exit_price2': price2,
                    'exit_time': int(datetime.now().timestamp()),
                    'exit_reason': reason,
                    'realized_pnl': pnl
                })
            except Exception as db_error:
                logger.error(f"      ✗ DB更新失敗（決済記録）: {db_error}")
                # 決済自体は成功しているので、エラー通知のみ
                self.notifier.notify_error(
                    'ペアポジション決済DB更新失敗',
                    f'ペア {position.pair_id} の決済記録の保存に失敗しました。\n'
                    f'決済は正常に完了していますが、DB記録が不完全です。\n'
                    f'エラー: {db_error}'
                )

            # リスク管理に記録
            self.risk_manager.record_trade_result(pnl, self.initial_capital)

            # Telegram通知
            self.notifier.notify_pair_trade_close(
                pair_id=position.pair_id,
                symbol1=position.symbol1,
                symbol2=position.symbol2,
                pnl=pnl,
                reason=reason,
                hold_duration=hold_duration
            )

        except Exception as e:
            logger.error(f"ペアクローズエラー: {e}")
            logger.error(traceback.format_exc())

    def run_trading_cycle(self):
        """1サイクルの取引処理"""
        logger.info("\n" + "=" * 70)
        logger.info(f"取引サイクル開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 70)

        # 自動再開チェック（24時間経過で自動的に取引再開）
        if self.risk_manager.check_auto_resume():
            self.notifier.notify_info(
                "取引自動再開",
                "一時停止から24時間経過したため、取引を自動的に再開しました。"
            )

        # 戦略配分を取得
        alloc = self.config.get('strategy_allocation', {})
        trend_ratio = alloc.get('trend_ratio', 0.5)
        coint_ratio = alloc.get('cointegration_ratio', 0.5)

        try:
            # ========== トレンド戦略 ==========
            if trend_ratio > 0:
                logger.info("\n[トレンド戦略] 処理開始")
                for pair_config in self.trading_pairs:
                    symbol = pair_config['symbol']

                    logger.info(f"\n  [{symbol}] 処理中")

                    # シグナル生成
                    signal = self.generate_trading_signal(symbol)

                    if signal:
                        # 取引判断・実行
                        self.execute_trading_decision(symbol, signal)
                    else:
                        logger.debug(f"    {symbol} シグナルなし")
            else:
                logger.info("\n[トレンド戦略] 無効（配分0%）")

            # ========== 共和分戦略 ==========
            if coint_ratio > 0:
                self.run_cointegration_trading()
            else:
                logger.info("\n[共和分戦略] 無効（配分0%）")

            logger.info("\n" + "=" * 70)
            logger.info("取引サイクル完了")
            logger.info("=" * 70 + "\n")

        except Exception as e:
            logger.error(f"取引サイクルエラー: {e}")
            logger.error(traceback.format_exc())
            self.notifier.notify_error('取引サイクルエラー', str(e))

    def send_daily_report(self, report_type: str = "evening"):
        """定時レポート送信

        Args:
            report_type: レポート種別（morning/noon/evening）
        """
        try:
            type_labels = {
                'morning': '朝の',
                'noon': '昼の',
                'evening': '夜の'
            }
            label = type_labels.get(report_type, '')

            logger.info(f"{label}レポート生成中...")

            # レポート生成
            report = self.report_generator.generate_daily_report()
            stats = self.report_generator.generate_summary_stats()

            # 保有ポジション取得
            open_positions = []
            for pair_config in self.trading_pairs:
                symbol = pair_config['symbol']
                position = self.position_manager.get_open_position(symbol)

                if position:
                    current_price = self.order_executor.get_current_price(symbol)
                    if current_price:
                        open_positions.append({
                            'symbol': symbol,
                            'side': position.side,
                            'unrealized_pnl': position.calculate_unrealized_pnl(current_price),
                            'unrealized_pnl_pct': position.calculate_unrealized_pnl_pct(current_price)
                        })

            # Telegram送信
            self.notifier.notify_daily_summary(
                total_equity=stats.get('total_equity', 200000),
                daily_pnl=stats.get('daily_pnl', 0),
                daily_pnl_pct=stats.get('daily_pnl_pct', 0),
                trades_count=stats.get('total_trades', 0),
                win_rate=stats.get('win_rate', 0),
                open_positions=open_positions
            )

            logger.info(f"  ✓ {label}レポート送信完了\n")

        except Exception as e:
            logger.error(f"{label}レポート送信エラー: {e}")

    def send_weekly_report(self):
        """週次レポート送信"""
        try:
            logger.info("週次レポート生成中...")

            # 週次レポート生成
            report = self.report_generator.generate_weekly_report()

            # Telegramに送信（テキストとして）
            if self.notifier.enabled:
                self.notifier.send_message(report)

            logger.info("  ✓ 週次レポート送信完了\n")

        except Exception as e:
            logger.error(f"週次レポート送信エラー: {e}")

    def send_monthly_report(self):
        """月次レポート送信"""
        try:
            logger.info("月次レポート生成中...")

            # 月次レポート生成
            report = self.report_generator.generate_monthly_report()

            # Telegramに送信（テキストとして）
            if self.notifier.enabled:
                self.notifier.send_message(report)

            logger.info("  ✓ 月次レポート送信完了\n")

        except Exception as e:
            logger.error(f"月次レポート送信エラー: {e}")

    def _verify_initial_balance(self):
        """初期資産の検証

        設定ファイルのinitial_capitalと実際の取引所残高を比較し、
        大きな差異がある場合は警告を出す
        """
        try:
            trading_config = self.config.get('trading', {})
            initial_capital = trading_config.get('initial_capital', 200000)

            # 取引所の実際の残高を取得
            balance = self.data_collector.fetch_balance()

            if balance is None:
                logger.warning("  ⚠ 残高取得失敗 - 検証スキップ")
                return

            # JPY残高を取得
            jpy_balance = balance.get('JPY', {}).get('free', 0)
            total_balance = jpy_balance

            # 暗号資産の時価評価額も追加
            for symbol in ['BTC', 'ETH']:
                if symbol in balance:
                    crypto_amount = balance[symbol].get('free', 0)
                    if crypto_amount > 0:
                        # 現在価格取得
                        ticker = self.data_collector.fetch_ticker(f'{symbol}/JPY')
                        if ticker:
                            current_price = ticker.get('last', 0)
                            total_balance += crypto_amount * current_price

            logger.info(f"  設定上の初期資本: ¥{initial_capital:,.0f}")
            logger.info(f"  実際の取引所残高: ¥{total_balance:,.0f}")

            # 差異を計算（ゼロ除算を防ぐ）
            if initial_capital > 0:
                difference_pct = abs(total_balance - initial_capital) / initial_capital * 100
            else:
                logger.error("  ✗ initial_capitalが0または未設定です")
                return

            if difference_pct > 10:
                logger.warning(f"  ⚠ 警告: 設定値と実残高に{difference_pct:.1f}%の差異があります")
                logger.warning(f"  リスク管理が正確に機能しない可能性があります")
                logger.warning(f"  config.yaml の initial_capital を実残高に合わせて調整することを推奨します")
            else:
                logger.info(f"  ✓ 残高検証OK（差異: {difference_pct:.1f}%）")

        except Exception as e:
            logger.warning(f"  ⚠ 残高検証エラー: {e}")
            logger.warning(f"  検証をスキップして続行します")

    def start(self, interval_minutes: int = 5):
        """取引ボット開始

        Args:
            interval_minutes: 取引サイクル間隔（分）
        """
        logger.info("=" * 70)
        logger.info("CryptoTrader 取引開始")
        logger.info(f"サイクル間隔: {interval_minutes}分")
        logger.info("=" * 70 + "\n")

        # 起動時健全性チェック
        logger.info("\n[健全性チェック] システム状態確認中...")
        is_healthy, issues, warnings = self.health_checker.run_all_checks()
        self.health_checker.print_health_report(is_healthy, issues, warnings)

        if not is_healthy:
            logger.error("システムに問題があります。上記の問題を解決してから起動してください。")
            return

        # パフォーマンストラッカー初期化
        self.performance_tracker = PerformanceTracker(self.db_manager)

        # モデル存在チェック＆自動学習
        logger.info("\n[モデル確認] MLモデルの存在確認中...")
        if not self._check_models_exist():
            logger.warning("モデルファイルが存在しません。初回学習を実行します。")
            logger.warning("※ 学習には数分～数十分かかる場合があります")
            self._train_initial_models()
        else:
            logger.info("  ✓ 全てのモデルファイルが存在します")

        # モデル読み込み
        self.load_models()

        # 資産残高検証（本番モードのみ）
        if not self.test_mode:
            logger.info("\n[資産検証] 取引所残高確認中...")
            self._verify_initial_balance()

        # Telegram Bot起動（コマンド受信用）
        self.telegram_bot.start()

        self.is_running = True
        last_health_check = datetime.now()
        cycle_count = 0
        consecutive_api_errors = 0

        # レポート送信済みフラグ
        sent_reports = {
            'morning': None,  # 最後に送信した日付
            'noon': None,
            'evening': None,
            'weekly': None,
            'monthly': None
        }

        # レポート設定取得
        reporting_config = self.config.get('reporting', {})
        morning_time = reporting_config.get('morning_report_time', '07:00')
        noon_time = reporting_config.get('noon_report_time', '13:00')
        evening_time = reporting_config.get('evening_report_time', '22:00')
        weekly_day = reporting_config.get('weekly_report_day', 0)  # 月曜
        weekly_time = reporting_config.get('weekly_report_time', '22:00')
        monthly_day = reporting_config.get('monthly_report_day', -1)  # 月末
        monthly_time = reporting_config.get('monthly_report_time', '22:00')

        try:
            while self.is_running:
                try:
                    # 取引サイクル実行
                    self.run_trading_cycle()
                    cycle_count += 1

                    # サイクル成功時にAPIエラーカウントをリセット
                    if consecutive_api_errors > 0:
                        logger.info(f"サイクル成功 - APIエラーカウントリセット（前回: {consecutive_api_errors}回）")
                        consecutive_api_errors = 0

                    # ✨ 定期的にunknown状態のポジションを調整
                    if cycle_count % POSITION_RECONCILE_CYCLES == 0:
                        self.reconcile_unknown_positions()

                    # ✨ 定期的にWALチェックポイント
                    if cycle_count % WAL_CHECKPOINT_CYCLES == 0:
                        logger.info("[メンテナンス] WALチェックポイント実行")
                        self.db_manager.checkpoint_wal()

                    # CRITICAL-1: 定期的にDB接続をクリーンアップ
                    if cycle_count % DB_CONNECTION_REFRESH_CYCLES == 0:
                        logger.info("[メンテナンス] データベース接続をリフレッシュ")
                        self.db_manager.close_all_connections()
                        logger.debug("  ✓ 古い接続をクローズし、次回アクセス時に新規接続を作成します")

                    # 定時レポートチェック（1日3回）
                    now = datetime.now()
                    today = now.date()
                    current_time = now.strftime('%H:%M')

                    # 朝のレポート
                    if current_time >= morning_time and sent_reports['morning'] != today:
                        self.send_daily_report('morning')
                        sent_reports['morning'] = today

                    # 昼のレポート
                    if current_time >= noon_time and sent_reports['noon'] != today:
                        self.send_daily_report('noon')
                        sent_reports['noon'] = today

                    # 夜のレポート
                    if current_time >= evening_time and sent_reports['evening'] != today:
                        self.send_daily_report('evening')
                        sent_reports['evening'] = today

                    # 週次レポート（指定曜日の指定時刻）
                    if now.weekday() == weekly_day and current_time >= weekly_time:
                        if sent_reports['weekly'] != today:
                            self.send_weekly_report()
                            sent_reports['weekly'] = today

                    # 月次レポート（月末の指定時刻）
                    # 月末判定: 翌日が1日の場合
                    is_last_day_of_month = (now + timedelta(days=1)).day == 1
                    if is_last_day_of_month and current_time >= monthly_time:
                        # 月が変わったかチェック（同じ月に複数回送信しない）
                        if sent_reports['monthly'] != today:
                            self.send_monthly_report()
                            sent_reports['monthly'] = today

                    # 健全性チェック（1時間ごと）
                    if (datetime.now() - last_health_check).total_seconds() > 3600:
                        logger.info("\n[定期健全性チェック]")
                        is_healthy, issues, warnings = self.health_checker.run_all_checks()

                        if not is_healthy:
                            error_msg = "システムに問題が検出されました:\n" + "\n".join(issues)
                            logger.error(error_msg)
                            self.notifier.notify_error('健全性チェック失敗', error_msg)

                        last_health_check = datetime.now()

                    # パフォーマンスサマリー（10サイクルごと）
                    if cycle_count % 10 == 0 and self.performance_tracker:
                        logger.info("\n[パフォーマンスサマリー]")
                        self.performance_tracker.print_performance_report('all')

                    # 次のサイクルまで待機
                    logger.info(f"次のサイクルまで{interval_minutes}分待機...\n")
                    time.sleep(interval_minutes * 60)

                except Exception as cycle_error:
                    # サイクル内エラー処理
                    error_str = str(cycle_error)
                    is_api_error = any(keyword in error_str.lower() for keyword in [
                        'api', 'network', 'connection', 'timeout', 'exchange', 'request'
                    ])

                    if is_api_error:
                        consecutive_api_errors += 1
                        logger.error(f"APIエラー発生（{consecutive_api_errors}/{MAX_CONSECUTIVE_API_ERRORS}回目）: {cycle_error}")

                        # 連続APIエラー制限到達
                        if consecutive_api_errors >= MAX_CONSECUTIVE_API_ERRORS:
                            error_msg = (
                                f"連続APIエラー制限到達（{consecutive_api_errors}回）\n"
                                f"エラー: {cycle_error}\n"
                                f"システムを安全に停止します"
                            )
                            logger.critical(error_msg)
                            self.notifier.notify_error('緊急停止: API接続失敗', error_msg)

                            # 安全なシャットダウン
                            logger.info("安全なシャットダウンを開始します...")
                            self.stop()
                            break
                        else:
                            # リトライ前に待機（指数バックオフ）
                            wait_time = ROLLBACK_RETRY_WAIT_BASE ** consecutive_api_errors  # 2, 4, 8秒
                            logger.info(f"{wait_time}秒待機後にリトライします...")
                            time.sleep(wait_time)
                    else:
                        # 非APIエラー
                        logger.error(f"取引サイクルエラー: {cycle_error}")
                        logger.error(traceback.format_exc())
                        self.notifier.notify_error('取引サイクルエラー', str(cycle_error))

                        # 1サイクルスキップして継続
                        time.sleep(ERROR_RECOVERY_WAIT)

        except KeyboardInterrupt:
            logger.info("\n中断シグナル受信 - シャットダウン中...")
            self.stop()
        except Exception as e:
            logger.error(f"予期しないエラー: {e}")
            logger.error(traceback.format_exc())
            self.notifier.notify_error('システムエラー', str(e))
            self.stop()

    def stop(self):
        """取引ボット停止"""
        logger.info("=" * 70)
        logger.info("CryptoTrader 停止中...")
        logger.info("=" * 70)

        self.is_running = False

        # Telegram Bot停止
        self.telegram_bot.stop()

        # 最終レポート生成
        self.send_daily_report()

        # データベース接続クローズ
        logger.info("データベース接続をクローズ中...")
        self.db_manager.close()

        logger.info("\nCryptoTrader 停止完了\n")


def main():
    """メインエントリーポイント"""
    import argparse

    parser = argparse.ArgumentParser(description='CryptoTrader - 暗号資産自動売買システム')
    parser.add_argument(
        '--config',
        type=str,
        default='config/config.yaml',
        help='設定ファイルパス'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='テストモード（APIキーなし）'
    )
    parser.add_argument(
        '--interval',
        type=int,
        default=5,
        help='取引サイクル間隔（分）'
    )

    args = parser.parse_args()

    # LOW-2: 本番モード起動時の確認プロンプト
    if not args.test:
        logger.warning("=" * 70)
        logger.warning("⚠️  本番モードで起動しようとしています")
        logger.warning("   実際の資金で取引が実行されます！")
        logger.warning("=" * 70)

        # ユーザー確認
        try:
            confirmation = input("本番モードで続行しますか？ (yes/no): ").strip().lower()
            if confirmation not in ['yes', 'y']:
                logger.info("起動をキャンセルしました")
                return
        except (KeyboardInterrupt, EOFError):
            logger.info("\n起動をキャンセルしました")
            return

        logger.info("本番モードで起動を続行します...")

    # トレーダー起動
    trader = CryptoTrader(
        config_path=args.config,
        test_mode=args.test
    )

    trader.start(interval_minutes=args.interval)


if __name__ == "__main__":
    main()
