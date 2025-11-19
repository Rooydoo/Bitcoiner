#!/bin/bash
# Streamlit起動スクリプト

cd "$(dirname "$0")"
streamlit run ui/streamlit_app/app.py --server.port 8501 --server.address 0.0.0.0
