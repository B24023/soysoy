"""
run_planner.py
────────────────────────────────────────────────────────────
便（1〜4便）ごとに送迎ルートを計算する「次世代」最適化エンジンの試作。

optimizer.py の run_optimization() は「1台が1本の連続ルートで
全員を回る」モデルだった。実際の送迎は「車が施設(デポ)に何度も
戻り、便ごとに違うメンバーを回す」形なので、それに対応する。

optimizer.py とは別ファイルにしている理由:
  ・optimizer.py は app.py が既に使っている「本番」の最適化関数を
    含む。そこに大きな変更を混ぜると、動いているものを壊すリスクがある。
  ・この関数はまだ GUI と繋がっていない試作段階。
  ・便構造への対応は大きい変更なので、影響範囲をファイルごと区切った。
    (app.py 側は今まで通り optimizer.run_optimization を使い続ける)

対応している制約・目的:
  ハード制約:
    ・車両の定員(capacity)
    ・車いす利用者は、車いす対応車にしか割り当てない
  ソフト制約(重み。weights.json の値を使う):
    ・w_travel  … 車の移動時間
    ・w_balance … 車どうしの担当時間の偏り
    ・w_ride    … 利用者の乗車時間(できるだけ遅く乗せる)
    ・w_window  … 便が目標時間内に施設へ戻れるか

  ・w_stability … 欠席などで組み直すとき、元のルート(base_vehicle_map)
                  からできるだけ車を変えないようにする重み

まだやっていないこと(次のステップ):
  ・道路の通行制約(軽自動車限定の道 など)
  ・OSRM は公開サーバーを使用。将来的に自前ホストや時間帯別の
    移動時間を検討する余地あり
────────────────────────────────────────────────────────────
"""
import pandas as pd
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

from optimizer import get_duration_matrix, load_weights

RIDE_HORIZON_SEC = 7200


