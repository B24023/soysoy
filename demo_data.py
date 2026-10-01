"""
demo_data.py
────────────────────────────────────────────────────────────
本物のデータ(はなまるグループ様からの提供分)が届く前に、
run_planner.py / evaluate.py / tune_weights.py を動かして確認するための
「合成(ダミー)データ」を作るスクリプト。

★ 実在の利用者情報は一切含まれていない。
★ 座標はデポ(枚方の事業所付近)の周りにランダムにばらまいた架空の値。
★ 車両の車いす対応フラグ・便ごとの目標時間も、コードのテスト用の仮設定。
  （実際の値は、はなまるグループ様へのヒアリングで確認する）
★「ベテランのルート」も、簡単なルール(デポから遠い人を先に乗せる)で
  機械的に作った疑似データ。本物のベテランの判断ではない。

実行方法:
    python demo_data.py
data/demo/ フォルダに CSV / JSON が生成される。
────────────────────────────────────────────────────────────
"""
import json
import os
import random
from math import radians, sin, cos, asin, sqrt

import pandas as pd

HERE = os.path.dirname(__file__)
OUT_DIR = os.path.join(HERE, "data", "demo")
os.makedirs(OUT_DIR, exist_ok=True)

random.seed(42)

# 施設(デポ)の座標。枚方市山之上北町付近(Nominatimでの概算値)。
DEPOT = {
    "id": 0,
    "name": "デポ(枚方事業所・仮)",
    "lat": 34.8040,
    "lng": 135.6532,
    "address": "大阪府枚方市山之上北町(概算・要確認)",
}

N_USERS = 18
RUNS = [1, 2, 3, 4]


def haversine_km(lat1, lng1, lat2, lng2):
    """2点間の直線距離(km)。デモの「ベテラン風ルート」作成にだけ使う簡易計算。"""
    R = 6371
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dl = radians(lng2 - lng1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * R * asin(sqrt(a))


def make_users() -> pd.DataFrame:
    rows = []
    for i in range(1, N_USERS + 1):
        dlat = random.uniform(-0.018, 0.018)
        dlng = random.uniform(-0.022, 0.022)
        rows.append({
            "id": i,
            "name": f"利用者{i:02d}",
            "lat": round(DEPOT["lat"] + dlat, 6),
            "lng": round(DEPOT["lng"] + dlng, 6),
            "address": "(架空の住所・デモ用)",
            "run": random.choice(RUNS),
            "prep_min": random.choice([3, 5, 5, 8, 10]),       # 準備時間(分)の仮値
            "assist_min": random.choice([0, 0, 3, 5, 8]),      # 介助時間(分)の仮値
            "wheelchair": 1 if i in (4, 11) else 0,            # テスト用に2名だけ車いす想定
            "care_level": random.choice(["要支援", "要支援", "要介護", "未定"]),
        })
    return pd.DataFrame(rows)


def make_vehicles() -> pd.DataFrame:
    # 車両名は運転経路記述書と同じ。車いす対応・定員はテスト用の仮設定(要確認)。
    return pd.DataFrame([
        {"vehicle_id": "car1", "name": "ステラ",      "type": "軽",     "capacity": 4, "wheelchair": 0},
        {"vehicle_id": "car2", "name": "デイズ",      "type": "軽",     "capacity": 4, "wheelchair": 0},
        {"vehicle_id": "car3", "name": "タント",      "type": "軽",     "capacity": 4, "wheelchair": 0},
        {"vehicle_id": "car4", "name": "ヴォクシー",   "type": "ミニバン", "capacity": 6, "wheelchair": 1},
        {"vehicle_id": "car5", "name": "ヴォクシー2",  "type": "ミニバン", "capacity": 6, "wheelchair": 0},
    ])


def make_run_windows() -> dict:
    """各便の「開始から施設に戻るまでの目標時間(秒)」。記述書のヘッダーを参考にした仮値。"""
    return {"1": 1800, "2": 2400, "3": 1800, "4": 900}


def make_veteran_route(users: pd.DataFrame, vehicles: pd.DataFrame) -> pd.DataFrame:
    """
    「ベテランならこう組むはず」を模した合成の正解データ。
    ルール: 各便の中で、デポから遠い利用者から先に車へ割り振る
           (「乗車時間を短くする配慮」を単純なルールで再現)。
           定員を超えたら次の車に切り替える。車いす利用者は対応車へ。
    ※ 実際のベテラン職員の判断そのものではない。コードのテスト専用。
    """
    rows = []
    record_no = 1
    wc_vehicles = vehicles[vehicles["wheelchair"] == 1]
    normal_vehicles = vehicles

    for run in RUNS:
        run_users = users[users["run"] == run].copy()
        if run_users.empty:
            continue
        run_users["dist_from_depot"] = run_users.apply(
            lambda r: haversine_km(DEPOT["lat"], DEPOT["lng"], r["lat"], r["lng"]), axis=1)
        run_users = run_users.sort_values("dist_from_depot", ascending=False)

        cap_used = {vid: 0 for vid in vehicles["vehicle_id"]}
        order = {vid: 1 for vid in vehicles["vehicle_id"]}

        for _, u in run_users.iterrows():
            pool = wc_vehicles if u["wheelchair"] == 1 else normal_vehicles
            # 空きがある車の中から先頭を選ぶ(簡易ルール)
            chosen = None
            for _, v in pool.iterrows():
                if cap_used[v["vehicle_id"]] < v["capacity"]:
                    chosen = v["vehicle_id"]
                    break
            if chosen is None:
                chosen = pool.iloc[0]["vehicle_id"]  # 定員オーバーでも割り当てる(デモなので簡易処理)

            rows.append({
                "record_id": f"R{record_no:04d}",
                "date": "2026-09-14",
                "weekday": "月",
                "run": run,
                "vehicle_id": chosen,
                "visit_order": order[chosen],
                "user_id": int(u["id"]),
                "note": "合成データ(コードのテスト専用。実データではない)",
            })
            cap_used[chosen] += 1
            order[chosen] += 1
            record_no += 1

    return pd.DataFrame(rows)


def main():
    users = make_users()
    vehicles = make_vehicles()
    veteran = make_veteran_route(users, vehicles)
    windows = make_run_windows()

    users.to_csv(os.path.join(OUT_DIR, "users_demo.csv"), index=False)
    vehicles.to_csv(os.path.join(OUT_DIR, "vehicles_demo.csv"), index=False)
    veteran.to_csv(os.path.join(OUT_DIR, "veteran_route_demo.csv"), index=False)
    with open(os.path.join(OUT_DIR, "depot_demo.json"), "w", encoding="utf-8") as f:
        json.dump(DEPOT, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, "run_windows_demo.json"), "w", encoding="utf-8") as f:
        json.dump(windows, f, ensure_ascii=False, indent=2)

    print(f"users: {len(users)} 件, vehicles: {len(vehicles)} 件, veteran rows: {len(veteran)} 件")
    print(f"保存先: {OUT_DIR}")


if __name__ == "__main__":
    main()
