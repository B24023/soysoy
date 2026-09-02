import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
import datetime
from optimizer import run_optimization
from streamlit_sortables import sort_items

st.set_page_config(page_title="老人ホーム送迎ルート最適化システム", layout="wide")

# ──────────────────────────────────────────
# セッションステートの初期化
# ──────────────────────────────────────────
if "users_df" not in st.session_state:
    try:
        df = pd.read_csv("data/users.csv")
        if "care_level" not in df.columns: df["care_level"] = "要介護1"
        if "wheelchair" not in df.columns: df["wheelchair"] = "なし"
        if "days" not in df.columns: df["days"] = "月,火,水,木,金"
        st.session_state.users_df = df
    except:
        st.session_state.users_df = pd.DataFrame(columns=["id", "name", "lat", "lng", "address", "care_level", "wheelchair", "days"])

if "vehicles_df" not in st.session_state:
    st.session_state.vehicles_df = pd.DataFrame({
        "id": [1, 2],
        "name": ["1号車（ハイエース）", "2号車（ノア）"],
        "capacity": [8, 5],
        "wheelchair_support": ["あり", "なし"],
        "driver": ["佐藤", "鈴木"]
    })

if "impassable_df" not in st.session_state:
    st.session_state.impassable_df = pd.DataFrame(columns=["id", "road_name", "memo", "lat", "lng"])

if "optimization_done" not in st.session_state:
    st.session_state.optimization_done = False

if "route_data" not in st.session_state:
    st.session_state.route_data = []

# ──────────────────────────────────────────
# ユーティリティ関数
# ──────────────────────────────────────────
def get_route_geometry_and_steps(waypoints):
    coords = ";".join([f"{p['lng']},{p['lat']}" for p in waypoints])
    url = f"http://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson&steps=true"
    try:
        resp = requests.get(url, timeout=15).json()
        if resp.get("code") == "Ok":
            route = resp["routes"][0]
            route_coords = route["geometry"]["coordinates"]
            distance = route["distance"]
            
            road_names = []
            for leg in route.get("legs", []):
                for step in leg.get("steps", []):
                    name = step.get("name", "")
                    if name and (not road_names or road_names[-1] != name):
                        road_names.append(name)
            
            return [[c[1], c[0]] for c in route_coords], distance, road_names
    except Exception:
        pass
    return None, 0, []

def update_route_data_from_csv(num_vehicles):
    try:
        result_df = pd.read_csv("data/result.csv")
        merged = result_df.merge(st.session_state.users_df, left_on="user_id", right_on="id", how="left")
        
        route_data = []
        for vid in range(num_vehicles):
            v_rows = merged[merged["vehicle_id"] == vid].sort_values("order")
            v_name = f"車両 {vid + 1}"
            items = []
            for _, r in v_rows.iterrows():
                items.append(f"ID{r['id']}: {r['name']} ({r['care_level']})")
            route_data.append({"header": v_name, "items": items})
            
        route_data.append({"header": "未割り当て（手動で移動）", "items": []})
        st.session_state.route_data = route_data
    except Exception as e:
        st.error(f"結果の変換エラー: {e}")

# ──────────────────────────────────────────
# UIの構築
# ──────────────────────────────────────────
st.title("送迎ルート最適化システム")
st.markdown("日々の送迎計画の作成と、利用者・車両データの管理を行います。")

# 本来のタブUIを使用
tab_plan, tab_users, tab_vehicles, tab_road, tab_result = st.tabs([
    "ダッシュボード＆計画作成", 
    "利用者管理", 
    "車両管理", 
    "通行止め管理", 
    "最適化結果"
])

# ＝＝＝ タブ1: ダッシュボード＆計画作成 ＝＝＝
with tab_plan:
    st.header("送迎計画の作成")
    st.markdown("※ 今日お休みする利用者はチェックを外して除外してください。")
    
    col_filter, _ = st.columns([1, 3])
    with col_filter:
        selected_day = st.selectbox("曜日表示フィルター", ["すべて", "月", "火", "水", "木", "金", "土", "日"])
    
    df = st.session_state.users_df
    display_df = df[df["id"] != 0].copy()
    if selected_day != "すべて":
        display_df = display_df[display_df["days"].str.contains(selected_day, na=False)]
    
    display_df.insert(0, "出席", True)
    
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
            
        st.write("**本日の「通れない道」適用**")
        if not st.session_state.impassable_df.empty:
            for _, road in st.session_state.impassable_df.iterrows():
                st.checkbox(f"{road['road_name']} ({road['memo']})", value=True)
        else:
            st.caption("登録されている通れない道はありません。")

    if st.button("AIで最適ルートを自動作成する", type="primary", use_container_width=True):
        selected_ids = edited_plan_df[edited_plan_df["出席"]]["id"].tolist()
        if not selected_ids:
            st.error("エラー: 出席予定の利用者がいません。")
        else:
            with st.spinner("AIが最適ルートを計算中..."):
                try:
                    run_optimization(selected_ids, int(n_vehicles))
                    update_route_data_from_csv(int(n_vehicles))
                    st.session_state.optimization_done = True
                    st.success("最適化が完了しました。上部の「最適化結果」タブをクリックして確認してください。")
                except Exception as e:
                    st.error(f"最適化エラー: {e}")

