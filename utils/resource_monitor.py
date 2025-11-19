"""システムリソース監視モジュール"""

import psutil
import logging
from typing import Dict
from datetime import datetime
import os

logger = logging.getLogger(__name__)


class ResourceMonitor:
    """システムリソースを監視するクラス"""

    def __init__(self):
        """初期化"""
        self.process = psutil.Process(os.getpid())
        logger.info("リソース監視初期化")

    def get_cpu_usage(self) -> float:
        """
        CPU使用率を取得

        Returns:
            CPU使用率（%）
        """
        try:
            # プロセス単位のCPU使用率
            cpu_percent = self.process.cpu_percent(interval=1.0)
            return round(cpu_percent, 2)
        except Exception as e:
            logger.error(f"CPU使用率取得エラー: {e}")
            return 0.0

    def get_memory_usage(self) -> Dict[str, float]:
        """
        メモリ使用量を取得

        Returns:
            メモリ情報の辞書
        """
        try:
            # プロセス単位のメモリ使用量
            mem_info = self.process.memory_info()
            mem_percent = self.process.memory_percent()

            # システム全体のメモリ情報
            system_mem = psutil.virtual_memory()

            return {
                'process_mb': round(mem_info.rss / (1024 * 1024), 2),  # プロセスのメモリ（MB）
                'process_percent': round(mem_percent, 2),  # プロセスのメモリ使用率（%）
                'system_total_mb': round(system_mem.total / (1024 * 1024), 2),  # システム総メモリ
                'system_used_mb': round(system_mem.used / (1024 * 1024), 2),  # システム使用量
                'system_percent': round(system_mem.percent, 2)  # システム使用率（%）
            }
        except Exception as e:
            logger.error(f"メモリ使用量取得エラー: {e}")
            return {}

    def get_disk_usage(self, path: str = '/') -> Dict[str, float]:
        """
        ディスク使用量を取得

        Args:
            path: 確認するパス

        Returns:
            ディスク情報の辞書
        """
        try:
            disk = psutil.disk_usage(path)

            return {
                'total_gb': round(disk.total / (1024**3), 2),
                'used_gb': round(disk.used / (1024**3), 2),
                'free_gb': round(disk.free / (1024**3), 2),
                'percent': round(disk.percent, 2)
            }
        except Exception as e:
            logger.error(f"ディスク使用量取得エラー: {e}")
            return {}

    def get_network_io(self) -> Dict[str, float]:
        """
        ネットワークI/O統計を取得

        Returns:
            ネットワーク情報の辞書
        """
        try:
            net_io = psutil.net_io_counters()

            return {
                'bytes_sent_mb': round(net_io.bytes_sent / (1024 * 1024), 2),
                'bytes_recv_mb': round(net_io.bytes_recv / (1024 * 1024), 2),
                'packets_sent': net_io.packets_sent,
                'packets_recv': net_io.packets_recv
            }
        except Exception as e:
            logger.error(f"ネットワークI/O取得エラー: {e}")
            return {}

    def get_all_metrics(self) -> Dict[str, any]:
        """
        全てのリソースメトリクスを取得

        Returns:
            全メトリクスの辞書
        """
        metrics = {
            'timestamp': datetime.now().isoformat(),
            'cpu': self.get_cpu_usage(),
            'memory': self.get_memory_usage(),
            'disk': self.get_disk_usage(),
            'network': self.get_network_io()
        }

        return metrics

    def check_resource_limits(
        self,
        cpu_threshold: float = 80.0,
        memory_threshold: float = 80.0,
        disk_threshold: float = 90.0
    ) -> Dict[str, bool]:
        """
        リソース制限をチェック

        Args:
            cpu_threshold: CPU使用率の閾値（%）
            memory_threshold: メモリ使用率の閾値（%）
            disk_threshold: ディスク使用率の閾値（%）

        Returns:
            各リソースが閾値を超えているかの辞書
        """
        cpu = self.get_cpu_usage()
        mem = self.get_memory_usage()
        disk = self.get_disk_usage()

        warnings = {
            'cpu_warning': cpu > cpu_threshold,
            'memory_warning': mem.get('system_percent', 0) > memory_threshold,
            'disk_warning': disk.get('percent', 0) > disk_threshold
        }

        # 警告をログ出力
        if warnings['cpu_warning']:
            logger.warning(f"CPU使用率が閾値を超えています: {cpu}% > {cpu_threshold}%")

        if warnings['memory_warning']:
            logger.warning(f"メモリ使用率が閾値を超えています: {mem.get('system_percent')}% > {memory_threshold}%")

        if warnings['disk_warning']:
            logger.warning(f"ディスク使用率が閾値を超えています: {disk.get('percent')}% > {disk_threshold}%")

        return warnings

    def log_current_status(self):
        """現在のリソース状態をログ出力"""
        metrics = self.get_all_metrics()

        logger.info("=" * 60)
        logger.info("システムリソース状態")
        logger.info("=" * 60)
        logger.info(f"CPU使用率: {metrics['cpu']}%")
        logger.info(f"メモリ使用量: {metrics['memory'].get('process_mb')} MB ({metrics['memory'].get('process_percent')}%)")
        logger.info(f"システムメモリ: {metrics['memory'].get('system_used_mb')} / {metrics['memory'].get('system_total_mb')} MB ({metrics['memory'].get('system_percent')}%)")
        logger.info(f"ディスク使用量: {metrics['disk'].get('used_gb')} / {metrics['disk'].get('total_gb')} GB ({metrics['disk'].get('percent')}%)")
        logger.info("=" * 60)

    def is_healthy(
        self,
        cpu_threshold: float = 80.0,
        memory_threshold: float = 80.0,
        disk_threshold: float = 90.0
    ) -> bool:
        """
        システムが健全かチェック

        Args:
            cpu_threshold: CPU閾値
            memory_threshold: メモリ閾値
            disk_threshold: ディスク閾値

        Returns:
            健全な場合True
        """
        warnings = self.check_resource_limits(cpu_threshold, memory_threshold, disk_threshold)
        return not any(warnings.values())


# シングルトンインスタンス
_monitor = None


def get_resource_monitor() -> ResourceMonitor:
    """
    リソースモニターのシングルトンインスタンスを取得

    Returns:
        ResourceMonitorインスタンス
    """
    global _monitor
    if _monitor is None:
        _monitor = ResourceMonitor()
    return _monitor


# ユーティリティ関数
def log_resource_status():
    """現在のリソース状態をログ出力（ショートカット）"""
    monitor = get_resource_monitor()
    monitor.log_current_status()


def check_memory_usage() -> float:
    """現在のメモリ使用率を取得（ショートカット）"""
    monitor = get_resource_monitor()
    mem = monitor.get_memory_usage()
    return mem.get('process_percent', 0.0)