def _solve_one_run(run_no, run_users: pd.DataFrame, vehicles: pd.DataFrame,
                    depot: dict, weights: dict, run_window_sec, base_vehicle_map=None):
    """
    1つの便について、複数車両での VRP を解いて訪問順を返す。

    base_vehicle_map: {user_id: 前回その人が乗っていた vehicle_id} を渡すと、
    w_stability > 0 のとき「できるだけ同じ車にする」方向に誘導する。
    （欠席などで急にルートを組み直すとき、変更を最小限にするための機能）
    """
    vehicles = vehicles.reset_index(drop=True)
    base_vehicle_map = base_vehicle_map or {}

    nodes = [{"id": 0, "lat": depot["lat"], "lng": depot["lng"],
              "name": depot.get("name", "デポ")}]
    for _, u in run_users.iterrows():
        nodes.append({"id": int(u["id"]), "lat": float(u["lat"]),
                      "lng": float(u["lng"]), "name": str(u["name"])})
    n = len(nodes)
    n_vehicles = len(vehicles)

    dist_matrix = get_duration_matrix(nodes)

    manager = pywrapcp.RoutingIndexManager(n, n_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    # Time 次元用(実秒数): 移動時間そのものを積み上げる
    def time_cb(a, b):
        return dist_matrix[manager.IndexToNode(a)][manager.IndexToNode(b)]
    time_idx = routing.RegisterTransitCallback(time_cb)

    w_travel = weights["w_travel"]
    w_stability = int(round(weights.get("w_stability", 0)))

    # アークコスト(ルートの良し悪しの評価): 車両ごとに別のコールバックを登録する。
    #   w_stability が 0 なら、どの車で計算しても同じ関数(全車両共通)。
    #   w_stability > 0 のときは、「この車 v に乗せると、その利用者の
    #   前回の車と違う」場合にだけ追加コストを乗せる。車ごとに罰則の対象が
    #   変わるので、SetArcCostEvaluatorOfVehicle で車両ごとに別関数を登録する。
    if w_stability > 0 and base_vehicle_map:
        for v in range(n_vehicles):
            vehicle_id = vehicles.iloc[v]["vehicle_id"]

            def cost_cb(a, b, _v=v, _vehicle_id=vehicle_id):
                b_node = manager.IndexToNode(b)
                sec = dist_matrix[manager.IndexToNode(a)][b_node]
                cost = w_travel * sec
                if b_node != 0:
                    u_id = nodes[b_node]["id"]
                    base_vehicle = base_vehicle_map.get(u_id)
                    if base_vehicle is not None and base_vehicle != _vehicle_id:
                        cost += w_stability
                return int(round(cost))

            cost_idx = routing.RegisterTransitCallback(cost_cb)
            routing.SetArcCostEvaluatorOfVehicle(cost_idx, v)
    else:
        def cost_cb(a, b):
            sec = dist_matrix[manager.IndexToNode(a)][manager.IndexToNode(b)]
            return int(round(w_travel * sec))
        cost_idx = routing.RegisterTransitCallback(cost_cb)
        routing.SetArcCostEvaluatorOfAllVehicles(cost_idx)

    routing.AddDimension(time_idx, 0, 100_000, True, "Time")
    time_dim = routing.GetDimensionOrDie("Time")
    time_dim.SetGlobalSpanCostCoefficient(int(round(weights["w_balance"])))

    # 利用者の乗車時間を短くする(optimizer.py と同じ考え方)
    w_ride = int(round(weights["w_ride"]))
    if w_ride > 0:
        for node in range(1, n):
            time_dim.SetCumulVarSoftLowerBound(manager.NodeToIndex(node), RIDE_HORIZON_SEC, w_ride)

    # 便の目標時間内に施設へ戻れるか(新しい項)
    w_window = int(round(weights.get("w_window", 0)))
    if w_window > 0 and run_window_sec:
        for v in range(n_vehicles):
            time_dim.SetCumulVarSoftUpperBound(routing.End(v), int(run_window_sec), w_window)

    # ハード制約(1): 車両の定員
    def demand_cb(idx):
        node = manager.IndexToNode(idx)
        return 0 if node == 0 else 1
    demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
    capacities = [int(c) for c in vehicles["capacity"].tolist()]
    routing.AddDimensionWithVehicleCapacity(demand_idx, 0, capacities, True, "Capacity")

    # ハード制約(2): 車いす利用者は車いす対応車のみ
    #   本来は routing.SetAllowedVehiclesForIndex() を使うのが素直だが、
    #   手元の ortools 9.15 ではこの関数の Python バインディングが壊れており
    #   (absl::Span 型のエラーで必ず失敗する)、代わりに
    #   VehicleVar(各ノードの「どの車に乗るか」を表す変数).SetValues() で
    #   同じ効果(許可された車IDだけに絞る)を実現している。
    wheelchair_vehicle_idx = [v for v, ok in enumerate(vehicles["wheelchair"].tolist()) if ok]
    if wheelchair_vehicle_idx:
        for node in range(1, n):
            u_id = nodes[node]["id"]
            is_wc = bool(run_users.loc[run_users["id"] == u_id, "wheelchair"].iloc[0])
            if is_wc:
                routing.VehicleVar(manager.NodeToIndex(node)).SetValues(wheelchair_vehicle_idx)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = int(weights["solver_time_limit_sec"])

    solution = routing.SolveWithParameters(params)
    if solution is None:
        raise RuntimeError(
            f"便{run_no}: 解が見つかりませんでした"
            "(定員が足りない、または車いす対応車が不足している可能性があります)"
        )

    rows = []
    for v in range(n_vehicles):
        idx = routing.Start(v)
        order = 1
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node != 0:
                pickup_sec = solution.Value(time_dim.CumulVar(idx))
                rows.append({
                    "run": run_no,
                    "vehicle_id": vehicles.iloc[v]["vehicle_id"],
                    "order": order,
                    "user_id": nodes[node]["id"],
                    "user": nodes[node]["name"],
                    "pickup_sec": pickup_sec,
                })
                order += 1
            idx = solution.Value(routing.NextVar(idx))
    return rows


def run_planner(users_df: pd.DataFrame, vehicles_df: pd.DataFrame, depot: dict,
                 weights_path: str = "weights.json", run_windows: dict = None,
                 base_vehicle_map: dict = None) -> pd.DataFrame:
    """
    便ごとに送迎ルートを計算する。

    Args:
        users_df   : 必須列 id, name, lat, lng, run, wheelchair
        vehicles_df: 必須列 vehicle_id, capacity, wheelchair
        depot      : {"lat": ..., "lng": ..., "name": ...(任意)}
        weights_path: weights.json のパス
        run_windows : {便番号(文字列 or 数値): 目標秒数}。省略時は w_window を使わない
        base_vehicle_map: {user_id: 前回のvehicle_id}。急な欠席などで組み直すとき、
                        w_stability > 0 なら「できるだけ同じ車を維持する」方向に働く

    Returns:
        DataFrame[run, vehicle_id, order, user_id, user, pickup_sec]
        (result.csv と同じ列に "run" と "pickup_sec" が加わった形)
    """
    weights = load_weights(weights_path)
    run_windows = run_windows or {}

    all_rows = []
    for run_no in sorted(users_df["run"].unique()):
        run_users = users_df[users_df["run"] == run_no]
        window = run_windows.get(str(run_no), run_windows.get(run_no))
        all_rows.extend(_solve_one_run(run_no, run_users, vehicles_df, depot, weights, window,
                                        base_vehicle_map=base_vehicle_map))

    return pd.DataFrame(all_rows)
