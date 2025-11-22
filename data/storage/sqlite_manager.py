"""SQLite データベースマネージャー"""

import sqlite3
import logging
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
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

        # HIGH-8: 接続キャッシュ（接続プーリング）
        self._connection_cache = {}

        # 初期化
        self._initialize_databases()

    def _initialize_databases(self):
        """データベースとテーブルの初期化"""
        self._init_price_db()
        self._init_trades_db()
        self._init_ml_models_db()
        # HIGH-6: 既存DBに外部キー制約を追加（マイグレーション）
        self._migrate_add_foreign_keys()
        logger.info("データベース初期化完了")

    def _connect_with_wal(self, db_path: str):
        """
        WALモードでデータベースに接続（HIGH-8: 接続キャッシュ使用）

        Args:
            db_path: データベースファイルパス

        Returns:
            WALモード有効化されたsqlite3.Connection
        """
        # HIGH-8: キャッシュから接続を取得（なければ新規作成）
        db_key = str(db_path)

        if db_key in self._connection_cache:
            conn = self._connection_cache[db_key]
            try:
                # 接続が有効か確認
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                # 無効な接続は削除して再作成
                del self._connection_cache[db_key]

        # 新しい接続を作成してキャッシュに保存
        conn = sqlite3.connect(db_path, check_same_thread=False)  # マルチスレッド対応
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        # HIGH-6: 外部キー制約を有効化（孤立レコード防止）
        conn.execute("PRAGMA foreign_keys=ON")

        self._connection_cache[db_key] = conn
        logger.debug(f"新規接続をキャッシュ: {Path(db_path).name}")

        return conn

    def _init_price_db(self):
        """価格データベースの初期化"""
        conn = self._connect_with_wal(self.price_db)  # WALと組み合わせて性能向上
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
        # HIGH-8: 接続はキャッシュされるためclose不要
        logger.info(f"価格データベース初期化: {self.price_db}")

        # データベースファイルの権限を制限（オーナーのみ読み書き）
        try:
            os.chmod(self.price_db, 0o600)
        except (OSError, FileNotFoundError):
            pass  # Windows環境では無視

    def _init_trades_db(self):
        """取引データベースの初期化"""
        conn = self._connect_with_wal(self.trades_db)
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
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            FOREIGN KEY (position_id) REFERENCES positions(position_id) ON DELETE SET NULL
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

        # インデックス作成
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_time ON trades(symbol, timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_pnl_date ON daily_pnl(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pair_positions_status ON pair_positions(status)")

        conn.commit()
        # HIGH-8: 接続はキャッシュされるためclose不要
        logger.info(f"取引データベース初期化: {self.trades_db}")

        # データベースファイルの権限を制限（オーナーのみ読み書き）
        try:
            os.chmod(self.trades_db, 0o600)
        except (OSError, FileNotFoundError):
            pass  # Windows環境では無視

    def _init_ml_models_db(self):
        """MLモデルデータベースの初期化"""
        conn = self._connect_with_wal(self.ml_models_db)
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
        # HIGH-8: 接続はキャッシュされるためclose不要
        logger.info(f"MLモデルデータベース初期化: {self.ml_models_db}")

        # データベースファイルの権限を制限（オーナーのみ読み書き）
        try:
            os.chmod(self.ml_models_db, 0o600)
        except (OSError, FileNotFoundError):
            pass  # Windows環境では無視

    def _migrate_add_foreign_keys(self):
        """
        HIGH-6: 既存のtradesテーブルに外部キー制約を追加するマイグレーション

        SQLiteは既存テーブルへのFK追加不可のため、テーブル再作成が必要
        """
        conn = self._connect_with_wal(self.trades_db)
        cursor = conn.cursor()

        try:
            # tradesテーブルのスキーマを確認
            cursor.execute("PRAGMA table_info(trades)")
            columns = cursor.fetchall()

            if not columns:
                # テーブルが存在しない場合はスキップ（新規作成時）
                # HIGH-8: 接続キャッシュのためclose不要 (conn.close())
                return

            # 外部キー制約があるか確認
            cursor.execute("PRAGMA foreign_key_list(trades)")
            fk_list = cursor.fetchall()

            if fk_list:
                # すでに外部キーがある場合はスキップ
                logger.debug("tradesテーブルはすでに外部キー制約を持っています")
                # HIGH-8: 接続キャッシュのためclose不要 (conn.close())
                return

            logger.info("🔧 HIGH-6: tradesテーブルに外部キー制約を追加中...")

            # 1. 一時テーブルにデータをバックアップ
            cursor.execute("ALTER TABLE trades RENAME TO trades_old")

            # 2. 新しいテーブルを外部キー付きで作成
            cursor.execute("""
            CREATE TABLE trades (
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
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                FOREIGN KEY (position_id) REFERENCES positions(position_id) ON DELETE SET NULL
            )
            """)

            # 3. データをコピー
            cursor.execute("""
            INSERT INTO trades (
                id, symbol, side, order_type, price, amount, cost, fee, fee_currency,
                timestamp, order_id, position_id, profit_loss, notes, created_at
            )
            SELECT
                id, symbol, side, order_type, price, amount, cost, fee, fee_currency,
                timestamp, order_id, position_id, profit_loss, notes, created_at
            FROM trades_old
            """)

            # 4. インデックスを再作成
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_symbol_time ON trades(symbol, timestamp)")

            # 5. 古いテーブルを削除
            cursor.execute("DROP TABLE trades_old")

            conn.commit()
            logger.info("✅ HIGH-6: 外部キー制約の追加完了")

        except Exception as e:
            conn.rollback()
            logger.error(f"外部キー制約の追加に失敗: {e}")
            # ロールバックでtrades_oldが残っている場合は元に戻す
            try:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades_old'")
                if cursor.fetchone():
                    cursor.execute("DROP TABLE IF EXISTS trades")
                    cursor.execute("ALTER TABLE trades_old RENAME TO trades")
                    conn.commit()
                    logger.info("テーブルを元に戻しました")
            except Exception as rollback_error:
                logger.error(f"ロールバック失敗: {rollback_error}")
        finally:
            # HIGH-8: 接続キャッシュのためclose不要 (conn.close())

    # ========== データ挿入メソッド ==========

    def insert_ohlcv(self, data: pd.DataFrame, symbol: str, timeframe: str):
        """
        OHLCVデータを挿入

        Args:
            data: OHLCVデータ（timestamp, open, high, low, close, volume）
            symbol: 通貨ペア
            timeframe: 時間足
        """
        conn = self._connect_with_wal(self.price_db)

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
            # HIGH-8: 接続キャッシュのためclose不要 (conn.close())

    def insert_trade(self, trade_data: Dict[str, Any]) -> int:
        """
        取引を挿入

        Args:
            trade_data: 取引データ

        Returns:
            挿入されたレコードID
        """
        conn = self._connect_with_wal(self.trades_db)
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
        except Exception as e:
            conn.rollback()
            logger.error(f"取引挿入失敗: {e}")
            raise
        finally:
            # HIGH-8: 接続キャッシュのためclose不要 (conn.close())

    def create_position(self, position_data: Dict[str, Any]) -> str:
        """
        新規ポジションを作成

        Args:
            position_data: ポジションデータ

        Returns:
            ポジションID
        """
        conn = self._connect_with_wal(self.trades_db)
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
                position_data.get('status', 'open')  # 渡されたstatusを使用（デフォルトは'open'）
            ))

            conn.commit()

            logger.info(f"ポジション作成: {position_data['position_id']}")
            return position_data['position_id']
        finally:
            # HIGH-8: 接続キャッシュのためclose不要 (conn.close())

    def update_position(self, position_id: str, updates: Dict[str, Any]):
        """
        ポジションを更新

        Args:
            position_id: ポジションID
            updates: 更新データ
        """
        conn = self._connect_with_wal(self.trades_db)
        try:
            cursor = conn.cursor()

            # 許可されたカラム名のホワイトリスト
            ALLOWED_POSITION_COLUMNS = {
                'entry_price', 'entry_amount',  # 二段階コミット確定時に必要
                'exit_price', 'exit_amount', 'exit_time', 'status',
                'profit_loss', 'profit_loss_pct', 'stop_loss', 'take_profit',
                'hold_time_hours'  # ポジション保有時間
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
            # HIGH-8: 接続キャッシュのためclose不要 (conn.close())

    # ========== ペアポジション操作メソッド ==========

    def create_pair_position(self, position_data: Dict[str, Any]) -> str:
        """
        新規ペアポジションを作成

        Args:
            position_data: ペアポジションデータ

        Returns:
            ペアID
        """
        conn = self._connect_with_wal(self.trades_db)
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
            # HIGH-8: 接続キャッシュのためclose不要 (conn.close())

    def update_pair_position(self, pair_id: str, updates: Dict[str, Any]):
        """
        ペアポジションを更新

        Args:
            pair_id: ペアID
            updates: 更新データ
        """
        conn = self._connect_with_wal(self.trades_db)
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
            # HIGH-8: 接続キャッシュのためclose不要 (conn.close())

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
        conn = self._connect_with_wal(self.trades_db)
        cursor = conn.cursor()

        cursor.execute("""
        SELECT * FROM pair_positions WHERE status = 'open'
        """)

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        # HIGH-8: 接続キャッシュのためclose不要 (conn.close())

        return [dict(zip(columns, row)) for row in rows]

    def get_pair_position(self, pair_id: str) -> Optional[Dict[str, Any]]:
        """
        特定のペアポジションを取得

        Args:
            pair_id: ペアID

        Returns:
            ペアポジションデータ or None
        """
        conn = self._connect_with_wal(self.trades_db)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM pair_positions WHERE pair_id = ?", (pair_id,))
        row = cursor.fetchone()

        if row:
            columns = [desc[0] for desc in cursor.description]
            # HIGH-8: 接続キャッシュのためclose不要 (conn.close())
            return dict(zip(columns, row))

        # HIGH-8: 接続キャッシュのためclose不要 (conn.close())
        return None

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
        conn = self._connect_with_wal(self.price_db)

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
        # HIGH-8: 接続キャッシュのためclose不要 (conn.close())

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
        conn = self._connect_with_wal(self.price_db)

        query = """
        SELECT * FROM ohlcv
        WHERE symbol = ? AND timeframe = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """

        df = pd.read_sql_query(query, conn, params=[symbol, timeframe, limit])
        # HIGH-8: 接続キャッシュのためclose不要 (conn.close())

        # 古い順に並び替え
        df = df.sort_values('timestamp').reset_index(drop=True)

        return df

    def get_open_positions(self) -> pd.DataFrame:
        """
        オープンポジションを取得

        Returns:
            ポジションデータフレーム
        """
        conn = self._connect_with_wal(self.trades_db)

        query = "SELECT * FROM positions WHERE status = 'open' ORDER BY entry_time DESC"
        df = pd.read_sql_query(query, conn)

        # HIGH-8: 接続キャッシュのためclose不要 (conn.close())
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
        conn = self._connect_with_wal(self.trades_db)

        query = """
        SELECT * FROM daily_pnl
        WHERE date >= ? AND date <= ?
        ORDER BY date ASC
        """

        df = pd.read_sql_query(query, conn, params=[start_date, end_date])
        # HIGH-8: 接続キャッシュのためclose不要 (conn.close())

        return df

    # ========== ユーティリティメソッド ==========

    def vacuum_databases(self):
        """データベースを最適化（VACUUM）"""
        for db_path in [self.price_db, self.trades_db, self.ml_models_db]:
            conn = self._connect_with_wal(db_path)
            conn.execute("VACUUM")
            # HIGH-8: 接続キャッシュのためclose不要 (conn.close())
            logger.info(f"VACUUM実行: {db_path.name}")

    def checkpoint_wal(self):
        """✨ WALチェックポイント実行（WAL→メインDBへの永続化）"""
        for db_path in [self.price_db, self.trades_db, self.ml_models_db]:
            try:
                conn = self._connect_with_wal(db_path)
                # TRUNCATE: WALファイルを切り詰め（サイズ削減）
                cursor = conn.cursor()
                cursor.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                result = cursor.fetchone()
                # result = (0, pages_written, pages_checkpointed)
                # 0 = success
                if result and result[0] == 0:
                    logger.debug(f"WALチェックポイント完了: {db_path.name} "
                               f"(書込={result[1]}, CP={result[2]})")
                else:
                    logger.warning(f"WALチェックポイント警告: {db_path.name} result={result}")
                # HIGH-8: 接続キャッシュのためclose不要 (conn.close())
            except Exception as e:
                logger.error(f"WALチェックポイント失敗: {db_path.name} - {e}")

    def close_all_connections(self):
        """HIGH-8: キャッシュされた全接続をクローズ"""
        for db_key, conn in list(self._connection_cache.items()):
            try:
                conn.commit()  # 未コミットの変更を保存
                conn.close()
                logger.debug(f"接続クローズ: {Path(db_key).name}")
            except Exception as e:
                logger.error(f"接続クローズ失敗: {Path(db_key).name} - {e}")

        self._connection_cache.clear()
        logger.info("全データベース接続をクローズしました")

    def __del__(self):
        """デストラクタ: オブジェクト破棄時に接続をクリーンアップ"""
        try:
            self.close_all_connections()
        except Exception:
            pass  # デストラクタでは例外を無視

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

    def backup_databases(self, backup_dir: str = "database/backups", keep_last: int = 10) -> Dict[str, str]:
        """
        MEDIUM-4: 全データベースをバックアップ

        Args:
            backup_dir: バックアップ保存先ディレクトリ
            keep_last: 保持する最新バックアップ数（古いものは自動削除）

        Returns:
            バックアップファイルパスの辞書 {db_name: backup_path}
        """
        import shutil
        from datetime import datetime

        backup_path = Path(backup_dir)
        backup_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_files = {}

        for name, db_path in [
            ('price_data', self.price_db),
            ('trades', self.trades_db),
            ('ml_models', self.ml_models_db)
        ]:
            if not db_path.exists():
                logger.warning(f"DBファイルが存在しません: {db_path}")
                continue

            try:
                # バックアップファイル名: dbname_YYYYMMDD_HHMMSS.db
                backup_file = backup_path / f"{name}_{timestamp}.db"

                # SQLiteの安全なバックアップ（VACUUM INTO使用）
                conn = self._connect_with_wal(db_path)
                conn.execute(f"VACUUM INTO '{backup_file}'")
                # HIGH-8: 接続キャッシュのためclose不要 (conn.close())

                backup_files[name] = str(backup_file)
                logger.info(f"バックアップ作成: {backup_file.name} ({backup_file.stat().st_size / 1024 / 1024:.2f} MB)")

            except Exception as e:
                logger.error(f"バックアップ失敗: {name} - {e}")

        # 古いバックアップを削除（最新N個を保持）
        if keep_last > 0:
            self._cleanup_old_backups(backup_path, keep_last)

        logger.info(f"データベースバックアップ完了: {len(backup_files)}個のDBを保存")
        return backup_files

    def _cleanup_old_backups(self, backup_dir: Path, keep_last: int):
        """
        古いバックアップファイルを削除

        Args:
            backup_dir: バックアップディレクトリ
            keep_last: 保持する最新ファイル数
        """
        # データベースごとに古いバックアップを削除
        for db_name in ['price_data', 'trades', 'ml_models']:
            # パターンに一致するファイルを取得
            backup_files = sorted(
                backup_dir.glob(f"{db_name}_*.db"),
                key=lambda p: p.stat().st_mtime,
                reverse=True  # 新しい順
            )

            # 古いファイルを削除
            for old_file in backup_files[keep_last:]:
                try:
                    old_file.unlink()
                    logger.debug(f"古いバックアップ削除: {old_file.name}")
                except Exception as e:
                    logger.error(f"バックアップ削除失敗: {old_file.name} - {e}")

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
