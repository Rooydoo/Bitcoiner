"""タスクスケジューラー"""

from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime

scheduler = BlockingScheduler()

@scheduler.scheduled_job('cron', hour=7, minute=0)
def morning_report():
    print(f"[{datetime.now()}] 朝レポート生成")

@scheduler.scheduled_job('cron', hour=13, minute=0)
def noon_report():
    print(f"[{datetime.now()}] 昼レポート生成")

@scheduler.scheduled_job('cron', hour=22, minute=0)
def evening_report():
    print(f"[{datetime.now()}] 夜レポート生成")

if __name__ == "__main__":
    print("スケジューラー開始")
    scheduler.start()
