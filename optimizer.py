import os
import requests
import pandas as pd
import ast
import datetime
import time
from shapely.geometry import LineString
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp
import utils

OSRM_BASE = "http://router.project-osrm.org"
VEHICLE_CAPACITY_FIXED = 3 # 1便あたり最大3枠
MAX_TRIPS = 3 # 1台につき最大第3便まで往復を許可

def get_active_rules_geometry():
    rules_path = os.path.join(utils.DATA_DIR, "traffic_rules.csv")
    if not os.path.exists(rules_path): return []
    try:
        df = pd.read_csv(rules_path)
        now = datetime.datetime.now().time()
        time_float = now.hour * 100 + now.minute
        active_lines = []
        for _, row in df.iterrows():
            start, end = row['開始時間'], row['終了時間']
            if pd.isna(start) or pd.isna(end) or (start <= time_float <= end):
                coords = ast.literal_eval(row['座標リスト(緯度,経度)'])
                if len(coords) >= 2:
                    active_lines.append(LineString([(c[1], c[0]) for c in coords]))
        return active_lines
    except: return []

def get_duration_matrix(waypoints):
    n = len(waypoints)
    durations = [[0] * n for _ in range(n)]
    distances = [[0] * n for _ in range(n)]
    restricted_lines = get_active_rules_geometry()
    
    for i in range(n):
        for j in range(n):
            if i == j: continue
            p1, p2 = waypoints[i], waypoints[j]
            url = f"{OSRM_BASE}/route/v1/driving/{p1['lng']},{p1['lat']};{p2['lng']},{p2['lat']}?overview=simplified&geometries=geojson"
            try:
                resp = requests.get(url, timeout=5).json()
                if resp.get("code") == "Ok":
                    route = resp["routes"][0]
                    dur, dist = int(route["duration"]), int(route["distance"])
                    path_line = LineString(route["geometry"]["coordinates"])
                    for restricted_line in restricted_lines:
                        if path_line.intersects(restricted_line.buffer(0.0002)):
                            dur *= 100
                            dist *= 100
                            break
                    durations[i][j] = dur
                    distances[i][j] = dist
                else:
                    durations[i][j], distances[i][j] = 999999, 999999
            except:
                durations[i][j], distances[i][j] = 999999, 999999
            time.sleep(0.05)
    return durations, distances

