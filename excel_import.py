"""
excel_import.py
────────────────────────────────────────────────────────────
「送迎データ_入力テンプレート.xlsx」(チームが手入力するファイル)を読み込み、
run_planner.py / evaluate.py がそのまま使える形の DataFrame に変換する。

Excelテンプレートの各シートは、1行目=見出し、2行目=グレーの説明文、
3行目からが実データ、という構造(はじめにシート参照)。
このモジュールは列の「位置」で読む(見出しの文言を多少変えても壊れないように)。
ただし列の並び順を変えると壊れるので、並び順を変えた場合はここも直すこと。

★ まだ実データは入っていない前提のコード。はなまるグループ様からの
   データが届いて、チームが手入力し始めたら、まずこのスクリプトを
   実データで試して、想定通り読めるか確認すること。

主な関数:
  load_veteran_route(xlsx_path)  -> 送迎実績_迎え を evaluate.py 用の形に
  load_vehicles(xlsx_path)       -> 車両マスタ を run_planner.py 用の形に
  load_users(xlsx_path)          -> 利用者マスタ を run_planner.py 用の形に
                                     (住所しか無い行は geocode.py で緯度経度を補う)
  assign_runs_from_history(...)  -> 利用者マスタには「便」の列が無いので、
                                     過去の送迎実績から「その人がいつも
                                     乗る便」を推定して付け足す
  load_all(xlsx_path)            -> 上記をまとめて呼ぶ便利関数
────────────────────────────────────────────────────────────
"""
import pandas as pd

from geocode import geocode_dataframe

SHEET_VETERAN = "送迎実績_迎え"
SHEET_USERS = "利用者マスタ"
SHEET_VEHICLES = "車両マスタ"

# Excelの列の並び順(位置で読むための列名リスト。テンプレートの列順と一致させること)
COLS_VETERAN = ["record_id", "date", "weekday", "run", "vehicle_id", "driver_id",
                 "order", "user_id", "planned_pickup", "actual_pickup",
                 "arrival_time", "note"]
COLS_USERS = ["id", "address", "lat", "lng", "wheelchair_mark", "prep_min", "assist_min",
              "care_level", "usual_weekday", "run_preference", "run_preference_note",
              "no_coride_ids", "staff_constraint", "note"]
COLS_VEHICLES = ["vehicle_id", "name", "type", "capacity", "wheelchair_mark",
                  "fixed_driver_id", "note"]


def _read_sheet_by_position(xlsx_path: str, sheet_name: str, colnames: list[str]) -> pd.DataFrame:
    """
    見出し行(1行目)と説明行(2行目)を飛ばして、3行目からを読む。
    列は「テンプレートで決めた並び順」で読み、colnames の名前を付け直す。
    """
    raw = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=None, skiprows=2)
    raw = raw.iloc[:, :len(colnames)]
    raw.columns = colnames
    # 全部の列が空(=空行)の行は捨てる
    raw = raw.dropna(how="all")
    return raw.reset_index(drop=True)


def _mark_to_bool(series: pd.Series) -> pd.Series:
    """"○" が入っていれば True、空欄なら False に変換する。"""
    return series.notna() & (series.astype(str).str.strip().isin(["○", "o", "O", "1", "true", "True"]))


def load_veteran_route(xlsx_path: str) -> pd.DataFrame:
    """
    送迎実績_迎え シートを、evaluate.py が期待する形
    [run, vehicle_id, order, user_id] (+参考情報)に変換する。
    利用者IDが空の行(記入例の空欄行など)は除外する。
    """
    df = _read_sheet_by_position(xlsx_path, SHEET_VETERAN, COLS_VETERAN)
    df = df.dropna(subset=["user_id", "run", "vehicle_id", "order"])
    df["run"] = df["run"].astype(int)
    df["order"] = df["order"].astype(int)
    df["user_id"] = df["user_id"].astype(int)
    df["visit_order"] = df["order"]  # evaluate.py は visit_order という列名を見る
    return df.reset_index(drop=True)


