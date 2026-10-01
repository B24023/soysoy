import streamlit as st
import pandas as pd
from geocode import geocode_address, geocode_dataframe
import utils

def render():
    st.header("新規利用者登録")
    with st.form("add_user_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            u_name = st.text_input("氏名 *")
            u_care = st.selectbox("要介護度", ["要支援1", "要支援2", "要介護1", "要介護2", "要介護3", "要介護4", "要介護5"])
        with c2:
            u_wheel = st.selectbox("車椅子利用", ["なし", "あり"])
            u_pre_call = st.selectbox("事前連絡（到着前）", ["なし", "あり"])
        with c3:
            u_days = st.multiselect("利用曜日", ["月", "火", "水", "木", "金", "土", "日"], default=["月", "水", "金"])
        
        u_address = st.text_input("住所 *")
        
        if st.form_submit_button("登録する", type="primary"):
            if u_name and u_address:
                geo_res = geocode_address(u_address)
                u_lat = geo_res["lat"] if geo_res else 34.815
                u_lng = geo_res["lng"] if geo_res else 135.652
                
                max_id = int(st.session_state.users_df["id"].astype(float).max()) if not st.session_state.users_df.empty else 0
                new_row = pd.DataFrame([{
                    "id": max_id + 1, "name": u_name, "lat": u_lat, "lng": u_lng, 
                    "address": u_address, "care_level": u_care, "wheelchair": u_wheel, 
                    "pre_call": u_pre_call, "days": ",".join(u_days)
                }])
                st.session_state.users_df = pd.concat([st.session_state.users_df, new_row], ignore_index=True)
                st.session_state.users_df.to_csv(utils.USERS_CSV, index=False, encoding="utf-8-sig")
                st.success(f"{u_name} さんを登録しました。")
                st.rerun() # 画面をリロードしてリストを更新
            else:
                st.error("必須項目を入力してください。")

    st.divider()

    # --- 新規追加：利用者の個別削除機能 ---
    st.subheader("🗑️ 利用者の削除")
    # 施設（ID:0）は削除リストから除外する
    deletable_users = st.session_state.users_df[st.session_state.users_df["id"].astype(float) != 0.0]
    
    if not deletable_users.empty:
        col1, col2 = st.columns([3, 1])
        with col1:
            user_to_delete = st.selectbox(
                "削除する利用者を選択してください",
                deletable_users.apply(lambda r: f"ID:{int(float(r['id']))} {r['name']}", axis=1).tolist()
            )
        with col2:
            st.write("") # 高さ合わせ
            st.write("")
            if st.button("この利用者を削除", type="primary"):
                # 選択された文字列からIDを抽出して削除
                del_id = int(user_to_delete.split(" ")[0].replace("ID:", ""))
                st.session_state.users_df = st.session_state.users_df[st.session_state.users_df["id"].astype(float) != del_id]
                st.session_state.users_df.to_csv(utils.USERS_CSV, index=False, encoding="utf-8-sig")
                st.success(f"利用者を削除しました。")
                st.rerun() # 画面をリロード
    else:
        st.info("削除できる利用者がいません。")

    st.divider()

    st.subheader("利用者一覧 (データ元: data/users.csv)")
    st.info("※ 表の左端をクリックして行を選択し、キーボードの「Delete」キーを押すことでも直接まとめて削除できます。")
    
    # num_rows="dynamic" を追加し、表からの直接削除・行追加を許可
    edited_df = st.data_editor(st.session_state.users_df, num_rows="dynamic", hide_index=True, use_container_width=True)
    
    if st.button("利用者データを保存"):
        # 安全装置：表からの直接削除で誤って施設(ID:0)を消してしまった場合の復元処理
        if 0.0 not in edited_df["id"].astype(float).values:
            st.warning("施設（デポ）は削除できないため、自動復元しました。")
            depot_row = pd.DataFrame([{
                "id": 0, "name": "施設（デポ）", "lat": 34.8151, "lng": 135.6525, 
                "address": "大阪府枚方市山之上北町", "care_level": "-", "wheelchair": "なし", 
                "pre_call": "なし", "days": "月,火,水,木,金,土,日"
            }])
            edited_df = pd.concat([depot_row, edited_df], ignore_index=True)

        st.session_state.users_df = edited_df
        st.session_state.users_df.to_csv(utils.USERS_CSV, index=False, encoding="utf-8-sig")
        st.success("保存しました。")
        st.rerun()