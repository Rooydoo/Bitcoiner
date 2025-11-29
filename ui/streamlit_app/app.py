"""Streamlit メインアプリケーション"""

import streamlit as st
import os
import hashlib

st.set_page_config(
    page_title="CryptoTrader Dashboard",
    page_icon="📊",
    layout="wide"
)

# 認証機能
def check_password():
    """パスワード認証を実施"""

    # セッション状態の初期化
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    # 既に認証済みの場合
    if st.session_state.authenticated:
        return True

    # 環境変数から認証情報を取得
    correct_username = os.getenv('STREAMLIT_USERNAME', 'admin')
    correct_password = os.getenv('STREAMLIT_PASSWORD', 'admin')

    # ログインフォーム
    st.title("🔐 CryptoTrader ログイン")

    with st.form("login_form"):
        username = st.text_input("ユーザー名")
        password = st.text_input("パスワード", type="password")
        submit = st.form_submit_button("ログイン")

        if submit:
            if username == correct_username and password == correct_password:
                st.session_state.authenticated = True
                st.success("✅ ログイン成功！")
                st.rerun()
            else:
                st.error("❌ ユーザー名またはパスワードが間違っています")

    return False

# 認証チェック
if not check_password():
    st.stop()

# ログアウトボタン（サイドバー）
if st.sidebar.button("ログアウト"):
    st.session_state.authenticated = False
    st.rerun()

st.title("🚀 CryptoTrader Dashboard")
st.write("暗号資産自動売買システム")

# サイドバー
st.sidebar.title("ナビゲーション")
page = st.sidebar.radio("ページ選択",
    ["ダッシュボード", "共和分分析", "レポート", "Telegram", "設定", "システム"])

if page == "ダッシュボード":
    st.header("📈 ダッシュボード")
    st.info("実装予定: ポジション一覧、損益グラフ、リスク指標")

elif page == "共和分分析":
    from pages.cointegration_analysis import render_cointegration_page
    render_cointegration_page()

elif page == "レポート":
    st.header("📄 レポート閲覧")
    st.info("実装予定: 朝・昼・夜レポート、月次レポート")

elif page == "Telegram":
    st.header("💬 Telegramメッセージ")
    st.info("実装予定: メッセージ履歴、フィルター機能")

elif page == "設定":
    st.header("⚙️ 設定・操作")
    st.info("実装予定: リスクパラメータ調整、緊急停止")

elif page == "システム":
    st.header("🖥️ システム監視")
    st.info("実装予定: CPU/メモリ使用率、エラーログ")
