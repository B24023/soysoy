import streamlit as st
import pandas as pd
import datetime
import folium
from streamlit_folium import st_folium
from streamlit_sortables import sort_items
import io
import utils

def generate_excel():
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        workbook = writer.book
        worksheet = workbook.add_worksheet('送迎表')
        
        fmt_header = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#D9D9D9', 'border': 1})
        fmt_normal = workbook.add_format({'align': 'center', 'border': 1})
        fmt_call = workbook.add_format({'align': 'center', 'border': 1, 'bg_color': '#FFFF00'})
        fmt_time = workbook.add_format({'align': 'center', 'border': 1})
        fmt_blank = workbook.add_format({'border': 1})
        
        worksheet.set_column('A:O', 12)
        
        users_df = st.session_state.users_df
        vehicles_df = st.session_state.vehicles_df
        
        TOTAL_TRIPS = 4
        TOTAL_VEHICLES = 5
        row_offset = 0
        
        for current_trip in range(1, TOTAL_TRIPS + 1):
            col_offset = 0
            
            for vid in range(TOTAL_VEHICLES):
                v_id_display = vid + 1
                v_info = vehicles_df[vehicles_df["id"].astype(float) == float(v_id_display)] if not vehicles_df.empty else pd.DataFrame()
                v_name = v_info["name"].values[0] if not v_info.empty else f"車両 {v_id_display}"
                
                trip_title = v_name if current_trip == 1 else f"{v_name} (第{current_trip}便)"
                worksheet.merge_range(row_offset, col_offset, row_offset, col_offset + 2, trip_title, fmt_header)
                
                for r_i in [1, 2, 3, 4]:
                    for c_i in range(3):
                        worksheet.write(row_offset + r_i, col_offset + c_i, "", fmt_blank)
                
                trip_users = []
                # vehicle_idを使って正確にルートデータを取得
                for route in st.session_state.route_data:
                    if route.get("vehicle_id") == v_id_display:
                        for item in route["items"]:
                            u_trip = 1
                            if " [第" in item:
                                try: u_trip = int(item.split(" [第")[1].split("便]")[0])
                                except: pass
                            
                            if u_trip == current_trip:
                                uid = int(float(item.split(":")[0].replace("ID", "")))
                                u_row = users_df[users_df["id"].astype(float) == float(uid)].iloc[0]
                                trip_users.append(u_row)
                        break 
                
                if trip_users:
                    assigned = []
                    for u_row in trip_users:
                        name = u_row["name"]
                        is_wheelchair = (u_row.get("wheelchair") == "あり")
                        needs_call = (u_row.get("pre_call") == "あり")
                        cell_fmt = fmt_call if needs_call else fmt_normal
                        
                        if is_wheelchair:
                            worksheet.merge_range(row_offset + 3, col_offset + 0, row_offset + 3, col_offset + 1, name, cell_fmt)
                            worksheet.merge_range(row_offset + 4, col_offset + 0, row_offset + 4, col_offset + 1, "09:00:00", fmt_time)
                            assigned.append("WHEEL")
                        else:
                            if "FRONT_LEFT" not in assigned:
                                worksheet.write(row_offset + 1, col_offset + 0, name, cell_fmt)
                                worksheet.write(row_offset + 2, col_offset + 0, "09:00:00", fmt_time)
                                assigned.append("FRONT_LEFT")
                            elif "BACK_LEFT" not in assigned and "WHEEL" not in assigned:
                                worksheet.write(row_offset + 3, col_offset + 0, name, cell_fmt)
                                worksheet.write(row_offset + 4, col_offset + 0, "09:00:00", fmt_time)
                                assigned.append("BACK_LEFT")
                            elif "BACK_MIDDLE" not in assigned and "WHEEL" not in assigned:
                                worksheet.write(row_offset + 3, col_offset + 1, name, cell_fmt)
                                worksheet.write(row_offset + 4, col_offset + 1, "09:00:00", fmt_time)
                                assigned.append("BACK_MIDDLE")
                            elif "BACK_RIGHT" not in assigned:
                                worksheet.write(row_offset + 3, col_offset + 2, name, cell_fmt)
                                worksheet.write(row_offset + 4, col_offset + 2, "09:00:00", fmt_time)
                                assigned.append("BACK_RIGHT")
                                
                col_offset += 3 
            row_offset += 6 
                
    output.seek(0)
    return output

