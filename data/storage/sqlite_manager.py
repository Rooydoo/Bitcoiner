"""SQLiteデータベース管理モジュール"""

import sqlite3
import pandas as pd
from pathlib import Path
from typing import Optional

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
    
    def connect(self):
        """データベース接続"""
        self.conn = sqlite3.connect(self.db_path)
        return self.conn
    
    def close(self):
        """接続クローズ"""
        if self.conn:
            self.conn.close()
    
    def execute(self, query: str, params: tuple = None):
        """クエリ実行"""
        cursor = self.conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        self.conn.commit()
        return cursor
    
    def fetch_df(self, query: str, params: tuple = None) -> pd.DataFrame:
        """クエリ結果をDataFrameで取得"""
        return pd.read_sql_query(query, self.conn, params=params)
