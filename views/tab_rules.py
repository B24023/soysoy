import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import os
import ast
import utils

RULES_CSV = os.path.join(utils.DATA_DIR, "traffic_rules.csv")

def render():
    st.header("通行規制・回避ルート管理")
    st.markdown("""
    大阪府警のオープンデータ等から抽出した交通規制（スクールゾーン、一方通行、進入禁止など）を管理します。
    ここで有効（アクティブ）になっている規制エリアは、AIがルートを作成する際に**通行禁止（ペナルティ）**として扱われ、自動的に迂回ルートが組まれます。
    """)

    if not os.path.exists(RULES_CSV):
        st.warning(f"規制データが見つかりません。先に変換スクリプトを実行して `{RULES_CSV}` を配置してください。")
        return

    # データの読み込み
    try:
        df_rules = pd.read_csv(RULES_CSV)
        # 文字列になっている座標リストをPythonのリストに変換
        df_rules['座標リスト(緯度,経度)'] = df_rules['座標リスト(緯度,経度)'].apply(ast.literal_eval)
    except Exception as e:
        st.error(f"データの読み込みに失敗しました: {e}")
        return

    # 現在の送迎時間帯フィルター
    st.subheader("規制状況の確認")
    col1, col2 = st.columns([1, 2])
    
    with col1:
        current_time = st.time_input("送迎予定時刻を設定", value=pd.to_datetime("08:00").time())
        time_float = current_time.hour * 100 + current_time.minute
        
        st.info(f"設定時刻: {current_time.strftime('%H:%M')} (数値: {time_float})")
        
        # 時間帯によるフィルタリングロジック
        def is_active(row, t_float):
            start = row['開始時間']
            end = row['終了時間']
            if pd.isna(start) or pd.isna(end):
                return True # 終日規制（一方通行など）
            return start <= t_float <= end

        df_rules['現在有効'] = df_rules.apply(lambda r: is_active(r, time_float), axis=1)
        active_count = df_rules['現在有効'].sum()
        
        st.metric("現在引っかかる規制エリア数", f"{active_count} 箇所")

    with col2:
        # 施設（デポ）の座標を取得してマップの中心にする
        depot_lat, depot_lng = 34.8040, 135.6532
        if not st.session_state.users_df.empty and 0.0 in st.session_state.users_df["id"].astype(float).values:
            depot_row = st.session_state.users_df[st.session_state.users_df["id"].astype(float) == 0.0].iloc[0]
            depot_lat, depot_lng = float(depot_row["lat"]), float(depot_row["lng"])

        m_rules = folium.Map(location=[depot_lat, depot_lng], zoom_start=13)
        
        # 施設マーカー
        folium.CircleMarker(
            location=[depot_lat, depot_lng], radius=8, color="blue", fill=True, popup="施設"
        ).add_to(m_rules)

        # 規制エリアの描画
        active_rules = df_rules[df_rules['現在有効']]
        for idx, row in active_rules.iterrows():
            coords = row['座標リスト(緯度,経度)']
            rule_type = row['規制種別']
            rule_desc = row['条件詳細']
            
            # 規制種類によって色を変える
            color = "red" if "通禁" in rule_type else "orange"
            
            if len(coords) > 1:
                folium.PolyLine(
                    locations=coords,
                    color=color,
                    weight=5,
                    opacity=0.7,
                    popup=f"<b>{rule_type}</b><br>{rule_desc}"
                ).add_to(m_rules)

        st_folium(m_rules, width="100%", height=400)

    st.divider()
    
    st.subheader("規制データ一覧")
    st.dataframe(
        df_rules[['現在有効', '規制種別', '条件詳細', '開始時間', '終了時間']],
        use_container_width=True,
        hide_index=True
    )