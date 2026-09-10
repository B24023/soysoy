"""
OR-Tools VRP 最適化モジュール
- 選択した利用者のみを対象
- OSRM /table API で実道路の移動時間行列を取得
- 複数車両対応（min-max バランス）
"""
import pandas as pd
import requests
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

OSRM_BASE = "http://router.project-osrm.org"

def get_duration_matrix(nodes: list[dict]) -> list[list[int]]:
    coords = ";".join(f"{p['lng']},{p['lat']}" for p in nodes)
    url = f"{OSRM_BASE}/table/v1/driving/{coords}?annotations=duration"
    resp = requests.get(url, timeout=20)
    data = resp.json()

    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM table error: {data.get('code')}")

    BIG = 10_000_000
    matrix = []
    for row in data["durations"]:
        matrix.append([int(v) if v is not None else BIG for v in row])
    return matrix

# 修正ポイント：引数に users_df を追加し、戻り値として直接リストを返すように変更
def run_optimization(users_df: pd.DataFrame, selected_ids: list[int], n_vehicles: int = 1) -> list[dict]:
    
    # CSV読み込みを廃止し、引数で受け取った users_df を使う
    depot = users_df[users_df["id"] == 0].iloc[0]
    users = users_df[users_df["id"].isin(selected_ids)].copy()

    if users.empty:
        return []

    nodes = [{"id": int(depot["id"]), "lat": float(depot["lat"]),
               "lng": float(depot["lng"]), "name": str(depot["name"])}]
    for _, u in users.iterrows():
        nodes.append({"id": int(u["id"]), "lat": float(u["lat"]),
                      "lng": float(u["lng"]), "name": str(u["name"])})

    n = len(nodes)
    n_vehicles = max(1, min(n_vehicles, n - 1))

    dist_matrix = get_duration_matrix(nodes)

    manager = pywrapcp.RoutingIndexManager(n, n_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    def transit_cb(from_idx, to_idx):
        return dist_matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]

    cb_idx = routing.RegisterTransitCallback(transit_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(cb_idx)

    routing.AddDimension(cb_idx, 0, 100_000, True, "Time")
    time_dim = routing.GetDimensionOrDie("Time")
    time_dim.SetGlobalSpanCostCoefficient(100)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = 10

    solution = routing.SolveWithParameters(params)

    if solution is None:
        raise RuntimeError("OR-Tools: 解が見つかりませんでした")

    rows = []
    for vid in range(n_vehicles):
        idx = routing.Start(vid)
        order = 1
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node != 0:
                rows.append({
                    "vehicle_id": vid,
                    "order":      order,
                    "user_id":    nodes[node]["id"],
                    "user":       nodes[node]["name"],
                })
                order += 1
            idx = solution.Value(routing.NextVar(idx))

    # CSVへの保存処理を削除し、結果データのみを返す
    return rows
