@echo off
REM Streamlit起動スクリプト（Windows用）

cd /d %~dp0
streamlit run ui/streamlit_app/app.py --server.port 8501