def load_vehicles(xlsx_path: str) -> pd.DataFrame:
    """車両マスタ を run_planner.py が期待する形 [vehicle_id, capacity, wheelchair] に変換する。"""
    df = _read_sheet_by_position(xlsx_path, SHEET_VEHICLES, COLS_VEHICLES)
    df = df.dropna(subset=["vehicle_id"])
    df["capacity"] = pd.to_numeric(df["capacity"], errors="coerce").fillna(4).astype(int)
    df["wheelchair"] = _mark_to_bool(df["wheelchair_mark"]).astype(int)
    return df.reset_index(drop=True)


def load_users(xlsx_path: str, do_geocode: bool = True) -> pd.DataFrame:
    """
    利用者マスタ を run_planner.py が期待する形
    [id, name, lat, lng, wheelchair, prep_min, assist_min, ...] に変換する。

    利用者マスタには氏名が入っていない(個人情報保護のため)ので、
    name には仮に "利用者<ID>" を入れる(表示用)。
    緯度・経度が空欄で住所だけ入っている行は、do_geocode=True なら
    geocode.py で自動的に変換する(Nominatimを使うため多少時間がかかる)。
    """
    df = _read_sheet_by_position(xlsx_path, SHEET_USERS, COLS_USERS)
    df = df.dropna(subset=["id"])
    df["id"] = df["id"].astype(int)
    df["name"] = df["id"].apply(lambda i: f"利用者{i}")
    df["wheelchair"] = _mark_to_bool(df["wheelchair_mark"]).astype(int)
    df["prep_min"] = pd.to_numeric(df["prep_min"], errors="coerce").fillna(0)
    df["assist_min"] = pd.to_numeric(df["assist_min"], errors="coerce").fillna(0)
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lng"] = pd.to_numeric(df["lng"], errors="coerce")

    if do_geocode:
        missing = df["lat"].isna() | df["lng"].isna()
        if missing.any():
            print(f"[info] {missing.sum()} 件の利用者は緯度経度が未入力のため、"
                  "住所からジオコーディングします(Nominatim, 1件1秒程度)")
            df = geocode_dataframe(df, address_col="address", lat_col="lat", lng_col="lng")

    return df.reset_index(drop=True)


def assign_runs_from_history(users_df: pd.DataFrame, veteran_df: pd.DataFrame,
                              default_runs=(1, 2, 3, 4)) -> pd.DataFrame:
    """
    利用者マスタには「便」の列が無い(便は日によって変わりうるため)。
    run_planner.py を動かすには各利用者に便を割り当てる必要があるので、
    ここでは簡易的に「過去の送迎実績で一番多く使っている便」を採用する。
    履歴が無い利用者は、default_runs に順番に割り振る(ラウンドロビン)。

    ★ これは暫定的なルール。本来は「便の希望」列(早め/遅め)や、
       施設側の当日の判断を反映すべきだが、そこは未設計(次のステップ)。
    """
    users_df = users_df.copy()
    if veteran_df is not None and not veteran_df.empty:
        most_common_run = (
            veteran_df.groupby("user_id")["run"]
            .agg(lambda s: s.value_counts().idxmax())
        )
    else:
        most_common_run = pd.Series(dtype=int)

    runs = []
    for i, u in enumerate(users_df["id"]):
        if u in most_common_run.index:
            runs.append(int(most_common_run.loc[u]))
        else:
            runs.append(default_runs[i % len(default_runs)])
    users_df["run"] = runs
    return users_df


def load_all(xlsx_path: str, do_geocode: bool = True):
    """
    3つのシートをまとめて読み込み、run_planner.py にそのまま渡せる形で返す。

    Returns:
        (users_df, vehicles_df, veteran_df)
    """
    veteran_df = load_veteran_route(xlsx_path)
    vehicles_df = load_vehicles(xlsx_path)
    users_df = load_users(xlsx_path, do_geocode=do_geocode)
    users_df = assign_runs_from_history(users_df, veteran_df)
    return users_df, vehicles_df, veteran_df


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "送迎データ_入力テンプレート.xlsx"
    users_df, vehicles_df, veteran_df = load_all(path, do_geocode=False)
    print(f"利用者: {len(users_df)}件, 車両: {len(vehicles_df)}件, 送迎実績: {len(veteran_df)}件")
    print(users_df.head())