# ＝＝＝ タブ2: 利用者管理 ＝＝＝
with tab_users:
    st.header("新規利用者登録")
    with st.form("add_user_form"):
        c1, c2 = st.columns(2)
        with c1:
            u_name = st.text_input("氏名 *")
            u_care = st.selectbox("要介護度", ["要支援1", "要支援2", "要介護1", "要介護2", "要介護3", "要介護4", "要介護5"])
        with c2:
            u_wheel = st.selectbox("車椅子利用", ["なし", "あり"])
            u_days = st.multiselect("利用曜日", ["月", "火", "水", "木", "金", "土", "日"], default=["月", "水", "金"])
        
        u_address = st.text_input("住所 *")
        
        if st.form_submit_button("登録する", type="primary"):
            if u_name and u_address:
                new_id = st.session_state.users_df["id"].max() + 1 if not st.session_state.users_df.empty else 1
                new_row = {"id": new_id, "name": u_name, "lat": 34.815, "lng": 135.652, "address": u_address, "care_level": u_care, "wheelchair": u_wheel, "days": ",".join(u_days)}
                st.session_state.users_df = pd.concat([st.session_state.users_df, pd.DataFrame([new_row])], ignore_index=True)
                st.session_state.users_df.to_csv("data/users.csv", index=False)
                st.success(f"{u_name} さんを登録しました。")
            else:
                st.error("エラー: 必須項目を入力してください。")

    st.divider()
    st.subheader("利用者一覧")
    st.dataframe(st.session_state.users_df, hide_index=True, use_container_width=True)

# ＝＝＝ タブ3: 車両管理 ＝＝＝
with tab_vehicles:
    st.header("車両一覧")
    st.dataframe(st.session_state.vehicles_df, hide_index=True, use_container_width=True)

# ＝＝＝ タブ4: 通行止め管理 ＝＝＝
with tab_road:
    st.header("通れない道（工事・通行止め）登録")
    st.markdown("※ 地図をクリックして緯度経度を取得できます。")
    
    m_road = folium.Map(location=[34.8151, 135.6525], zoom_start=13)
    st_data = st_folium(m_road, height=300, width=800)
    
    with st.form("add_road_form"):
        clicked_lat = st_data["last_clicked"]["lat"] if st_data and st_data.get("last_clicked") else ""
        clicked_lng = st_data["last_clicked"]["lng"] if st_data and st_data.get("last_clicked") else ""
        
        st.write(f"選択した座標: {clicked_lat}, {clicked_lng}")
        r_name = st.text_input("道路名・区間 *", placeholder="例：国道1号線 枚方バイパス")
        r_memo = st.text_input("メモ", placeholder="例：終日車線規制")
        
        if st.form_submit_button("区間を登録する", type="primary"):
            if r_name and clicked_lat:
                new_id = len(st.session_state.impassable_df) + 1
                new_road = {"id": new_id, "road_name": r_name, "memo": r_memo, "lat": clicked_lat, "lng": clicked_lng}
                st.session_state.impassable_df = pd.concat([st.session_state.impassable_df, pd.DataFrame([new_road])], ignore_index=True)
                st.success("登録しました。")
            else:
                st.error("エラー: 地図をクリックして座標を指定し、道路名を入力してください。")
                
    st.subheader("通れない道 一覧")
    st.dataframe(st.session_state.impassable_df, hide_index=True)

