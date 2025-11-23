"""共和分分析可視化ページ"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from data.storage.sqlite_manager import get_db_manager
from ml.models.cointegration_analyzer import CointegrationAnalyzer


def load_price_data(symbol: str, timeframe: str = '1h', limit: int = 500):
    """
    データベースから価格データを取得

    Args:
        symbol: 通貨ペア
        timeframe: 時間足
        limit: 取得件数

    Returns:
        価格データ（pandas Series）
    """
    db = get_db_manager()
    df = db.get_latest_ohlcv(symbol, timeframe, limit)

    if df.empty:
        return None

    # close価格のSeriesを返す（indexはtimestamp）
    prices = pd.Series(df['close'].values, index=pd.to_datetime(df['timestamp'], unit='s'))
    return prices


def plot_price_comparison(price1, price2, symbol1, symbol2, hedge_ratio):
    """
    2つの価格とヘッジ調整後の価格を比較するチャート

    Args:
        price1: 資産1の価格系列
        price2: 資産2の価格系列
        symbol1: 資産1のシンボル
        symbol2: 資産2のシンボル
        hedge_ratio: ヘッジ比率
    """
    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=(
            f'{symbol1} vs {symbol2} 価格推移',
            f'{symbol1} vs ヘッジ調整後{symbol2}'
        ),
        vertical_spacing=0.12,
        row_heights=[0.5, 0.5]
    )

    # 正規化（最初の値を100とする）
    price1_norm = (price1 / price1.iloc[0]) * 100
    price2_norm = (price2 / price2.iloc[0]) * 100

    # 上段：正規化された価格
    fig.add_trace(
        go.Scatter(
            x=price1_norm.index,
            y=price1_norm,
            name=symbol1,
            line=dict(color='blue', width=2)
        ),
        row=1, col=1
    )

    fig.add_trace(
        go.Scatter(
            x=price2_norm.index,
            y=price2_norm,
            name=symbol2,
            line=dict(color='orange', width=2)
        ),
        row=1, col=1
    )

    # 下段：資産1と調整後資産2
    price2_adjusted = price2 * hedge_ratio

    fig.add_trace(
        go.Scatter(
            x=price1.index,
            y=price1,
            name=symbol1,
            line=dict(color='blue', width=2)
        ),
        row=2, col=1
    )

    fig.add_trace(
        go.Scatter(
            x=price2_adjusted.index,
            y=price2_adjusted,
            name=f'{symbol2} × {hedge_ratio:.4f}',
            line=dict(color='orange', width=2, dash='dash')
        ),
        row=2, col=1
    )

    fig.update_xaxes(title_text="日時", row=2, col=1)
    fig.update_yaxes(title_text="正規化価格（開始=100）", row=1, col=1)
    fig.update_yaxes(title_text="価格", row=2, col=1)

    fig.update_layout(
        height=700,
        hovermode='x unified',
        showlegend=True,
        template='plotly_white'
    )

    return fig


def plot_spread(spread, symbol1, symbol2):
    """
    スプレッドのチャート

    Args:
        spread: スプレッド系列
        symbol1: 資産1のシンボル
        symbol2: 資産2のシンボル
    """
    fig = go.Figure()

    # スプレッド
    fig.add_trace(
        go.Scatter(
            x=spread.index,
            y=spread,
            name='スプレッド',
            line=dict(color='green', width=2),
            fill='tozeroy',
            fillcolor='rgba(0, 255, 0, 0.1)'
        )
    )

    # 平均線
    mean = spread.mean()
    fig.add_hline(
        y=mean,
        line_dash="dash",
        line_color="red",
        annotation_text=f"平均: {mean:.2f}"
    )

    # ゼロライン
    fig.add_hline(y=0, line_dash="dot", line_color="gray")

    fig.update_layout(
        title=f'スプレッド: {symbol1} - hedge_ratio × {symbol2}',
        xaxis_title='日時',
        yaxis_title='スプレッド',
        height=400,
        hovermode='x unified',
        template='plotly_white'
    )

    return fig


def plot_zscore(z_score, entry_threshold, exit_threshold, symbol1, symbol2):
    """
    Zスコアのチャートとエントリー/エグジットポイント

    Args:
        z_score: Zスコア系列
        entry_threshold: エントリー閾値
        exit_threshold: エグジット閾値
        symbol1: 資産1のシンボル
        symbol2: 資産2のシンボル
    """
    fig = go.Figure()

    # Zスコア
    fig.add_trace(
        go.Scatter(
            x=z_score.index,
            y=z_score,
            name='Zスコア',
            line=dict(color='purple', width=2)
        )
    )

    # エントリー閾値（上）
    fig.add_hline(
        y=entry_threshold,
        line_dash="dash",
        line_color="red",
        annotation_text=f"ショートシグナル: +{entry_threshold}"
    )

    # エントリー閾値（下）
    fig.add_hline(
        y=-entry_threshold,
        line_dash="dash",
        line_color="blue",
        annotation_text=f"ロングシグナル: -{entry_threshold}"
    )

    # エグジット閾値（上）
    fig.add_hline(
        y=exit_threshold,
        line_dash="dot",
        line_color="orange",
        annotation_text=f"エグジット: +{exit_threshold}"
    )

    # エグジット閾値（下）
    fig.add_hline(
        y=-exit_threshold,
        line_dash="dot",
        line_color="orange",
        annotation_text=f"エグジット: -{exit_threshold}"
    )

    # ゼロライン
    fig.add_hline(y=0, line_dash="solid", line_color="gray", line_width=1)

    # エントリーポイントをマーク
    long_signals = z_score[z_score < -entry_threshold]
    short_signals = z_score[z_score > entry_threshold]

    if not long_signals.empty:
        fig.add_trace(
            go.Scatter(
                x=long_signals.index,
                y=long_signals,
                mode='markers',
                name='ロングシグナル',
                marker=dict(color='blue', size=10, symbol='triangle-up')
            )
        )

    if not short_signals.empty:
        fig.add_trace(
            go.Scatter(
                x=short_signals.index,
                y=short_signals,
                mode='markers',
                name='ショートシグナル',
                marker=dict(color='red', size=10, symbol='triangle-down')
            )
        )

    fig.update_layout(
        title=f'Zスコア: {symbol1}/{symbol2} ペア',
        xaxis_title='日時',
        yaxis_title='Zスコア',
        height=500,
        hovermode='x unified',
        template='plotly_white'
    )

    return fig


def render_cointegration_page():
    """共和分分析ページのレンダリング"""
    st.header("📊 共和分分析 - ペアトレーディング可視化")

    st.markdown("""
    このページでは、2つの暗号資産ペアの共和分関係を分析し、
    スプレッド（価格乖離）とZスコアを可視化します。
    """)

    # サイドバー設定
    st.sidebar.subheader("⚙️ 分析設定")

    # 利用可能なシンボルを取得（仮）
    available_symbols = [
        'BTC_JPY', 'ETH_JPY', 'XRP_JPY', 'LTC_JPY',
        'BCH_JPY', 'MONA_JPY', 'XLM_JPY', 'LINK_JPY'
    ]

    symbol1 = st.sidebar.selectbox(
        "資産1を選択",
        available_symbols,
        index=0
    )

    symbol2 = st.sidebar.selectbox(
        "資産2を選択",
        available_symbols,
        index=1
    )

    timeframe = st.sidebar.selectbox(
        "時間足",
        ['1h', '4h', '1d'],
        index=0
    )

    lookback_period = st.sidebar.slider(
        "ルックバック期間（データポイント数）",
        min_value=50,
        max_value=1000,
        value=252,
        step=10
    )

    z_score_entry = st.sidebar.slider(
        "エントリーZスコア閾値",
        min_value=1.0,
        max_value=4.0,
        value=2.0,
        step=0.1
    )

    z_score_exit = st.sidebar.slider(
        "エグジットZスコア閾値",
        min_value=0.1,
        max_value=2.0,
        value=0.5,
        step=0.1
    )

    # 分析実行ボタン
    if st.sidebar.button("🔍 分析実行", type="primary"):
        if symbol1 == symbol2:
            st.error("異なるシンボルを選択してください")
            return

        with st.spinner("データを読み込み中..."):
            # 価格データを取得
            price1 = load_price_data(symbol1, timeframe, lookback_period)
            price2 = load_price_data(symbol2, timeframe, lookback_period)

            if price1 is None or price2 is None:
                st.error(f"データが見つかりません。データベースに {symbol1} または {symbol2} の価格データが存在するか確認してください。")
                return

            if len(price1) < 50 or len(price2) < 50:
                st.error("データポイント数が不足しています（最低50ポイント必要）")
                return

        with st.spinner("共和分検定を実行中..."):
            # 共和分分析
            analyzer = CointegrationAnalyzer(
                lookback_period=lookback_period,
                z_score_entry=z_score_entry,
                z_score_exit=z_score_exit
            )

            # 共和分検定
            coint_result = analyzer.test_cointegration(price1, price2, symbol1, symbol2)

            # 検定結果を表示
            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric(
                    "共和分関係",
                    "✅ あり" if coint_result.is_cointegrated else "❌ なし",
                    delta=None
                )

            with col2:
                st.metric(
                    "p値",
                    f"{coint_result.p_value:.4f}",
                    delta=f"{'有意' if coint_result.p_value < 0.05 else '非有意'}"
                )

            with col3:
                st.metric(
                    "ヘッジ比率",
                    f"{coint_result.hedge_ratio:.4f}",
                    delta=None
                )

            # 詳細情報
            with st.expander("📋 検定詳細"):
                st.write(f"**検定統計量**: {coint_result.test_statistic:.4f}")
                st.write(f"**半減期**: {coint_result.half_life:.1f} 期間")
                st.write("**臨界値**:")
                st.write(f"  - 1%: {coint_result.critical_values['1%']:.4f}")
                st.write(f"  - 5%: {coint_result.critical_values['5%']:.4f}")
                st.write(f"  - 10%: {coint_result.critical_values['10%']:.4f}")

        # スプレッドとZスコアを計算
        spread = analyzer.calculate_spread(price1, price2, coint_result.hedge_ratio)
        z_score = analyzer.calculate_z_score(spread, window=lookback_period)

        # 現在のシグナル
        signal = analyzer.generate_signal(price1, price2, coint_result.hedge_ratio)

        # シグナル表示
        st.subheader("🎯 現在のトレーディングシグナル")

        signal_col1, signal_col2, signal_col3 = st.columns(3)

        with signal_col1:
            signal_emoji = {
                'long_spread': '🟢 ロング',
                'short_spread': '🔴 ショート',
                'close': '⚪ クローズ',
                'hold': '⏸️ ホールド'
            }
            st.metric(
                "シグナル",
                signal_emoji.get(signal.signal, signal.signal),
                delta=None
            )

        with signal_col2:
            st.metric(
                "現在のスプレッド",
                f"{signal.spread:.2f}",
                delta=None
            )

        with signal_col3:
            # Zスコアの色分け
            z_color = "normal"
            if abs(signal.z_score) > z_score_entry:
                z_color = "inverse"

            st.metric(
                "現在のZスコア",
                f"{signal.z_score:.2f}",
                delta=f"{'エントリー範囲' if abs(signal.z_score) > z_score_entry else '正常範囲'}"
            )

        # チャート表示
        st.subheader("📈 価格比較チャート")
        fig1 = plot_price_comparison(price1, price2, symbol1, symbol2, coint_result.hedge_ratio)
        st.plotly_chart(fig1, use_container_width=True)

        st.subheader("📉 スプレッドチャート")
        fig2 = plot_spread(spread, symbol1, symbol2)
        st.plotly_chart(fig2, use_container_width=True)

        st.subheader("📊 Zスコアとトレーディングシグナル")
        fig3 = plot_zscore(z_score, z_score_entry, z_score_exit, symbol1, symbol2)
        st.plotly_chart(fig3, use_container_width=True)

        # 統計情報
        st.subheader("📊 統計情報")
        stats_col1, stats_col2 = st.columns(2)

        with stats_col1:
            st.write("**スプレッド統計**")
            st.write(f"平均: {spread.mean():.2f}")
            st.write(f"標準偏差: {spread.std():.2f}")
            st.write(f"最小値: {spread.min():.2f}")
            st.write(f"最大値: {spread.max():.2f}")

        with stats_col2:
            st.write("**Zスコア統計**")
            st.write(f"平均: {z_score.mean():.2f}")
            st.write(f"標準偏差: {z_score.std():.2f}")
            st.write(f"最小値: {z_score.min():.2f}")
            st.write(f"最大値: {z_score.max():.2f}")

    else:
        st.info("👈 左側のサイドバーからペアを選択し、「分析実行」ボタンをクリックしてください")


if __name__ == "__main__":
    render_cointegration_page()
