"""リトライ機能 - API呼び出しの指数バックオフリトライ"""

import time
import logging
from typing import Callable, Any, Optional, Type, Tuple
from functools import wraps

logger = logging.getLogger(__name__)


def retry_with_backoff(
    max_retries: int = 4,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None
):
    """
    指数バックオフでリトライするデコレータ

    Args:
        max_retries: 最大リトライ回数（デフォルト: 4）
        base_delay: 初回待機時間（秒、デフォルト: 2.0）
        max_delay: 最大待機時間（秒、デフォルト: 60.0）
        exceptions: キャッチする例外タイプ
        on_retry: リトライ時に呼ぶコールバック関数

    使用例:
        @retry_with_backoff(max_retries=3, base_delay=1.0)
        def api_call():
            return requests.get('https://api.example.com')
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            retries = 0

            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)

                except exceptions as e:
                    retries += 1

                    if retries > max_retries:
                        logger.error(
                            f"{func.__name__}が{max_retries}回のリトライ後も失敗: {e}"
                        )
                        raise

                    # 指数バックオフ計算（2^n * base_delay）
                    delay = min(base_delay * (2 ** (retries - 1)), max_delay)

                    logger.warning(
                        f"{func.__name__}失敗 ({retries}/{max_retries}): {e}. "
                        f"{delay:.1f}秒後にリトライ..."
                    )

                    # リトライコールバック
                    if on_retry:
                        on_retry(e, retries)

                    time.sleep(delay)

            # 到達しないはずだが、念のため
            raise RuntimeError(f"{func.__name__}: 予期しないリトライループ終了")

        return wrapper
    return decorator


def retry_on_network_error(
    max_retries: int = 4,
    base_delay: float = 2.0,
    on_error_notify: Optional[Callable[[str], None]] = None
):
    """
    ネットワークエラー専用リトライデコレータ

    Args:
        max_retries: 最大リトライ回数
        base_delay: 初回待機時間
        on_error_notify: エラー通知関数（Telegram等）

    使用例:
        @retry_on_network_error(max_retries=3)
        def fetch_data():
            return ccxt.fetch_ohlcv()
    """
    import requests
    import ccxt

    network_exceptions = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.RequestException,
        ccxt.NetworkError,
        ccxt.RequestTimeout,
    )

    def on_retry_callback(error: Exception, retry_count: int):
        if on_error_notify and retry_count == 1:
            # 初回エラー時のみ通知（通知スパム防止）
            on_error_notify(f"ネットワークエラー発生（リトライ中）: {str(error)}")

    return retry_with_backoff(
        max_retries=max_retries,
        base_delay=base_delay,
        exceptions=network_exceptions,
        on_retry=on_retry_callback
    )


class RetryableError(Exception):
    """リトライ可能なエラー"""
    pass


class NonRetryableError(Exception):
    """リトライ不可能なエラー（即座に失敗）"""
    pass


# 使用例
if __name__ == "__main__":
    # テスト関数
    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def unstable_function():
        import random
        if random.random() < 0.7:
            raise ConnectionError("接続失敗")
        return "成功"

    try:
        result = unstable_function()
        print(f"結果: {result}")
    except Exception as e:
        print(f"最終的に失敗: {e}")
