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
    """
    OSRM /table/v1/driving で移動時間行列（秒）を取得。
    nodes: [{"lat": ..., "lng": ...}, ...]
    """
    coords = ";".join(f"{p['lng']},{p['lat']}" for p in nodes)
    url = f"{OSRM_BASE}/table/v1/driving/{coords}?annotations=duration"
    resp = requests.get(url, timeout=20)
    data = resp.json()

    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM table error: {data.get('code')}")

    BIG = 10_000_000  # null（到達不可）のペナルティ
    matrix = []
    for row in data["durations"]:
        matrix.append([int(v) if v is not None else BIG for v in row])
    return matrix


def run_optimization(users_df: pd.DataFrame, selected_ids: list[int], n_vehicles: int = 1) -> list[dict]:
    """
    OR-Tools VRP で最短ルートを計算し結果のリストを返す。

    Args:
        users_df    : スプレッドシートから読み込んだ全利用者のDataFrame
        selected_ids: 訪問する利用者 ID のリスト
        n_vehicles  : 車両数

    Returns:
        [{"vehicle_id": int, "order": int, "user_id": int, "user": str}, ...]
    """
    # id列を確実に整数型に変換し、空白行を除外する
    users_df = users_df.dropna(subset=["id"]).copy()
    users_df["id"] = users_df["id"].astype(int)

    depot = users_df[users_df["id"] == 0].iloc[0]
    users = users_df[users_df["id"].isin(selected_ids)].copy()

    if users.empty:
        return []

    # ノード一覧: index 0 = デポ、index 1..n = 利用者
    nodes = [{"id": int(depot["id"]), "lat": float(depot["lat"]),
               "lng": float(depot["lng"]), "name": str(depot["name"])}]
    for _, u in users.iterrows():
        nodes.append({"id": int(u["id"]), "lat": float(u["lat"]),
                      "lng": float(u["lng"]), "name": str(u["name"])})

    n = len(nodes)
    n_vehicles = max(1, min(n_vehicles, n - 1))  # 利用者数を超えないよう制限

    # ── OSRM 距離行列取得 ──
    dist_matrix = get_duration_matrix(nodes)

    # ── OR-Tools セットアップ ──
    manager = pywrapcp.RoutingIndexManager(n, n_vehicles, 0)  # depot index = 0
    routing = pywrapcp.RoutingModel(manager)

    def transit_cb(from_idx, to_idx):
        return dist_matrix[manager.IndexToNode(from_idx)][manager.IndexToNode(to_idx)]

    cb_idx = routing.RegisterTransitCallback(transit_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(cb_idx)

    # 各車両の移動時間次元 + 全車両の最大時間差を最小化（バランス重視）
    routing.AddDimension(cb_idx, 0, 100_000, True, "Time")
    time_dim = routing.GetDimensionOrDie("Time")
    time_dim.SetGlobalSpanCostCoefficient(100)

    # 探索パラメータ
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.seconds = 10

    solution = routing.SolveWithParameters(params)

    if solution is None:
        raise RuntimeError("OR-Tools: 解が見つかりませんでした")

    # ── ルート抽出 ──
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

    return rows
