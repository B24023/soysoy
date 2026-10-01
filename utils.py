import os
import json
import requests
import pandas as pd
import streamlit as st

DATA_DIR = "data"
DEMO_DIR = os.path.join(DATA_DIR, "demo")
USERS_CSV = os.path.join(DATA_DIR, "users.csv")
VEHICLES_CSV = os.path.join(DATA_DIR, "vehicles.csv")
VETERAN_CSV = os.path.join(DATA_DIR, "veteran_route.csv")
WEIGHTS_JSON = "weights.json"

def initialize_system():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(DEMO_DIR, exist_ok=True)

    if not os.path.exists(WEIGHTS_JSON):
        default_weights = {
            "w_travel": 1.0, "w_balance": 100, "w_ride": 5, 
            "w_window": 0, "w_stability": 0, "solver_time_limit_sec": 10
        }
        with open(WEIGHTS_JSON, "w", encoding="utf-8") as f:
            json.dump(default_weights, f, indent=2)

    if not os.path.exists(USERS_CSV):
        df_u = pd.DataFrame([{
            "id": 0, "name": "施設（デポ）", "lat": 34.8151, "lng": 135.6525, 
            "address": "大阪府枚方市山之上北町", "care_level": "-", "wheelchair": "なし", 
            "pre_call": "なし", "days": "月,火,水,木,金,土,日"
        }])
        df_u.to_csv(USERS_CSV, index=False, encoding="utf-8-sig")
    else:
        df_check = pd.read_csv(USERS_CSV, encoding="utf-8-sig")
        if 0 not in df_check["id"].astype(int).values:
            depot_row = pd.DataFrame([{
                "id": 0, "name": "施設（デポ）", "lat": 34.8151, "lng": 135.6525, 
                "address": "大阪府枚方市山之上北町", "care_level": "-", "wheelchair": "なし", 
                "pre_call": "なし", "days": "月,火,水,木,金,土,日"
            }])
            df_check = pd.concat([depot_row, df_check], ignore_index=True)
            df_check.to_csv(USERS_CSV, index=False, encoding="utf-8-sig")

    if not os.path.exists(VEHICLES_CSV):
        df_v = pd.DataFrame({
            "id": [1, 2, 3],
            "name": ["ラクティス", "ワゴンR", "ノア"],
            "wheelchair_support": ["あり", "なし", "なし"]
        })
        df_v.to_csv(VEHICLES_CSV, index=False, encoding="utf-8-sig")

    if "users_df" not in st.session_state:
        df = pd.read_csv(USERS_CSV, encoding="utf-8-sig").dropna(how="all")
        if "pre_call" not in df.columns: df["pre_call"] = "なし"
        st.session_state.users_df = df

    if "vehicles_df" not in st.session_state:
        st.session_state.vehicles_df = pd.read_csv(VEHICLES_CSV, encoding="utf-8-sig").dropna(how="all")

    if "optimization_done" not in st.session_state:
        st.session_state.optimization_done = False
    if "route_data" not in st.session_state:
        st.session_state.route_data = []

def get_route_geometry_and_steps(waypoints):
    coords = ";".join([f"{p['lng']},{p['lat']}" for p in waypoints])
    url = f"http://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson&steps=true"
    try:
        resp = requests.get(url, timeout=15).json()
        if resp.get("code") == "Ok":
            route = resp["routes"][0]
            route_coords = route["geometry"]["coordinates"]
            distance = route["distance"]
            return [[c[1], c[0]] for c in route_coords], distance, []
    except Exception:
        pass
    return None, 0, []

def update_route_data(optimized_rows, num_vehicles):
    try:
        result_df = pd.DataFrame(optimized_rows)
        st.session_state.users_df["id_float"] = st.session_state.users_df["id"].astype(float)
        result_df["user_id_float"] = result_df["user_id"].astype(float)
        
        users_subset = st.session_state.users_df[["id_float", "care_level"]] 
        merged = result_df.merge(users_subset, left_on="user_id_float", right_on="id_float", how="left")
        
        route_data = []
        for vid in range(num_vehicles):
            v_rows = merged[merged["vehicle_id"] == vid].sort_values("order")
            
            # 車両のIDから実際の車両名（ワゴンRなど）を取得
            v_id_display = vid + 1
            if "vehicles_df" in st.session_state and not st.session_state.vehicles_df.empty:
                v_info = st.session_state.vehicles_df[st.session_state.vehicles_df["id"].astype(float) == float(v_id_display)]
                v_name = v_info["name"].values[0] if not v_info.empty else f"車両 {v_id_display}"
            else:
                v_name = f"車両 {v_id_display}"
                
            items = []
            for _, r in v_rows.iterrows():
                uid = int(float(r['user_id']))
                trip_tag = f" [第{int(r['trip'])}便]" if 'trip' in r and int(r['trip']) > 1 else ""
                items.append(f"ID{uid}: {r['name']}{trip_tag} ({r['care_level']})")
                
            # vehicle_idを保持したまま、headerに実際の車両名をセットする
            route_data.append({"header": v_name, "vehicle_id": v_id_display, "items": items})
            
        unassigned_rows = merged[merged["vehicle_id"] == 999].sort_values("order")
        unassigned_items = []
        for _, r in unassigned_rows.iterrows():
            uid = int(float(r['user_id']))
            unassigned_items.append(f"ID{uid}: {r['name']} ({r['care_level']})")
        route_data.append({"header": "未割り当て（手動で移動）", "vehicle_id": 999, "items": unassigned_items})
        
        st.session_state.route_data = route_data
    except Exception as e:
        st.error(f"結果の変換エラー: {e}")