def render():
    if not st.session_state.optimization_done:
        st.markdown("※ 「計画作成」タブから最適化を実行してください。")
        return
        
    st.header("最適化結果・配車表")
    new_route_data = sort_items(st.session_state.route_data, multi_containers=True)
    if new_route_data and new_route_data != st.session_state.route_data:
        st.session_state.route_data = new_route_data
        st.rerun()

    try:
        users_df = st.session_state.users_df
        depot_row = users_df[users_df["id"].astype(float) == 0.0].iloc[0] if 0.0 in users_df["id"].astype(float).values else {"lat": 34.8151, "lng": 135.6525}
        
        m_res = folium.Map(location=[float(depot_row["lat"]), float(depot_row["lng"])], zoom_start=13)
        folium.CircleMarker([float(depot_row["lat"]), float(depot_row["lng"])], radius=10, color="red", fill=True, popup="施設").add_to(m_res)

        vehicles, v_colors = [], ['blue', 'green', 'orange', 'purple', 'darkred']
        
        for route in st.session_state.route_data:
            if route["header"] == "未割り当て（手動で移動）": continue
            vid = route.get("vehicle_id", 1)
            points = []
            for i, item in enumerate(route["items"]):
                uid = int(float(item.split(":")[0].replace("ID", "")))
                trip_num = 1
                if " [第" in item:
                    try: trip_num = int(item.split(" [第")[1].split("便]")[0])
                    except: pass
                u_row = users_df[users_df["id"].astype(float) == float(uid)].iloc[0]
                points.append({
                    "order": i + 1, "id": uid, "name": u_row["name"],
                    "lat": float(u_row["lat"]), "lng": float(u_row["lng"]),
                    "address": u_row["address"], "care_level": u_row["care_level"],
                    "trip": trip_num
                })
            vehicles.append({"vehicle_id": vid, "header": route["header"], "points": points})
        
        st.markdown("<hr>", unsafe_allow_html=True)
        
        # 横並び（カラム）ではなく縦並びに変更し、間に一行空行を挟む
        for i, v in enumerate(vehicles):
            color = v_colors[i % len(v_colors)]
            v_name = v["header"]
            
            waypoints = [{"lat": float(depot_row["lat"]), "lng": float(depot_row["lng"])}]
            last_trip = 1
            
            st.markdown(f"### <span style='color:{color}'>■</span> {v_name}", unsafe_allow_html=True)
            
            for pt in v["points"]:
                if pt["trip"] > last_trip:
                    waypoints.append({"lat": float(depot_row["lat"]), "lng": float(depot_row["lng"])})
                    last_trip = pt["trip"]
                    st.markdown("---") 
                    st.markdown(f"**【第{pt['trip']}便 出発】**")
                
                waypoints.append({"lat": pt["lat"], "lng": pt["lng"]})
                folium.CircleMarker([pt["lat"], pt["lng"]], radius=8, color=color, fill=True, popup=pt['name']).add_to(m_res)
                st.markdown(f"**{pt['order']}. {pt['name']}**")
                
            waypoints.append({"lat": float(depot_row["lat"]), "lng": float(depot_row["lng"])})
            
            route_coords, dist, _ = utils.get_route_geometry_and_steps(waypoints)
            if route_coords: folium.PolyLine(route_coords, color=color, weight=5, opacity=0.8).add_to(m_res)
            
            # ご要望通り、車両と車両の間に空行を挟む
            st.markdown("<br>", unsafe_allow_html=True)
        
        st.write("### 全体ルートマップ")
        st_folium(m_res, width="100%", height=500)
        
        st.write("### 現場用 Excel 配車表のダウンロード")
        excel_data = generate_excel()
        st.download_button(
            label="座席レイアウト配車表を出力 (.xlsx)", data=excel_data,
            file_name=f"大阪工大_送迎表_{datetime.date.today()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary", use_container_width=True
        )
        
    except Exception as e:
        st.error(f"結果の読み込みエラー: {e}")