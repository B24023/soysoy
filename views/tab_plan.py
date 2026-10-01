import streamlit as st
import pandas as pd
import datetime
from optimizer import run_optimization
import utils

def render():
    st.header("送迎計画の作成")
    
    col_filter, _ = st.columns([1, 3])
    with col_filter:
        selected_day = st.selectbox("曜日表示フィルター", ["すべて", "月", "火", "水", "木", "金", "土", "日"])
    
    df = st.session_state.users_df
    display_df = df[df["id"].astype(float) != 0.0].copy() if not df.empty else df.copy()
    if selected_day != "すべて" and not display_df.empty:
        display_df = display_df[display_df["days"].astype(str).str.contains(selected_day, na=False)]
    
    if not display_df.empty:
        display_df.insert(0, "出席", True)
    else:
        display_df = pd.DataFrame(columns=["出席", "id", "name", "care_level", "address", "days"])
    
    st.write("**送迎対象者の選択**")
    edited_plan_df = st.data_editor(
        display_df[["出席", "id", "name", "care_level", "address", "days"]],
        hide_index=True,
        use_container_width=True,
        disabled=["id", "name", "care_level", "address", "days"]
    )
    
    with st.expander("詳細設定（車両数・時間制限・通行止め）"):
        col1, col2, col3 = st.columns(3)
        with col1:
            n_vehicles = st.number_input("利用車両数", min_value=1, max_value=5, value=2)
        with col2:
            arrival_time = st.time_input("施設到着時刻", datetime.time(9, 0))
        with col3:
            max_ride_time = st.number_input("最大乗車時間（分）", value=60)
            
    if st.button("AIで最適ルートを自動作成する", type="primary", use_container_width=True):
        if edited_plan_df.empty or not edited_plan_df["出席"].any():
            st.error("エラー: 出席予定の利用者がいません。")
        else:
            selected_ids = [int(float(x)) for x in edited_plan_df[edited_plan_df["出席"]]["id"].tolist()]
            with st.spinner("最適ルートを計算中..."):
                try:
                    optimized_rows = run_optimization(selected_ids, int(n_vehicles))
                    utils.update_route_data(optimized_rows, int(n_vehicles))
                    st.session_state.optimization_done = True
                    st.success("最適化が完了しました。「最適化結果」タブを確認してください。")
                except Exception as e:
                    st.error(f"最適化エラー: {e}")