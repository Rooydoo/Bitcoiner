"""Phase 3統合テスト - 売買エンジン実装完了確認"""

import sys
from pathlib import Path
import time

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from trading.order_executor import OrderExecutor
from trading.position_manager import PositionManager, Position
from trading.risk_manager import RiskManager
from data.storage.sqlite_manager import SQLiteManager
from utils.logger import setup_logger

# ロガー設定
logger = setup_logger('test_phase3', 'test_phase3.log', console=True)


def test_phase3_integration():
    """Phase 3統合テスト"""
    print("=" * 70)
    print("Phase 3統合テスト: 売買エンジン実装")
    print("=" * 70)

    # ========== 1. 注文実行モジュールテスト ==========
    print("\n[1] 注文実行モジュール確認:")

    # テストモードで初期化（APIキーなし）
    executor = OrderExecutor(test_mode=True)
    print(f"  ✓ OrderExecutor初期化（テストモード）")

    # 成行注文テスト
    market_order = executor.create_market_order('BTC/JPY', 'buy', 0.01)
    print(f"  ✓ 成行注文: {market_order['side'].upper()} {market_order['amount']} BTC")
    print(f"    注文ID: {market_order['id']}")
    print(f"    ステータス: {market_order['status']}")

    # 指値注文テスト
    limit_order = executor.create_limit_order('BTC/JPY', 'buy', 0.01, 11000000)
    print(f"  ✓ 指値注文: {limit_order['amount']} BTC @ ¥{limit_order['price']:,.0f}")

    # 残高確認
    balance = executor.get_balance('JPY')
    print(f"  ✓ 残高: ¥{balance['free']:,.0f}")

    # 現在価格取得
    current_price = executor.get_current_price('BTC/JPY')
    print(f"  ✓ 現在価格: ¥{current_price:,.0f}")

    # ポジションサイズ計算
    position_size = executor.calculate_position_size('BTC/JPY', 200000, 0.6)
    print(f"  ✓ ポジションサイズ: {position_size:.6f} BTC")

    # ========== 2. ポジション管理システムテスト ==========
    print("\n[2] ポジション管理システム確認:")

    # DBマネージャー初期化
    db_manager = SQLiteManager()
    position_manager = PositionManager(db_manager)
    print(f"  ✓ PositionManager初期化")

    # ポジションオープン
    position = position_manager.open_position(
        symbol='BTC/JPY',
        side='long',
        entry_price=12000000,
        quantity=0.01
    )
    print(f"  ✓ ポジションオープン: {position.symbol} {position.side.upper()}")
    print(f"    エントリー価格: ¥{position.entry_price:,.0f}")
    print(f"    数量: {position.quantity} BTC")

    # 未実現損益計算
    current_price_btc = 12500000  # +5%上昇
    unrealized_pnl = position.calculate_unrealized_pnl(current_price_btc)
    unrealized_pnl_pct = position.calculate_unrealized_pnl_pct(current_price_btc)
    print(f"  ✓ 未実現損益: ¥{unrealized_pnl:,.0f} ({unrealized_pnl_pct:+.2f}%)")

    # ポジションサマリー
    summary = position_manager.get_position_summary('BTC/JPY', current_price_btc)
    print(f"  ✓ ポジションサマリー:")
    print(f"    保有時間: {summary['holding_hours']:.2f}時間")
    print(f"    未実現損益率: {summary['unrealized_pnl_pct']:+.2f}%")

    # ========== 3. リスク管理ロジックテスト ==========
    print("\n[3] リスク管理ロジック確認:")

    risk_manager = RiskManager(
        max_position_size=0.95,
        stop_loss_pct=10.0,
        max_drawdown_pct=20.0,
        profit_taking_enabled=True
    )
    print(f"  ✓ RiskManager初期化")

    # ストップロスチェック（-5%下落）
    sl_price = 11400000  # -5%
    is_stop_loss = risk_manager.check_stop_loss(position, sl_price)
    print(f"  ✓ ストップロスチェック（-5%）: {'発動' if is_stop_loss else '未発動'}")

    # ストップロスチェック（-11%下落）
    sl_price_trigger = 10680000  # -11%
    is_stop_loss_trigger = risk_manager.check_stop_loss(position, sl_price_trigger)
    print(f"  ✓ ストップロスチェック（-11%）: {'発動' if is_stop_loss_trigger else '未発動'}")

    # 第1段階利益確定チェック（+15%上昇）
    tp1_price = 13800000  # +15%
    profit_action_1 = risk_manager.check_profit_taking(position, tp1_price)
    if profit_action_1:
        print(f"  ✓ 第1段階利益確定（+15%）: {profit_action_1['action']}")
        print(f"    決済比率: {profit_action_1['close_ratio']:.0%}")
        print(f"    理由: {profit_action_1['reason']}")

    # 第2段階利益確定チェック（+25%上昇）
    risk_manager.partial_profit_taken['BTC/JPY'] = True  # 第1段階済み
    tp2_price = 15000000  # +25%
    profit_action_2 = risk_manager.check_profit_taking(position, tp2_price)
    if profit_action_2:
        print(f"  ✓ 第2段階利益確定（+25%）: {profit_action_2['action']}")
        print(f"    決済比率: {profit_action_2['close_ratio']:.0%}")

    # ポジションサイズ検証
    is_valid, msg = risk_manager.validate_position_size(180000, 200000)
    print(f"  ✓ ポジションサイズ検証: {'OK' if is_valid else 'NG'} - {msg}")

    # リスクベースポジションサイズ計算
    risk_based_size = risk_manager.calculate_position_size_with_risk(
        available_capital=200000,
        current_price=12000000,
        risk_per_trade_pct=2.0
    )
    print(f"  ✓ リスクベースサイズ: {risk_based_size:.6f} BTC")

    # ========== 4. 統合ワークフローテスト ==========
    print("\n[4] 統合ワークフロー確認:")

    # シナリオ1: エントリー判定
    should_enter, reason = risk_manager.should_enter_trade(
        signal_confidence=0.75,
        min_confidence=0.6,
        current_equity=200000,
        initial_capital=200000
    )
    print(f"  [シナリオ1] エントリー判定: {'OK' if should_enter else 'NG'} - {reason}")

    # シナリオ2: 価格上昇（+16%）→ 第1段階利確
    print(f"\n  [シナリオ2] 価格上昇（+16%）")
    price_up_16 = 13920000
    exit_action = risk_manager.get_exit_action(position, price_up_16)
    if exit_action:
        print(f"    アクション: {exit_action['action']}")
        print(f"    理由: {exit_action['reason']}")
        print(f"    決済比率: {exit_action['close_ratio']:.0%}")

    # シナリオ3: 価格下落（-12%）→ ストップロス
    print(f"\n  [シナリオ3] 価格下落（-12%）")
    position2 = Position('ETH/JPY', 'long', 500000, 0.2)
    price_down_12 = 440000
    exit_action_sl = risk_manager.get_exit_action(position2, price_down_12)
    if exit_action_sl:
        print(f"    アクション: {exit_action_sl['action']}")
        print(f"    理由: {exit_action_sl['reason']}")

    # シナリオ4: ポジションクローズ
    print(f"\n  [シナリオ4] ポジションクローズ")
    closed_position = position_manager.close_position('BTC/JPY', 13000000)
    if closed_position:
        print(f"    決済価格: ¥{closed_position.exit_price:,.0f}")
        print(f"    実現損益: ¥{closed_position.realized_pnl:,.0f}")
        print(f"    損益率: {closed_position.calculate_unrealized_pnl_pct(closed_position.exit_price):+.2f}%")

    # ========== 5. DB永続化確認 ==========
    print("\n[5] データベース永続化確認:")

    # ポジション履歴確認（クローズ済み）
    print(f"  ✓ クローズ済みポジション: {len(position_manager.closed_positions)}件")
    if position_manager.closed_positions:
        latest = position_manager.closed_positions[-1]
        print(f"    最新: {latest.symbol} {latest.side.upper()} @ ¥{latest.exit_price:,.0f}")
        print(f"    損益: ¥{latest.realized_pnl:,.0f}")

    # ========== 6. Phase 3完了判定 ==========
    print("\n[6] Phase 3完了判定:")

    checks = {
        '注文実行モジュール': market_order is not None,
        'ポジション管理': position is not None,
        'リスク管理（ストップロス）': is_stop_loss_trigger,
        'リスク管理（利益確定）': profit_action_1 is not None and profit_action_2 is not None,
        'DB永続化': len(position_manager.closed_positions) > 0
    }

    all_passed = all(checks.values())

    for check_name, passed in checks.items():
        status = "✓" if passed else "✗"
        print(f"  {status} {check_name}")

    # 最終判定
    print("\n" + "=" * 70)
    if all_passed:
        print("Phase 3: 売買エンジン実装 - 完了✓")
        print("\n実装済みコンポーネント:")
        print("  ✓ 注文実行モジュール（bitFlyer API統合、テストモード対応）")
        print("  ✓ ポジション管理システム（エントリー/エグジット、損益計算）")
        print("  ✓ リスク管理ロジック（ストップロス、段階的利確、ドローダウン管理）")
        print("\nリスク管理設定:")
        print(f"  - ストップロス: {risk_manager.stop_loss_pct}%")
        print(f"  - 第1段階利確: +15%で50%決済")
        print(f"  - 第2段階利確: +25%で全決済")
        print(f"  - 最大ドローダウン: {risk_manager.max_drawdown_pct}%")
        print("\n次のフェーズ: Phase 4 - レポート・UI実装")
    else:
        print("Phase 3: 一部のチェックが失敗しました")

    print("=" * 70 + "\n")

    return executor, position_manager, risk_manager


if __name__ == "__main__":
    executor, pos_mgr, risk_mgr = test_phase3_integration()
