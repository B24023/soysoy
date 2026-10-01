"""
evaluate.py
────────────────────────────────────────────────────────────
システム(run_planner.py)が出したルートと、「正解」とするルート
(本来はベテランの実績データ。今はデモ用の合成データ)を比較して、
一致度を数値で出す。

3つの指標:
  ① 便一致率              … その利用者が正解と同じ便に割り当てられたか
  ② 車一致率(便が合った人のうち) … 同じ便の中で、正解と同じ車に乗ったか
  ③ 訪問順の一致度(便・車が合ったグループ内)
                          … 同じ車の中での訪問順が、正解とどれくらい近いか
                            (共通の利用者どうしのペアで、前後関係が
                             一致している割合。0〜1、1が完全一致)

使い方:
    python evaluate.py system.csv veteran.csv
or  Python から:
    from evaluate import evaluate
    result = evaluate(system_df, veteran_df)
────────────────────────────────────────────────────────────
"""
from itertools import combinations

import pandas as pd


def _pair_concordance(order_a: dict, order_b: dict):
    """
    同じ利用者集合について、2つの順序がどれくらい一致しているかを 0〜1 で返す。
    共通する利用者のペアのうち、前後関係(どちらが先か)が一致する割合。
    利用者が1人以下なら比較できないので None を返す。
    """
    common = set(order_a) & set(order_b)
    if len(common) < 2:
        return None
    concordant = 0
    total = 0
    for a, b in combinations(common, 2):
        total += 1
        same_direction = (order_a[a] < order_a[b]) == (order_b[a] < order_b[b])
        if same_direction:
            concordant += 1
    return concordant / total


def evaluate(system_df: pd.DataFrame, veteran_df: pd.DataFrame) -> dict:
    """
    system_df : run_planner() の出力。列 [run, vehicle_id, order, user_id, ...]
    veteran_df: 正解データ。列 [run, vehicle_id, visit_order, user_id, ...]
                (Excelテンプレート「送迎実績_迎え」/ demo_data.py の出力と同じ考え方)
    """
    sys_map = {int(r.user_id): (r.run, r.vehicle_id, r.order) for r in system_df.itertuples()}
    vet_map = {int(r.user_id): (r.run, r.vehicle_id, r.visit_order) for r in veteran_df.itertuples()}

    common_users = set(sys_map) & set(vet_map)
    if not common_users:
        raise ValueError("システムとベテランデータに共通する利用者IDがありません")

    # ① 便一致率
    run_match = sum(1 for u in common_users if sys_map[u][0] == vet_map[u][0])
    run_match_rate = run_match / len(common_users)

    # ② 車一致率(便が一致した人だけを対象。便が違えば車も違うとみなす)
    same_run_users = [u for u in common_users if sys_map[u][0] == vet_map[u][0]]
    vehicle_match = sum(1 for u in same_run_users if sys_map[u][1] == vet_map[u][1])
    vehicle_match_rate = (vehicle_match / len(same_run_users)) if same_run_users else 0.0

    # ③ 訪問順の一致度(便・車の両方が一致したグループ内で)
    groups: dict[tuple, list[int]] = {}
    for u in same_run_users:
        if sys_map[u][1] != vet_map[u][1]:
            continue
        key = (sys_map[u][0], sys_map[u][1])
        groups.setdefault(key, []).append(u)

    order_scores = []
    for users_in_group in groups.values():
        order_a = {u: sys_map[u][2] for u in users_in_group}
        order_b = {u: vet_map[u][2] for u in users_in_group}
        score = _pair_concordance(order_a, order_b)
        if score is not None:
            order_scores.append(score)
    order_score = sum(order_scores) / len(order_scores) if order_scores else None

    return {
        "比較した利用者数": len(common_users),
        "便一致率": round(run_match_rate, 3),
        "車一致率(便が合った人のうち)": round(vehicle_match_rate, 3),
        "訪問順の一致度(便・車が合ったグループ内)":
            round(order_score, 3) if order_score is not None else None,
    }


def evaluate_from_csv(system_csv: str, veteran_csv: str) -> dict:
    system_df = pd.read_csv(system_csv)
    veteran_df = pd.read_csv(veteran_csv)
    return evaluate(system_df, veteran_df)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="システムのルートとベテランのルートの一致度を測る")
    parser.add_argument("system_csv", help="run_planner.py の出力(またはそれを保存したCSV)")
    parser.add_argument("veteran_csv", help="正解データ(ベテランの実績、または demo データ)")
    args = parser.parse_args()

    result = evaluate_from_csv(args.system_csv, args.veteran_csv)
    for k, v in result.items():
        print(f"{k}: {v}")
