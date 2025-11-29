"""SQLite データベースマネージャー"""

import sqlite3
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime
import pandas as pd

logger = logging.getLogger(__name__)


class SQLiteManager:
    """SQLiteデータベース管理クラス"""

    def __init__(self, db_dir: str = "database"):
        """
        初期化

        Args:
            db_dir: データベースファイル格納ディレクトリ
        """
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)

        # データベースファイルパス
        self.price_db = self.db_dir / "price_data.db"
        self.trades_db = self.db_dir / "trades.db"
        self.ml_models_db = self.db_dir / "ml_models.db"

        # 初期化
        self._initialize_databases()

    def _initialize_databases(self):
        """データベースとテーブルの初期化"""
        self._init_price_db()
        self._init_trades_db()
        self._init_ml_models_db()
        logger.info("データベース初期化完了")

    def _connect_with_wal(self, db_path: str):
        """
        WALモードでデータベースに接続

        Args:
            db_path: データベースファイルパス

        Returns:
            WALモード有効化されたsqlite3.Connection
        """
        conn = sqlite3.connect(db_path)
        self._configure_database_safety(conn)
        return conn

    def _configure_database_safety(self, conn: sqlite3.Connection):
        """
        SQLiteを最大限のクラッシュ安全性に設定

        CRITICAL: すべての接続で呼び出す必要がある
        """
        try:
            # Write-Ahead Logging（ロールバックジャーナルより安全）
            conn.execute("PRAGMA journal_mode=WAL")

            # 毎コミットで完全fsync（遅いが安全）
            conn.execute("PRAGMA synchronous=FULL")

            # 外部キー制約を有効化
            conn.execute("PRAGMA foreign_keys=ON")

            # より大きなキャッシュでパフォーマンス向上
            conn.execute("PRAGMA cache_size=-64000")  # 64MB

            # 安全な削除（削除データを上書き）
            conn.execute("PRAGMA secure_delete=ON")

            conn.commit()

            # 設定を検証
            result = conn.execute("PRAGMA journal_mode").fetchone()
            if result[0] != 'wal':
                raise Exception("WALモードの有効化に失敗しました")

            logger.debug("データベース安全設定完了: WALモード, FULL同期, FK有効")

        except Exception as e:
            logger.error(f"データベース安全設定に失敗: {e}")
            raise

    def _get_connection(self, db_path) -> sqlite3.Connection:
        """
        適切に設定されたデータベース接続を取得

        Args:
            db_path: データベースファイルパス

        Returns:
            設定済みのsqlite3.Connection
        """
        conn = sqlite3.connect(db_path)
        self._configure_database_safety(conn)
        return conn

    def _init_price_db(self):
        """価格データベースの初期化"""
        conn = sqlite3.connect(self.price_db)
        self._configure_database_safety(conn)
        cursor = conn.cursor()

        # OHLCVテーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            UNIQUE(symbol, timeframe, timestamp)
        )
        """)

        # 板情報テーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS orderbook (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            bid_price REAL NOT NULL,
            bid_volume REAL NOT NULL,
            ask_price REAL NOT NULL,
            ask_volume REAL NOT NULL,
            spread REAL NOT NULL,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            UNIQUE(symbol, timestamp)
        )
        """)

        # 技術指標テーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS technical_indicators (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            indicator_name TEXT NOT NULL,
            value REAL,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            UNIQUE(symbol, timeframe, timestamp, indicator_name)
        )
        """)

        # インデックス作成
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_time ON ohlcv(symbol, timeframe, timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_orderbook_symbol_time ON orderbook(symbol, timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_indicators_symbol_time ON technical_indicators(symbol, timeframe, timestamp)")

        conn.commit()
        conn.close()
        logger.info(f"価格データベース初期化: {self.price_db}")

        # データベースファイルの権限を制限（オーナーのみ読み書き）
        try:
            os.chmod(self.price_db, 0o600)
        except (OSError, FileNotFoundError):
            pass  # Windows環境では無視

    def _init_trades_db(self):
        """取引データベースの初期化"""
        conn = sqlite3.connect(self.trades_db)
        self._configure_database_safety(conn)
        cursor = conn.cursor()

        # 取引履歴テーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            price REAL NOT NULL,
            amount REAL NOT NULL,
            cost REAL NOT NULL,
            fee REAL NOT NULL,
            fee_currency TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            order_id TEXT,
            position_id TEXT,
            profit_loss REAL,
            notes TEXT,
            created_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
        """)

        # ポジション履歴テーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id TEXT UNIQUE NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            entry_amount REAL NOT NULL,
            entry_time INTEGER NOT NULL,
            exit_price REAL,
            exit_amount REAL,
            exit_time INTEGER,
            stop_loss REAL,
            take_profit REAL,
            status TEXT NOT NULL,
            profit_loss REAL,
            profit_loss_pct REAL,
            hold_time_hours REAL,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            updated_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
        """)

        # 日次損益テーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_pnl (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            total_trades INTEGER DEFAULT 0,
            winning_trades INTEGER DEFAULT 0,
            losing_trades INTEGER DEFAULT 0,
            total_profit REAL DEFAULT 0,
            total_loss REAL DEFAULT 0,
            net_pnl REAL DEFAULT 0,
            win_rate REAL DEFAULT 0,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            updated_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
        """)

        # ペアポジションテーブル（共和分戦略用）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pair_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair_id TEXT UNIQUE NOT NULL,
            symbol1 TEXT NOT NULL,
            symbol2 TEXT NOT NULL,
            direction TEXT NOT NULL,
            hedge_ratio REAL NOT NULL,
            entry_spread REAL NOT NULL,
            entry_z_score REAL NOT NULL,
            entry_time INTEGER NOT NULL,
            size1 REAL NOT NULL,
            size2 REAL NOT NULL,
            entry_price1 REAL NOT NULL,
            entry_price2 REAL NOT NULL,
            entry_capital REAL NOT NULL,
            exit_price1 REAL,
            exit_price2 REAL,
            exit_time INTEGER,
            exit_reason TEXT,
            unrealized_pnl REAL DEFAULT 0,
            realized_pnl REAL,
            max_pnl REAL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'open',
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            updated_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
        """)

        # ペアポジション状態追跡テーブル（クラッシュリカバリー用）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS pair_position_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair_id TEXT UNIQUE NOT NULL,
            state TEXT NOT NULL,
            symbol1 TEXT NOT NULL,
            symbol2 TEXT NOT NULL,
            size1 REAL,
            size2 REAL,
            order1_id TEXT,
            order2_id TEXT,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            updated_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
        """)

        # インデックス作成
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_time ON trades(symbol, timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_pnl_date ON daily_pnl(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pair_positions_status ON pair_positions(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pair_states_state ON pair_position_states(state)")

        conn.commit()
        conn.close()
        logger.info(f"取引データベース初期化: {self.trades_db}")

        # データベースファイルの権限を制限（オーナーのみ読み書き）
        try:
            os.chmod(self.trades_db, 0o600)
        except (OSError, FileNotFoundError):
            pass  # Windows環境では無視

    def _init_ml_models_db(self):
        """MLモデルデータベースの初期化"""
        conn = sqlite3.connect(self.ml_models_db)
        self._configure_database_safety(conn)
        cursor = conn.cursor()

        # モデルメタデータテーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_name TEXT NOT NULL,
            model_type TEXT NOT NULL,
            version TEXT NOT NULL,
            file_path TEXT NOT NULL,
            training_start_date TEXT,
            training_end_date TEXT,
            hyperparameters TEXT,
            status TEXT DEFAULT 'active',
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            UNIQUE(model_name, version)
        )
        """)

        # 予測履歴テーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            prediction_direction TEXT NOT NULL,
            confidence_score REAL NOT NULL,
            expected_return REAL,
            risk_level TEXT,
            actual_direction TEXT,
            actual_return REAL,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (model_id) REFERENCES models(id)
        )
        """)

        # モデルパフォーマンステーブル
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id INTEGER NOT NULL,
            evaluation_date TEXT NOT NULL,
            accuracy REAL,
            precision_score REAL,
            recall REAL,
            f1_score REAL,
            sharpe_ratio REAL,
            max_drawdown REAL,
            total_return REAL,
            win_rate REAL,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (model_id) REFERENCES models(id)
        )
        """)

        # インデックス作成
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_predictions_model_time ON predictions(model_id, timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_performance_model ON performance(model_id)")

        conn.commit()
        conn.close()
        logger.info(f"MLモデルデータベース初期化: {self.ml_models_db}")

        # データベースファイルの権限を制限（オーナーのみ読み書き）
        try:
            os.chmod(self.ml_models_db, 0o600)
        except (OSError, FileNotFoundError):
            pass  # Windows環境では無視

    # ========== データ挿入メソッド ==========

    def insert_ohlcv(self, data: pd.DataFrame, symbol: str, timeframe: str):
        """
        OHLCVデータを挿入

        Args:
            data: OHLCVデータ（timestamp, open, high, low, close, volume）
            symbol: 通貨ペア
            timeframe: 時間足
        """
        conn = sqlite3.connect(self.price_db)

        # データ準備
        data = data.copy()
        data['symbol'] = symbol
        data['timeframe'] = timeframe

        # カラムの順序を明示的に指定
        columns_order = ['symbol', 'timeframe', 'timestamp', 'open', 'high', 'low', 'close', 'volume']
        data = data[columns_order]

        try:
            # 重複を無視して挿入（OR IGNORE）
            for _, row in data.iterrows():
                conn.execute("""
                    INSERT OR IGNORE INTO ohlcv (symbol, timeframe, timestamp, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, tuple(row))

            conn.commit()
            logger.debug(f"OHLCV挿入完了: {symbol} {timeframe} ({len(data)}件)")
        except Exception as e:
            logger.error(f"OHLCV挿入エラー: {e}")
            conn.rollback()
        finally:
            conn.close()

    def insert_trade(self, trade_data: Dict[str, Any]) -> int:
        """
        取引を挿入

        Args:
            trade_data: 取引データ

        Returns:
            挿入されたレコードID
        """
        conn = sqlite3.connect(self.trades_db)
        try:
            cursor = conn.cursor()

            cursor.execute("""
            INSERT INTO trades (
                symbol, side, order_type, price, amount, cost, fee, fee_currency,
                timestamp, order_id, position_id, profit_loss, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_data['symbol'],
                trade_data['side'],
                trade_data['order_type'],
                trade_data['price'],
                trade_data['amount'],
                trade_data['cost'],
                trade_data.get('fee', 0),
                trade_data.get('fee_currency', 'JPY'),
                trade_data['timestamp'],
                trade_data.get('order_id'),
                trade_data.get('position_id'),
                trade_data.get('profit_loss'),
                trade_data.get('notes')
            ))

            trade_id = cursor.lastrowid
            conn.commit()

            logger.info(f"取引記録: {trade_data['symbol']} {trade_data['side']} @ {trade_data['price']}")
            return trade_id
        finally:
            conn.close()

    def create_position(self, position_data: Dict[str, Any]) -> str:
        """
        新規ポジションを作成

        Args:
            position_data: ポジションデータ

        Returns:
            ポジションID
        """
        conn = sqlite3.connect(self.trades_db)
        try:
            cursor = conn.cursor()

            cursor.execute("""
            INSERT INTO positions (
                position_id, symbol, side, entry_price, entry_amount, entry_time,
                stop_loss, take_profit, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position_data['position_id'],
                position_data['symbol'],
                position_data['side'],
                position_data['entry_price'],
                position_data['entry_amount'],
                position_data['entry_time'],
                position_data.get('stop_loss'),
                position_data.get('take_profit'),
                'open'
            ))

            conn.commit()

            logger.info(f"ポジション作成: {position_data['position_id']}")
            return position_data['position_id']
        finally:
            conn.close()

    def update_position(self, position_id: str, updates: Dict[str, Any]):
        """
        ポジションを更新

        Args:
            position_id: ポジションID
            updates: 更新データ
        """
        conn = sqlite3.connect(self.trades_db)
        try:
            cursor = conn.cursor()

            # 許可されたカラム名のホワイトリスト
            ALLOWED_POSITION_COLUMNS = {
                'exit_price', 'exit_amount', 'exit_time', 'status',
                'profit_loss', 'profit_loss_pct', 'stop_loss', 'take_profit'
            }

            # カラム名を検証
            validated_updates = {k: v for k, v in updates.items() if k in ALLOWED_POSITION_COLUMNS}

            if not validated_updates:
                logger.warning(f"有効な更新カラムがありません: {list(updates.keys())}")
                return

            # 更新SQLを動的に生成
            set_clause = ", ".join([f"{key} = ?" for key in validated_updates.keys()])
            set_clause += ", updated_at = strftime('%s', 'now')"

            query = f"UPDATE positions SET {set_clause} WHERE position_id = ?"
            values = list(validated_updates.values()) + [position_id]

            cursor.execute(query, values)
            conn.commit()

            logger.debug(f"ポジション更新: {position_id}")
        finally:
            conn.close()

    # ========== ペアポジション操作メソッド ==========

    def create_pair_position(self, position_data: Dict[str, Any]) -> str:
        """
        新規ペアポジションを作成

        Args:
            position_data: ペアポジションデータ

        Returns:
            ペアID
        """
        conn = sqlite3.connect(self.trades_db)
        try:
            cursor = conn.cursor()

            cursor.execute("""
            INSERT INTO pair_positions (
                pair_id, symbol1, symbol2, direction, hedge_ratio,
                entry_spread, entry_z_score, entry_time,
                size1, size2, entry_price1, entry_price2, entry_capital, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                position_data['pair_id'],
                position_data['symbol1'],
                position_data['symbol2'],
                position_data['direction'],
                position_data['hedge_ratio'],
                position_data['entry_spread'],
                position_data['entry_z_score'],
                position_data['entry_time'],
                position_data['size1'],
                position_data['size2'],
                position_data['entry_price1'],
                position_data['entry_price2'],
                position_data['entry_capital'],
                'open'
            ))

            conn.commit()

            logger.info(f"ペアポジション作成: {position_data['pair_id']}")
            return position_data['pair_id']
        finally:
            conn.close()

    def update_pair_position(self, pair_id: str, updates: Dict[str, Any]):
        """
        ペアポジションを更新

        Args:
            pair_id: ペアID
            updates: 更新データ
        """
        conn = sqlite3.connect(self.trades_db)
        try:
            cursor = conn.cursor()

            # 許可されたカラム名のホワイトリスト
            ALLOWED_PAIR_COLUMNS = {
                'exit_spread', 'exit_z_score', 'exit_time', 'exit_price1', 'exit_price2',
                'status', 'profit_loss', 'profit_loss_pct', 'unrealized_pnl', 'max_pnl'
            }

            # カラム名を検証
            validated_updates = {k: v for k, v in updates.items() if k in ALLOWED_PAIR_COLUMNS}

            if not validated_updates:
                logger.warning(f"有効な更新カラムがありません: {list(updates.keys())}")
                return

            set_clause = ", ".join([f"{key} = ?" for key in validated_updates.keys()])
            set_clause += ", updated_at = strftime('%s', 'now')"

            query = f"UPDATE pair_positions SET {set_clause} WHERE pair_id = ?"
            values = list(validated_updates.values()) + [pair_id]

            cursor.execute(query, values)
            conn.commit()

            logger.debug(f"ペアポジション更新: {pair_id}")
        finally:
            conn.close()

    def close_pair_position(self, pair_id: str, exit_data: Dict[str, Any]):
        """
        ペアポジションをクローズ

        Args:
            pair_id: ペアID
            exit_data: 決済データ
        """
        updates = {
            'exit_price1': exit_data['exit_price1'],
            'exit_price2': exit_data['exit_price2'],
            'exit_time': exit_data['exit_time'],
            'exit_reason': exit_data['exit_reason'],
            'realized_pnl': exit_data['realized_pnl'],
            'status': 'closed'
        }
        self.update_pair_position(pair_id, updates)
        logger.info(f"ペアポジションクローズ: {pair_id} 損益=¥{exit_data['realized_pnl']:,.0f}")

    def get_open_pair_positions(self) -> List[Dict[str, Any]]:
        """
        オープン中のペアポジションを取得

        Returns:
            ペアポジションのリスト
        """
        conn = sqlite3.connect(self.trades_db)
        cursor = conn.cursor()

        cursor.execute("""
        SELECT * FROM pair_positions WHERE status = 'open'
        """)

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()

        return [dict(zip(columns, row)) for row in rows]

    def get_pair_position(self, pair_id: str) -> Optional[Dict[str, Any]]:
        """
        特定のペアポジションを取得

        Args:
            pair_id: ペアID

        Returns:
            ペアポジションデータ or None
        """
        conn = sqlite3.connect(self.trades_db)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM pair_positions WHERE pair_id = ?", (pair_id,))
        row = cursor.fetchone()

        if row:
            columns = [desc[0] for desc in cursor.description]
            conn.close()
            return dict(zip(columns, row))

        conn.close()
        return None

    # ========== アトミック操作メソッド（クラッシュセーフ） ==========

    def create_position_atomic(self, position_data: Dict[str, Any], order_callback: Callable) -> str:
        """
        アトミックにポジションを作成（注文実行と同時）

        Args:
            position_data: ポジション詳細
            order_callback: 注文を実行する関数

        Returns:
            成功時はポジションID、失敗時は例外を発生

        Raises:
            Exception: 注文失敗時またはDB操作失敗時
        """
        position_id = str(uuid.uuid4())

        conn = self._get_connection(self.trades_db)
        conn.execute("BEGIN IMMEDIATE")

        try:
            cursor = conn.cursor()

            # Step 1: まずPENDINGポジションをDBに書き込む
            cursor.execute("""
            INSERT INTO positions (
                position_id, symbol, side, entry_price, entry_amount,
                entry_time, stop_loss, take_profit, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """, (
                position_id,
                position_data['symbol'],
                position_data['side'],
                position_data['entry_price'],
                position_data['entry_amount'],
                int(time.time()),
                position_data.get('stop_loss'),
                position_data.get('take_profit')
            ))
            conn.commit()

            # Step 2: 取引所で注文実行
            # 失敗した場合、pendingポジションをクリーンアップ可能
            try:
                order = order_callback()

                if not order or order.get('status') not in ['closed', 'filled']:
                    raise Exception(f"注文失敗: {order}")

            except Exception as order_error:
                # 注文失敗 - pendingポジションを削除
                logger.error(f"注文実行失敗: {order_error}")
                cursor.execute("DELETE FROM positions WHERE position_id = ?", (position_id,))
                conn.commit()
                raise

            # Step 3: ポジションを'open'に更新
            cursor.execute("""
            UPDATE positions
            SET status = 'open', updated_at = strftime('%s', 'now')
            WHERE position_id = ?
            """, (position_id,))
            conn.commit()

            logger.info(f"✓ アトミックにポジション作成完了: {position_id}")
            return position_id

        except Exception as e:
            conn.rollback()
            logger.error(f"アトミックポジション作成失敗: {e}")
            raise
        finally:
            conn.close()

    def create_pair_position_atomic(
        self,
        pair_data: Dict[str, Any],
        order1_callback: Callable,
        order2_callback: Callable
    ) -> str:
        """
        状態追跡付きでアトミックにペアポジションを作成

        Args:
            pair_data: ペアポジションデータ
            order1_callback: 1つ目の注文を実行する関数
            order2_callback: 2つ目の注文を実行する関数

        Returns:
            成功時はペアID

        Raises:
            Exception: 注文失敗時（手動修正が必要な場合あり）
        """
        conn = self._get_connection(self.trades_db)
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()

        pair_id = pair_data['pair_id']

        try:
            # State 1: pendingペアを記録
            cursor.execute("""
            INSERT INTO pair_position_states
            (pair_id, state, symbol1, symbol2, size1, size2)
            VALUES (?, 'pending', ?, ?, ?, ?)
            """, (pair_id, pair_data['symbol1'], pair_data['symbol2'],
                  pair_data['size1'], pair_data['size2']))
            conn.commit()

            # 注文1を実行
            order1 = order1_callback()
            if not order1 or order1.get('status') not in ['closed', 'filled']:
                cursor.execute("UPDATE pair_position_states SET state = 'failed' WHERE pair_id = ?", (pair_id,))
                conn.commit()
                raise Exception(f"注文1失敗: {order1}")

            # State 2: 1つ目の注文完了
            cursor.execute("""
            UPDATE pair_position_states
            SET state = 'first_order_complete', order1_id = ?, updated_at = strftime('%s', 'now')
            WHERE pair_id = ?
            """, (order1.get('id'), pair_id))
            conn.commit()

            # 注文2を実行
            try:
                order2 = order2_callback()
                if not order2 or order2.get('status') not in ['closed', 'filled']:
                    raise Exception(f"注文2失敗: {order2}")
            except Exception as order2_error:
                # CRITICAL: 注文1は成功したが注文2が失敗
                # 補償取引が必要（またはマニュアル対応）
                logger.critical(f"ペアトレード不完全: 注文1成功、注文2失敗!")
                logger.critical(f"手動介入が必要: pair_id: {pair_id}")

                cursor.execute("""
                UPDATE pair_position_states
                SET state = 'incomplete_needs_manual_fix'
                WHERE pair_id = ?
                """, (pair_id,))
                conn.commit()

                raise Exception(f"ペアトレード不完全 - 手動修正が必要: {pair_id}")

            # State 3: 両方の注文完了 - フルポジション作成
            cursor.execute("""
            UPDATE pair_position_states
            SET state = 'open', order2_id = ?, updated_at = strftime('%s', 'now')
            WHERE pair_id = ?
            """, (order2.get('id'), pair_id))

            # 実際のペアポジションレコードを作成
            cursor.execute("""
            INSERT INTO pair_positions (
                pair_id, symbol1, symbol2, direction, hedge_ratio,
                entry_spread, entry_z_score, entry_time,
                size1, size2, entry_price1, entry_price2, entry_capital, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """, (
                pair_id, pair_data['symbol1'], pair_data['symbol2'],
                pair_data['direction'], pair_data['hedge_ratio'],
                pair_data['entry_spread'], pair_data['entry_z_score'],
                int(time.time()),
                pair_data['size1'], pair_data['size2'],
                pair_data['entry_price1'], pair_data['entry_price2'],
                pair_data['entry_capital']
            ))
            conn.commit()

            logger.info(f"✓ アトミックにペアポジション作成完了: {pair_id}")
            return pair_id

        except Exception as e:
            conn.rollback()
            logger.error(f"ペアポジション作成失敗: {e}")
            raise
        finally:
            conn.close()

    def recover_incomplete_pairs(self) -> List[Dict[str, Any]]:
        """
        起動時に不完全なペアポジションをチェック

        Returns:
            手動介入が必要なペアのリスト
        """
        conn = self._get_connection(self.trades_db)
        cursor = conn.cursor()

        cursor.execute("""
        SELECT pair_id, state, symbol1, symbol2, size1, size2, order1_id, order2_id,
               created_at, updated_at
        FROM pair_position_states
        WHERE state IN ('first_order_complete', 'incomplete_needs_manual_fix', 'pending')
        """)

        columns = ['pair_id', 'state', 'symbol1', 'symbol2', 'size1', 'size2',
                   'order1_id', 'order2_id', 'created_at', 'updated_at']
        rows = cursor.fetchall()
        conn.close()

        incomplete = [dict(zip(columns, row)) for row in rows]

        if incomplete:
            logger.critical(f"不完全なペアポジションを{len(incomplete)}件検出!")
            logger.critical("取引開始前に手動確認が必要です!")

        return incomplete

    def cleanup_pending_positions(self) -> int:
        """
        古いpendingポジションをクリーンアップ（10分以上前のもの）

        Returns:
            削除された件数
        """
        conn = self._get_connection(self.trades_db)
        cursor = conn.cursor()

        # 10分以上前のpendingを削除
        cutoff_time = int(time.time()) - 600

        cursor.execute("""
        DELETE FROM positions
        WHERE status = 'pending' AND entry_time < ?
        """, (cutoff_time,))

        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()

        if deleted_count > 0:
            logger.warning(f"古いpendingポジションを{deleted_count}件削除しました")

        return deleted_count

    def mark_pair_state_resolved(self, pair_id: str, resolution: str = 'manually_resolved'):
        """
        不完全なペア状態を解決済みにマーク

        Args:
            pair_id: ペアID
            resolution: 解決方法の説明
        """
        conn = self._get_connection(self.trades_db)
        cursor = conn.cursor()

        cursor.execute("""
        UPDATE pair_position_states
        SET state = ?, updated_at = strftime('%s', 'now')
        WHERE pair_id = ?
        """, (resolution, pair_id))

        conn.commit()
        conn.close()
        logger.info(f"ペア状態を解決済みにマーク: {pair_id} → {resolution}")

    # ========== データ取得メソッド ==========

    def get_ohlcv(self, symbol: str, timeframe: str,
                   start_time: Optional[int] = None,
                   end_time: Optional[int] = None,
                   limit: Optional[int] = None) -> pd.DataFrame:
        """
        OHLCVデータを取得

        Args:
            symbol: 通貨ペア
            timeframe: 時間足
            start_time: 開始時刻（Unix timestamp）
            end_time: 終了時刻（Unix timestamp）
            limit: 取得件数

        Returns:
            OHLCVデータフレーム
        """
        conn = sqlite3.connect(self.price_db)

        query = "SELECT * FROM ohlcv WHERE symbol = ? AND timeframe = ?"
        params = [symbol, timeframe]

        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)

        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)

        query += " ORDER BY timestamp ASC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        df = pd.read_sql_query(query, conn, params=params)
        conn.close()

        return df

    def get_latest_ohlcv(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        """
        最新のOHLCVデータを取得

        Args:
            symbol: 通貨ペア
            timeframe: 時間足
            limit: 取得件数

        Returns:
            OHLCVデータフレーム
        """
        conn = sqlite3.connect(self.price_db)

        query = """
        SELECT * FROM ohlcv
        WHERE symbol = ? AND timeframe = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """

        df = pd.read_sql_query(query, conn, params=[symbol, timeframe, limit])
        conn.close()

        # 古い順に並び替え
        df = df.sort_values('timestamp').reset_index(drop=True)

        return df

    def get_open_positions(self) -> pd.DataFrame:
        """
        オープンポジションを取得

        Returns:
            ポジションデータフレーム
        """
        conn = sqlite3.connect(self.trades_db)

        query = "SELECT * FROM positions WHERE status = 'open' ORDER BY entry_time DESC"
        df = pd.read_sql_query(query, conn)

        conn.close()
        return df

    def get_daily_pnl(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        日次損益を取得

        Args:
            start_date: 開始日（YYYY-MM-DD）
            end_date: 終了日（YYYY-MM-DD）

        Returns:
            日次損益データフレーム
        """
        conn = sqlite3.connect(self.trades_db)

        query = """
        SELECT * FROM daily_pnl
        WHERE date >= ? AND date <= ?
        ORDER BY date ASC
        """

        df = pd.read_sql_query(query, conn, params=[start_date, end_date])
        conn.close()

        return df

    # ========== ユーティリティメソッド ==========

    def vacuum_databases(self):
        """データベースを最適化（VACUUM）"""
        for db_path in [self.price_db, self.trades_db, self.ml_models_db]:
            conn = sqlite3.connect(db_path)
            conn.execute("VACUUM")
            conn.close()
            logger.info(f"VACUUM実行: {db_path.name}")

    def get_database_sizes(self) -> Dict[str, float]:
        """
        データベースのサイズを取得

        Returns:
            各データベースのサイズ（MB）
        """
        sizes = {}
        for name, db_path in [
            ('price_data', self.price_db),
            ('trades', self.trades_db),
            ('ml_models', self.ml_models_db)
        ]:
            if db_path.exists():
                size_mb = db_path.stat().st_size / (1024 * 1024)
                sizes[name] = round(size_mb, 2)
            else:
                sizes[name] = 0.0

        return sizes

    def close_all(self):
        """全接続をクローズ（実際にはSQLiteは自動管理）"""
        logger.info("SQLiteマネージャー終了")
        # SQLiteは各メソッド内で接続を開閉しているため、
        # 明示的にクローズする必要はないが、念のため確認
        # 将来的に永続的接続を使う場合のために実装を用意

    def close(self):
        """close_all()のエイリアス"""
        self.close_all()

    def __del__(self):
        """デストラクタでクリーンアップ"""
        try:
            self.close_all()
        except Exception:
            # デストラクタでの例外は無視
            pass


# シングルトンインスタンス
_db_manager = None

def get_db_manager() -> SQLiteManager:
    """
    データベースマネージャーのシングルトンインスタンスを取得

    Returns:
        SQLiteManagerインスタンス
    """
    global _db_manager
    if _db_manager is None:
        _db_manager = SQLiteManager()
    return _db_manager