def run_optimization(selected_user_ids, num_vehicles):
    users_df = pd.read_csv(utils.USERS_CSV)
    vehicles_df = pd.read_csv(utils.VEHICLES_CSV)

    depot_df = users_df[users_df["id"].astype(float) == 0.0]
    depot_row = depot_df.iloc[0] if not depot_df.empty else {"id": 0, "name": "施設", "lat": 34.8151, "lng": 135.6525}
    target_users = users_df[users_df["id"].astype(float).isin(selected_user_ids)]
    waypoints = [depot_row] + [row for _, row in target_users.iterrows()]
    n = len(waypoints)
    
    # ---------------------------------------------------------
    # 【オートチューニングロジック】
    # 人数に応じて計算の制限時間を自動調整し、各種ペナルティ係数も最適値で固定
    user_count = n - 1
    if user_count <= 10:
        solver_time_limit_sec = 5   # 人数が少なければサクッと5秒で終わらせる
    elif user_count <= 20:
        solver_time_limit_sec = 10  # 中規模なら10秒じっくり考える
    else:
        solver_time_limit_sec = 15  # 大規模なら15秒かけて精度を上げる

    # 安定稼働のための固定パラメータ（元の weights.json の役割）
    w_travel = 1.0     # 移動時間の重み
    w_balance = 100    # 車両間の負荷バランスを保つためのペナルティ
    w_ride = 5         # 要介護3以上の乗車時間を短くするためのペナルティ
    # ---------------------------------------------------------

    virtual_vehicles = num_vehicles * MAX_TRIPS
    vehicle_capacities = []
    vehicle_wheelchair_support = []
    
    for i in range(virtual_vehicles):
        pid = i % num_vehicles 
        if pid < len(vehicles_df):
            support = VEHICLE_CAPACITY_FIXED if vehicles_df.iloc[pid]["wheelchair_support"] == "あり" else 0
        else:
            support = 0
        vehicle_capacities.append(VEHICLE_CAPACITY_FIXED)
        vehicle_wheelchair_support.append(support)

    demands = [0] * n
    wheelchair_demands = [0] * n
    for i, p in enumerate(waypoints[1:], start=1):
        if p.get("wheelchair") == "あり":
            demands[i] = 2
            wheelchair_demands[i] = 1
        else:
            demands[i] = 1

    if sum(demands) > sum(vehicle_capacities):
        raise ValueError(f"【定員オーバー】第{MAX_TRIPS}便までフル稼働しても乗り切れません。車両を増やすか利用者を減らしてください。")
    if sum(wheelchair_demands) > sum(vehicle_wheelchair_support):
        raise ValueError("【車いす枠不足】車いす対応車の枠が不足しています。対応車を増やすか利用者を減らしてください。")

    durations, distances = get_duration_matrix(waypoints)
    manager = pywrapcp.RoutingIndexManager(n, virtual_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    # 距離・時間のコールバックに要介護者配慮（w_ride）を組み込む
    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        cost = durations[from_node][to_node] * w_travel
        
        if to_node != 0:
            care_level = waypoints[to_node].get("care_level", "")
            if "要介護3" in care_level or "要介護4" in care_level or "要介護5" in care_level:
                cost += w_ride
        return int(cost)

    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    demand_callback_index = routing.RegisterUnaryTransitCallback(lambda f: demands[manager.IndexToNode(f)])
    routing.AddDimensionWithVehicleCapacity(demand_callback_index, 0, vehicle_capacities, True, 'Capacity')

    wheelchair_callback_index = routing.RegisterUnaryTransitCallback(lambda f: wheelchair_demands[manager.IndexToNode(f)])
    routing.AddDimensionWithVehicleCapacity(wheelchair_callback_index, 0, vehicle_wheelchair_support, True, 'Wheelchair')

    # 負荷分散（便のバランス）
    time_dimension = routing.GetDimensionOrDie('Capacity')
    time_dimension.SetGlobalSpanCostCoefficient(w_balance)

    # パズル失敗時用の安全弁（ペナルティ退避）
    penalty = 1000000
    for node in range(1, n):
        routing.AddDisjunction([manager.NodeToIndex(node)], penalty)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    
    # オートチューニングした制限時間をセット
    search_parameters.time_limit.seconds = solver_time_limit_sec

    solution = routing.SolveWithParameters(search_parameters)
    if not solution: raise Exception("最適化解が見つかりません。条件を見直してください。")

    result_rows = []
    routed_user_ids = set()
    
    for pid in range(num_vehicles):
        order = 1
        active_trip_counter = 1
        for trip_idx in range(MAX_TRIPS):
            v_id = (trip_idx * num_vehicles) + pid
            index = routing.Start(v_id)
            
            temp_users = []
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                if node != 0:
                    temp_users.append(waypoints[node])
                    routed_user_ids.add(int(float(waypoints[node]["id"])))
                index = solution.Value(routing.NextVar(index))
                
            if temp_users:
                for user in temp_users:
                    result_rows.append({
                        "vehicle_id": pid,
                        "trip": active_trip_counter,
                        "order": order,
                        "user_id": int(float(user["id"])),
                        "name": user["name"]
                    })
                    order += 1
                active_trip_counter += 1

    # ドロップされた人を「未割り当て(999)」に追加
    unassigned_order = 1
    for p in waypoints[1:]:
        uid = int(float(p["id"]))
        if uid not in routed_user_ids:
            result_rows.append({
                "vehicle_id": 999,
                "trip": 1,
                "order": unassigned_order,
                "user_id": uid,
                "name": p["name"]
            })
            unassigned_order += 1
                
    return result_rows