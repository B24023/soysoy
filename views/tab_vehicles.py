import streamlit as st
import pandas as pd
import utils

def render():
    st.header("新規車両登録")
    st.info("※ 現場のルールに基づき、全車両の定員は「3名」に固定されています。ドライバーは当日ランダム配置です。")
    with st.form("add_vehicle_form"):
        c1, c2 = st.columns(2)
        with c1:
            v_name = st.text_input("車両名 *", placeholder="例：ラクティス")
        with c2:
            v_wheel = st.selectbox("車椅子対応", ["あり", "なし"])
            
        if st.form_submit_button("車両を登録する", type="primary"):
            if v_name:
                max_v_id = int(st.session_state.vehicles_df["id"].astype(float).max()) if not st.session_state.vehicles_df.empty else 0
                new_row = pd.DataFrame([{
                    "id": max_v_id + 1, 
                    "name": v_name, 
                    "wheelchair_support": v_wheel
                }])
                st.session_state.vehicles_df = pd.concat([st.session_state.vehicles_df, new_row], ignore_index=True)
                st.session_state.vehicles_df.to_csv(utils.VEHICLES_CSV, index=False, encoding="utf-8-sig")
                st.success(f"「{v_name}」を登録しました。")
            else:
                st.error("車両名を入力してください。")

    st.divider()
    st.subheader("登録済み車両一覧")
    edited_vehicles_df = st.data_editor(
        st.session_state.vehicles_df, num_rows="dynamic", hide_index=True, use_container_width=True
    )
    if st.button("編集内容を保存する", key="save_vehicles"):
        st.session_state.vehicles_df = edited_vehicles_df
        st.session_state.vehicles_df.to_csv(utils.VEHICLES_CSV, index=False, encoding="utf-8-sig")
        st.success("変更内容を保存しました。")