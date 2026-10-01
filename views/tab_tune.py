import streamlit as st
import pandas as pd
import os
import json
import itertools
import utils

try:
    from run_planner import run_planner
    from evaluate import evaluate
except ImportError:
    pass

def render():
    st.header("重みパラメータ調整")
    st.markdown("""
    `tune_weights.py` の機能を利用し、正解データのルートに最も近づく「乗車時間」「便の目標時間」の最適な重み設定を探索します。
    **A案反映:** 最適な設定が見つかった場合、次回のルート作成から使用される基本設定（`weights.json`）を自動的に上書き更新します。
    """)
    
    data_source = st.radio("チューニングに使用する正解データ", [
        "保存した実績データ (直近で手直し・保存したルートを使用)",
        "デモデータ (自動生成された仮のテストデータを使用)"
    ])
    
    col_w1, col_w2 = st.columns(2)
    with col_w1:
        w_ride_input = st.text_input("検証する w_ride の値（カンマ区切り）", value="0, 3, 5, 10, 20")
    with col_w2:
        w_window_input = st.text_input("検証する w_window の値（カンマ区切り）", value="0, 20, 50, 100")
        
    if st.button("チューニングを実行する", type="primary"):
        try:
            w_ride_options = [int(x.strip()) for x in w_ride_input.split(",")]
            w_window_options = [int(x.strip()) for x in w_window_input.split(",")]
            
            if "実績データ" in data_source:
                if not os.path.exists(utils.VETERAN_CSV):
                    st.error("実績データが見つかりません。先に「最適化結果」タブでルートを保存してください。")
                    st.stop()
                
                users = st.session_state.users_df.copy()
                users["run"] = 1
                users["wheelchair"] = users["wheelchair"].apply(lambda x: 1 if x == "あり" else 0)
                
                vehicles = st.session_state.vehicles_df.copy()
                vehicles["vehicle_id"] = vehicles["id"]
                vehicles["wheelchair"] = vehicles["wheelchair_support"].apply(lambda x: 1 if x == "あり" else 0)
                
                veteran = pd.read_csv(utils.VETERAN_CSV)
                depot_row = users[users["id"].astype(float) == 0.0].iloc[0] if 0.0 in users["id"].astype(float).values else {"lat": 34.8151, "lng": 135.6525}
                depot = {"lat": float(depot_row["lat"]), "lng": float(depot_row["lng"]), "name": "施設"}
                run_windows = {"1": 1800}
                
            else:
                demo_files = [
                    os.path.join(utils.DEMO_DIR, "users_demo.csv"),
                    os.path.join(utils.DEMO_DIR, "vehicles_demo.csv"),
                    os.path.join(utils.DEMO_DIR, "veteran_route_demo.csv"),
                    os.path.join(utils.DEMO_DIR, "depot_demo.json"),
                    os.path.join(utils.DEMO_DIR, "run_windows_demo.json")
                ]
                if not all(os.path.exists(f) for f in demo_files):
                    st.error(f"デモデータが `{utils.DEMO_DIR}` に揃っていません。先にターミナルで `python demo_data.py` を実行してください。")
                    st.stop()
                    
                users = pd.read_csv(demo_files[0])
                vehicles = pd.read_csv(demo_files[1])
                veteran = pd.read_csv(demo_files[2])
                with open(demo_files[3], encoding="utf-8") as f:
                    depot = json.load(f)
                with open(demo_files[4], encoding="utf-8") as f:
                    run_windows = json.load(f)

            with open(utils.WEIGHTS_JSON, encoding="utf-8") as f:
                base_weights = json.load(f)
            
            tmp_path = os.path.join(utils.DATA_DIR, "_tmp_weights.json")
            best = None
            log = []
            
            progress_text = "パラメータ探索中..."
            my_bar = st.progress(0, text=progress_text)
            
            total_steps = len(w_ride_options) * len(w_window_options)
            current_step = 0
            
            def score_of(res_dict):
                parts = [res_dict["便一致率"], res_dict["車一致率(便が合った人のうち)"]]
                order_score = res_dict["訪問順の一致度(便・車が合ったグループ内)"]
                parts.append(order_score if order_score is not None else 0.5)
                return sum(parts) / len(parts)

            for w_ride, w_window in itertools.product(w_ride_options, w_window_options):
                trial = dict(base_weights)
                trial["w_ride"] = w_ride
                trial["w_window"] = w_window
                trial["solver_time_limit_sec"] = 3
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(trial, f)

                system_df = run_planner(users, vehicles, depot, weights_path=tmp_path, run_windows=run_windows)
                result = evaluate(system_df, veteran)
                s = score_of(result)
                log.append({"w_ride": w_ride, "w_window": w_window, "score": round(s, 3), **result})
                
                if best is None or s > best["score"]:
                    best = {"w_ride": w_ride, "w_window": w_window, "score": s}
                
                current_step += 1
                my_bar.progress(current_step / total_steps, text=f"パラメータ探索中... {current_step}/{total_steps} 完了")

            if os.path.exists(tmp_path):
                os.remove(tmp_path)
                
            my_bar.empty()
            log_df = pd.DataFrame(log).sort_values("score", ascending=False)
            
            # ベストな設定を基本設定に上書き保存
            out = dict(base_weights)
            out["w_ride"] = best["w_ride"]
            out["w_window"] = best["w_window"]
            with open(utils.WEIGHTS_JSON, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)

            st.success(f"チューニング完了！ 最適な組み合わせ: w_ride = **{best['w_ride']}**, w_window = **{best['w_window']}** (スコア: {best['score']:.3f})")
            st.info("💡 AIをアップデートしました: 基本設定 (`weights.json`) を上記の最適値で上書き保存しました。次回の計画作成からこの基準が適用されます。")
            
            st.write("▼ 全探索結果（スコア順）")
            st.dataframe(log_df, use_container_width=True)

        except Exception as e:
            st.error(f"チューニング中にエラーが発生しました: {e}")