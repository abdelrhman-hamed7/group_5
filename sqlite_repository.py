import sqlite3
import os

class SQLiteDatabaseRepository:
    def __init__(self, db_path="payment_router.db"):
        self.db_path = db_path
        self._initialize_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_db(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id TEXT PRIMARY KEY,
                amount REAL NOT NULL,
                recipient TEXT NOT NULL,
                status TEXT NOT NULL,
                gateway TEXT NOT NULL
            )
        ''')
        conn.commit()
        conn.close()

    def get_transaction(self, tx_id: str) -> dict:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT transaction_id, amount, recipient, status, gateway FROM transactions WHERE transaction_id = ?', (tx_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
        return None

    def record_transaction(self, tx_id: str, amount: float, recipient: str, status: str, gateway: str):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO transactions (transaction_id, amount, recipient, status, gateway)
            VALUES (?, ?, ?, ?, ?)
        ''', (tx_id, amount, recipient, status, gateway))
        conn.commit()
        conn.close()