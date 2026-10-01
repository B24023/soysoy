"""
demo_absence_scenario.py
────────────────────────────────────────────────────────────
システムの一番の見せ場「急な欠席が出たとき、元のルートをできるだけ
崩さずに組み直せるか」を、合成デモデータで検証するスクリプト。

やっていること:
  1. 通常の便構成でプランを1回計算する(base_vehicle_map = 誰がどの車か)
  2. その中の1人を「今日は欠席」として除外する
  3. 欠席が出た便だけを、条件を変えて2通り計算し直す
       (A) w_stability = 0  … 何も考慮せず、毎回ゼロから最適な形に組み直す
       (B) w_stability > 0 … 元の車からできるだけ変えないようにする
  4. 「欠席した人以外で、車が変わってしまった人数」を数えて比較する

期待される結果: (B) のほうが変更が少ない(数が少ない)はず。
車を変える人が少ないほど、若手職員でも当日の変更に対応しやすく、
利用者への「車が変わります」という連絡も減らせる。

★ demo_data.py で作った合成データを使用。実データではない。
────────────────────────────────────────────────────────────
"""
import json
import os

import pandas as pd

from run_planner import run_planner

HERE = os.path.dirname(__file__)
DEMO_DIR = os.path.join(HERE, "data", "demo")


def load_demo():
    users = pd.read_csv(os.path.join(DEMO_DIR, "users_demo.csv"))
    vehicles = pd.read_csv(os.path.join(DEMO_DIR, "vehicles_demo.csv"))
    with open(os.path.join(DEMO_DIR, "depot_demo.json"), encoding="utf-8") as f:
        depot = json.load(f)
    with open(os.path.join(DEMO_DIR, "run_windows_demo.json"), encoding="utf-8") as f:
        run_windows = json.load(f)
    return users, vehicles, depot, run_windows


def _tighten_capacity(vehicles: pd.DataFrame) -> pd.DataFrame:
    """
    デモ用車両は定員に余裕がありすぎて、誰が欠けても再配置が起きにくい
    (どの車にも空きがあるので、わざわざ車を変える理由がない)。
    この検証スクリプトの中だけ、定員を絞った“混雑した日”を想定して、
    w_stability の効果が見えやすい条件を作る。
    (vehicles_demo.csv 本体は書き換えない)
    """
    tight = vehicles.copy()
    tight["capacity"] = tight["capacity"].apply(lambda c: max(2, c // 2))
    return tight


def main():
    users, vehicles, depot, run_windows = load_demo()
    tight_vehicles = _tighten_capacity(vehicles)
    print("(検証用に、この便の車の定員を一時的に半分に絞って混雑を作っています: "
          f"{dict(zip(vehicles.vehicle_id, vehicles.capacity))} → "
          f"{dict(zip(tight_vehicles.vehicle_id, tight_vehicles.capacity))})\n")

    print("① まず通常どおりのプランを1回計算(これを「元のルート」とする)")
    base_df = run_planner(users, tight_vehicles, depot, weights_path="weights.json", run_windows=run_windows)
    base_vehicle_map = dict(zip(base_df["user_id"], base_df["vehicle_id"]))

    # 一番人数が多い便を「欠席が出た便」として選ぶ
    target_run = users["run"].value_counts().idxmax()
    run_users = users[users["run"] == target_run]
    absent_user = run_users.iloc[0]
    print(f"\n② 便{target_run}({len(run_users)}人)で、"
          f"利用者ID={absent_user['id']}({absent_user['name']}) が急に欠席したと仮定")

    remaining = users[(users["run"] == target_run) & (users["id"] != absent_user["id"])]
    other_ids = set(remaining["id"])

    print(f"\n③ 便{target_run}だけを2通りの条件で組み直す(残り{len(remaining)}人)")

    # (A) w_stability = 0(考慮なし)
    with open(os.path.join(DEMO_DIR, "_tmp_w0.json"), "w", encoding="utf-8") as f:
        json.dump({"w_travel": 1.0, "w_balance": 100, "w_ride": 5, "w_window": 0,
                   "w_stability": 0, "solver_time_limit_sec": 3}, f)
    df_a = run_planner(remaining, tight_vehicles, depot,
                        weights_path=os.path.join(DEMO_DIR, "_tmp_w0.json"),
                        run_windows=run_windows)

    # (B) w_stability = 300(元の車を維持したい。w_balance=100と拮抗させるため大きめ)
    with open(os.path.join(DEMO_DIR, "_tmp_w300.json"), "w", encoding="utf-8") as f:
        json.dump({"w_travel": 1.0, "w_balance": 100, "w_ride": 5, "w_window": 0,
                   "w_stability": 300, "solver_time_limit_sec": 3}, f)
    df_b = run_planner(remaining, tight_vehicles, depot,
                        weights_path=os.path.join(DEMO_DIR, "_tmp_w300.json"),
                        run_windows=run_windows, base_vehicle_map=base_vehicle_map)

    for p in ["_tmp_w0.json", "_tmp_w300.json"]:
        full = os.path.join(DEMO_DIR, p)
        if os.path.exists(full):
            os.remove(full)

    def changed_count(df):
        new_map = dict(zip(df["user_id"], df["vehicle_id"]))
        changed = [u for u in other_ids if new_map.get(u) != base_vehicle_map.get(u)]
        return changed

    changed_a = changed_count(df_a)
    changed_b = changed_count(df_b)

    print(f"\n④ 結果: 欠席者以外で「車が変わった人数」")
    print(f"   (A) w_stability=0   : {len(changed_a)} / {len(other_ids)} 人 変更  {sorted(changed_a)}")
    print(f"   (B) w_stability=300 : {len(changed_b)} / {len(other_ids)} 人 変更  {sorted(changed_b)}")

    if len(changed_b) <= len(changed_a):
        print("\n→ w_stability を入れたほうが、無関係な利用者への影響(車の変更)が少ない、"
              "または同じという結果になりました。")
    else:
        print("\n→ 今回のデモデータでは w_stability の効果が確認できませんでした"
              "(サンプルが小さいため。パラメータや人数を変えて再確認する余地あり)。")


if __name__ == "__main__":
    main()
