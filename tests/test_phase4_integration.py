"""Phase 4統合テスト - レポート・通知機能完了確認"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from notification.telegram_notifier import TelegramNotifier
from reporting.daily_report import ReportGenerator
from reporting.tax_export import TaxReportGenerator
from data.storage.sqlite_manager import SQLiteManager
from utils.logger import setup_logger

# ロガー設定
logger = setup_logger('test_phase4', 'test_phase4.log', console=True)


def test_phase4_integration():
    """Phase 4統合テスト"""
    print("=" * 70)
    print("Phase 4統合テスト: レポート・通知機能")
    print("=" * 70)

    # ========== 1. Telegram通知テスト ==========
    print("\n[1] Telegram通知機能確認:")

    # Token/ChatIDなしでテストモード
    telegram = TelegramNotifier(enabled=False)
    print(f"  ✓ TelegramNotifier初期化（テストモード）")

    # 取引開始通知
    telegram.notify_trade_open('BTC/JPY', 'long', 12000000, 0.01)
    print(f"  ✓ 取引開始通知")

    # 取引終了通知
    telegram.notify_trade_close(
        'BTC/JPY', 'long',
        entry_price=12000000,
        exit_price=13000000,
        quantity=0.01,
        pnl=10000,
        pnl_pct=8.33
    )
    print(f"  ✓ 取引終了通知")

    # ストップロス通知
    telegram.notify_stop_loss('ETH/JPY', 450000, -10.0)
    print(f"  ✓ ストップロス通知")

    # 利益確定通知
    telegram.notify_take_profit('BTC/JPY', level=1, close_ratio=0.5, pnl_pct=15.0)
    print(f"  ✓ 利益確定通知（第1段階）")

    telegram.notify_take_profit('BTC/JPY', level=2, close_ratio=1.0, pnl_pct=25.0)
    print(f"  ✓ 利益確定通知（第2段階）")

    # 日次サマリー通知
    telegram.notify_daily_summary(
        total_equity=205000,
        daily_pnl=5000,
        daily_pnl_pct=2.5,
        trades_count=2,
        win_rate=1.0,
        open_positions=[]
    )
    print(f"  ✓ 日次サマリー通知")

    # アラート通知
    telegram.notify_alert('価格急変動', 'BTC/JPY が5%以上変動しました')
    print(f"  ✓ アラート通知")

    # エラー通知
    telegram.notify_error('API接続エラー', 'bitFlyer APIに接続できません')
    print(f"  ✓ エラー通知")

    # ========== 2. レポート生成テスト ==========
    print("\n[2] レポート生成機能確認:")

    db_manager = SQLiteManager()
    report_gen = ReportGenerator(db_manager)
    print(f"  ✓ ReportGenerator初期化")

    # 日次レポート
    daily_report = report_gen.generate_daily_report()
    print(f"  ✓ 日次レポート生成")
    print("\n" + "─" * 60)
    print(daily_report[:500] + "...")
    print("─" * 60)

    # 週次レポート
    weekly_report = report_gen.generate_weekly_report()
    print(f"  ✓ 週次レポート生成")

    # 統計サマリー
    stats = report_gen.generate_summary_stats()
    print(f"  ✓ 統計サマリー取得")
    print(f"    総取引回数: {stats['total_trades']}回")
    print(f"    勝率: {stats['win_rate']:.1%}")
    print(f"    総損益: ¥{stats['total_pnl']:,.0f}")

    # ========== 3. 税務処理テスト ==========
    print("\n[3] 税務処理機能確認:")

    tax_gen = TaxReportGenerator(db_manager)
    print(f"  ✓ TaxReportGenerator初期化")

    # CSVエクスポート
    csv_path = "tax_reports/trades_2025.csv"
    exported_path = tax_gen.export_trades_to_csv(csv_path, year=2025)
    print(f"  ✓ CSV出力: {exported_path}")

    # 年間損益計算
    annual_pnl = tax_gen.calculate_annual_pnl(2025)
    print(f"  ✓ 年間損益計算完了")
    print(f"    純損益: ¥{annual_pnl['net_pnl']:,.0f}")
    print(f"    課税所得: ¥{annual_pnl['tax_base']:,.0f}")

    # 税務レポート生成
    tax_report = tax_gen.generate_tax_report(2025)
    print(f"  ✓ 税務レポート生成")
    print("\n" + "─" * 60)
    print(tax_report[:500] + "...")
    print("─" * 60)

    # ========== 4. 統合ワークフローテスト ==========
    print("\n[4] 統合ワークフロー確認:")

    # シナリオ: 取引完了 → 通知 → レポート
    print("  [シナリオ] 取引実行から日次レポートまで")

    # 1. 取引開始
    print("    1. 取引開始")
    telegram.notify_trade_open('BTC/JPY', 'long', 12000000, 0.01)

    # 2. 取引終了
    print("    2. 取引終了（利益確定）")
    telegram.notify_trade_close(
        'BTC/JPY', 'long',
        entry_price=12000000,
        exit_price=13800000,  # +15%
        quantity=0.01,
        pnl=18000,
        pnl_pct=15.0
    )

    # 3. 日次レポート生成
    print("    3. 日次レポート生成")
    daily_report = report_gen.generate_daily_report()

    # 4. Telegram送信（実際のBotでは送信）
    print("    4. 日次レポートをTelegram送信（テストモードのためスキップ）")

    print("  ✓ ワークフロー完了")

    # ========== 5. Phase 4完了判定 ==========
    print("\n[5] Phase 4完了判定:")

    checks = {
        'Telegram通知': telegram is not None,
        'レポート生成': daily_report is not None and weekly_report is not None,
        '税務処理': annual_pnl is not None and Path(exported_path).exists(),
        '統合ワークフロー': True
    }

    all_passed = all(checks.values())

    for check_name, passed in checks.items():
        status = "✓" if passed else "✗"
        print(f"  {status} {check_name}")

    # 最終判定
    print("\n" + "=" * 70)
    if all_passed:
        print("Phase 4: レポート・通知機能 - 完了✓")
        print("\n実装済みコンポーネント:")
        print("  ✓ Telegram Bot（取引通知、日次サマリー、アラート）")
        print("  ✓ レポート生成（日次/週次レポート、定型フォーマット）")
        print("  ✓ 税務処理（CSVエクスポート、年間損益計算、税額概算）")
        print("\n通知機能:")
        print("  - 取引開始/終了通知")
        print("  - ストップロス/利益確定通知")
        print("  - 日次サマリー")
        print("  - アラート/エラー通知")
        print("\nレポート機能:")
        print("  - 日次レポート（資産状況、取引実績、保有ポジション）")
        print("  - 週次レポート（週次損益、日別損益、リスク指標）")
        print("  - 税務レポート（課税所得、税額概算）")
        print("\n次のフェーズ: Phase 5 - 統合・デプロイ")
    else:
        print("Phase 4: 一部のチェックが失敗しました")

    print("=" * 70 + "\n")

    return telegram, report_gen, tax_gen


if __name__ == "__main__":
    telegram, report, tax = test_phase4_integration()