# ＝＝＝ タブ5: 最適化結果 ＝＝＝
with tab_result:
    if not st.session_state.optimization_done:
        st.markdown("※ 「計画作成」タブから最適化を実行すると、ここに結果が表示されます。")
    else:
        st.header("最適化結果・配車表")
        st.caption("※ 現場用配車表として出力する場合は、一番下のCSV出力をご利用ください。")
        
        st.write("**ルートの微調整（ドラッグ＆ドロップで移動・順番変更が可能です）**")
        
        new_route_data = sort_items(st.session_state.route_data, multi_containers=True)
        
        if new_route_data and new_route_data != st.session_state.route_data:
            st.session_state.route_data = new_route_data
            st.rerun()

        try:
            users_df = st.session_state.users_df
            depot_row = users_df[users_df["id"] == 0].iloc[0]
            
            m_res = folium.Map(location=[depot_row["lat"], depot_row["lng"]], zoom_start=13)
            folium.CircleMarker(
                location=[depot_row["lat"], depot_row["lng"]],
                radius=10,
                color="red",
                fill=True,
                fill_color="red",
                popup="施設"
            ).add_to(m_res)

            v_colors = ['blue', 'green', 'orange', 'purple', 'darkred']
            
            vehicles = []
            export_rows = []
            
            for route in st.session_state.route_data:
                header = route["header"]
                if header == "未割り当て（手動で移動）":
                    continue
                    
                vid_str = header.replace("車両 ", "")
                vid = int(vid_str) if vid_str.isdigit() else 1
                
                points = []
                for i, item in enumerate(route["items"]):
                    uid = int(item.split(":")[0].replace("ID", ""))
                    user_row = users_df[users_df["id"] == uid].iloc[0]
                    points.append({
                        "order": i + 1,
                        "id": uid,
                        "name": user_row["name"],
                        "lat": user_row["lat"],
                        "lng": user_row["lng"],
                        "address": user_row["address"],
                        "care_level": user_row["care_level"]
                    })
                    export_rows.append({
                        "vehicle_id": vid,
                        "order": i + 1,
                        "user_id": uid,
                        "user": user_row["name"]
                    })
                vehicles.append({
                    "vehicle_id": vid,
                    "points": points
                })
            
            cols = st.columns(len(vehicles) if len(vehicles) > 0 else 1)
            
            for i, v in enumerate(vehicles):
                color = v_colors[i % len(v_colors)]
                v_info = st.session_state.vehicles_df[st.session_state.vehicles_df["id"] == v["vehicle_id"]]
                v_name = v_info["name"].values[0] if not v_info.empty else f"車両 {v['vehicle_id']}"
                driver = v_info["driver"].values[0] if not v_info.empty else "未定"
                
                waypoints = [{"lat": depot_row["lat"], "lng": depot_row["lng"]}]
                
                with cols[i]:
                    st.markdown(f"### <span style='color:{color}'>■</span> {v_name}", unsafe_allow_html=True)
                    st.caption(f"担当ドライバー: {driver}")
                    
                    for pt in v["points"]:
                        waypoints.append({"lat": pt["lat"], "lng": pt["lng"]})
                        folium.CircleMarker(
                            location=[pt["lat"], pt["lng"]],
                            radius=8,
                            color=color,
                            fill=True,
                            fill_color=color,
                            popup=f"{pt['name']} ({pt['care_level']})"
                        ).add_to(m_res)
                    waypoints.append({"lat": depot_row["lat"], "lng": depot_row["lng"]})

                    route_coords, dist, roads = get_route_geometry_and_steps(waypoints)
                    
                    if route_coords:
                        folium.PolyLine(route_coords, color=color, weight=5, opacity=0.8).add_to(m_res)
                        
                    st.write(f"総移動距離: {dist/1000:.1f} km")
                    
                    for idx, pt in enumerate(v["points"]):
                        with st.container(border=True):
                            st.markdown(f"**{idx+1}. {pt['name']}** <span style='font-size:0.8em; color:gray;'>({pt['care_level']})</span>", unsafe_allow_html=True)
                            st.caption(f"住所: {pt['address']}")
                    
                    if roads:
                        st.caption("主な経由道: " + " -> ".join(roads[:5]) + ("..." if len(roads)>5 else ""))
            
            st.write("### 全体ルートマップ")
            st_folium(m_res, width="100%", height=500)
            
            csv_data = pd.DataFrame(export_rows).to_csv(index=False).encode('utf-8-sig')
            st.download_button("現場用配車表を出力 (CSV)", data=csv_data, file_name=f"配車表_{datetime.date.today()}.csv", mime="text/csv", type="primary")
            
        except Exception as e:
            st.error(f"結果の読み込みエラー: {e}")