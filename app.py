import streamlit as st
import utils
# tab_tune の読み込みを削除しました
from views import tab_plan, tab_users, tab_vehicles, tab_result, tab_rules

# 1. ページ全体の初期設定
st.set_page_config(page_title="老人ホーム送迎ルート最適化システム", layout="wide")

# 2. ローカルファイルの準備・セッションステートの初期化
utils.initialize_system()

# 3. GUIの大枠の構築
st.title("送迎ルート最適化システム")
st.markdown("日々の送迎計画の作成と、利用者・車両・道路・規制データの管理を行います。")

# AIパラメータ調整タブを削除し、5つのタブにスッキリさせました
t_plan, t_users, t_vehicles, t_rules, t_result = st.tabs([
    "ダッシュボード＆計画作成", 
    "利用者管理", 
    "車両管理",  
    "通行規制管理",
    "最適化結果"
])

# 4. 各タブの描画処理を呼び出し
with t_plan:
    tab_plan.render()
with t_users:
    tab_users.render()
with t_vehicles:
    tab_vehicles.render()
with t_rules:
    tab_rules.render()
with t_result:
    tab_result.render()