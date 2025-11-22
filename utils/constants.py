"""システム全体で使用する定数定義

HIGH-2: ハードコードされたマジックナンバーを定数化
"""

# ========== 取引所手数料 ==========
BITFLYER_COMMISSION_RATE = 0.0015  # 0.15% (bitFlyer手数料)

# ========== リスク管理 ==========
MAX_ORDER_COST_JPY = 100_000_000  # 最大注文金額: ¥100M
BALANCE_BUFFER_RATE = 0.03  # 残高バッファ: 3%
PRICE_SLIP_WARNING_THRESHOLD = 0.02  # 価格スリッページ警告: 2%
PRICE_SLIP_ERROR_THRESHOLD = 0.05  # 価格スリッページエラー: 5%

# LOW-1: 部分約定判定閾値
PARTIAL_FILL_THRESHOLD = 0.95  # 95%未満なら部分約定とみなす

# ========== タイムアウト設定 ==========
ORDER_STATUS_RETRY_DELAYS = [2, 4, 8, 16, 16, 16]  # 注文状態確認リトライ (秒)
ORDER_STATUS_TOTAL_TIMEOUT = sum(ORDER_STATUS_RETRY_DELAYS)  # 合計62秒

# ========== 価格精度 ==========
JPY_PRICE_DECIMALS = 0  # JPY建て価格の小数点桁数
CRYPTO_AMOUNT_DECIMALS = 8  # 暗号通貨数量の小数点桁数
DEFAULT_DECIMALS = 8  # その他のデフォルト精度

# ========== データベース ==========
DB_CONNECTION_REFRESH_CYCLES = 180  # DB接続リフレッシュ間隔 (約3時間)
WAL_CHECKPOINT_CYCLES = 60  # WALチェックポイント間隔 (約1時間)
POSITION_RECONCILE_CYCLES = 10  # ポジション調整間隔

# ========== API障害ハンドリング ==========
API_FAILURE_THRESHOLD = 5  # セーフモード発動までのAPI失敗回数

# ========== 注文ステータス ==========
ORDER_SUCCESS_STATUSES = ['closed', 'filled']  # 注文成功とみなすステータス
ORDER_FINAL_STATUSES = ['closed', 'filled', 'canceled']  # 注文が確定したステータス
