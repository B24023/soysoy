"""
geocode.py
────────────────────────────────────────────────────────────
住所の文字列を緯度経度に変換する(ジオコーディング)。

はなまるグループ様からいただく利用者データは「住所」の形で
届く想定(運転経路記述書・利用者マスタも住所ベース)。
optimizer.py / run_planner.py は緯度経度でないと距離計算(OSRM)が
できないので、その橋渡し役。

使っているサービス: Nominatim(OpenStreetMapの無料ジオコーダー)
  https://nominatim.org/release-docs/latest/api/Search/

★ Nominatim の利用ルール(必ず守ること):
  ・1秒に1リクエストまで(サーバーに負荷をかけない)
  ・User-Agent(誰が何のために使っているか)を必ず送る
  ・結果はキャッシュして、同じ住所に何度も問い合わせない
  上記に反すると、はなまるグループ様のIPアドレスやこちらの環境が
  ブロックされる可能性があるため、このモジュールは自動でキャッシュと
  待機(レート制限)をしている。

使い方:
    from geocode import geocode_address, geocode_dataframe

    result = geocode_address("大阪府枚方市山之上北町5番1号")
    # -> {"lat": 34.80..., "lng": 135.65..., "display_name": "..."} または None

    df = geocode_dataframe(df, address_col="address")
    # df に "lat" "lng" 列が追加される(既に値がある行は再取得しない)

CLIとしても使える:
    python geocode.py "大阪府枚方市山之上北町5番1号"
────────────────────────────────────────────────────────────
"""
import json
import os
import time

import pandas as pd
import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "soichalle-hanamaru-project/1.0 (student project; contact e1b24096@oit.ac.jp)"
CACHE_PATH = os.path.join(os.path.dirname(__file__), "data", "geocode_cache.json")
MIN_INTERVAL_SEC = 1.1  # Nominatim の利用ルール(1秒1リクエストまで)を守るための待機時間

_last_request_time = 0.0


def _load_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def geocode_address(address: str, cache: dict = None) -> dict | None:
    """
    住所1件を緯度経度に変換する。
    cache を渡すとそのdictを読み書きする(バッチ処理のとき使い回すため)。
    渡さない場合は、このモジュールのファイルキャッシュを直接読み書きする。

    戻り値: {"lat": float, "lng": float, "display_name": str} または
            見つからなければ None
    """
    global _last_request_time

    address = address.strip()
    if not address:
        return None

    own_cache = cache is None
    if own_cache:
        cache = _load_cache()

    if address in cache:
        return cache[address]

    # レート制限: 前回のリクエストから MIN_INTERVAL_SEC 秒空ける
    elapsed = time.time() - _last_request_time
    if elapsed < MIN_INTERVAL_SEC:
        time.sleep(MIN_INTERVAL_SEC - elapsed)

    resp = requests.get(
        NOMINATIM_URL,
        params={"q": address, "format": "json", "limit": 1, "countrycodes": "jp"},
        headers={"User-Agent": USER_AGENT},
        timeout=10,
    )
    _last_request_time = time.time()

    results = resp.json() if resp.status_code == 200 else []
    if not results:
        cache[address] = None
    else:
        top = results[0]
        cache[address] = {
            "lat": float(top["lat"]),
            "lng": float(top["lon"]),
            "display_name": top.get("display_name", ""),
        }

    if own_cache:
        _save_cache(cache)

    return cache[address]


def geocode_dataframe(df: pd.DataFrame, address_col: str = "address",
                       lat_col: str = "lat", lng_col: str = "lng") -> pd.DataFrame:
    """
    DataFrame の住所列を一括でジオコーディングし、緯度経度の列を追加/更新する。
    既に lat/lng に値が入っている行はスキップする(無駄なAPI呼び出しを避ける)。
    見つからなかった住所は lat/lng が NaN のままになる(要目視確認)。
    """
    df = df.copy()
    if lat_col not in df.columns:
        df[lat_col] = pd.NA
    if lng_col not in df.columns:
        df[lng_col] = pd.NA

    cache = _load_cache()
    not_found = []

    for i, row in df.iterrows():
        if pd.notna(row.get(lat_col)) and pd.notna(row.get(lng_col)):
            continue
        address = str(row.get(address_col, "")).strip()
        if not address:
            continue
        result = geocode_address(address, cache=cache)
        if result is None:
            not_found.append(address)
            continue
        df.at[i, lat_col] = result["lat"]
        df.at[i, lng_col] = result["lng"]

    _save_cache(cache)

    if not_found:
        print(f"[warn] {len(not_found)} 件の住所が見つかりませんでした(要目視確認):")
        for a in not_found:
            print(f"  - {a}")

    return df


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("使い方: python geocode.py \"住所\"")
        sys.exit(1)

    address = " ".join(sys.argv[1:])
    result = geocode_address(address)
    if result is None:
        print(f"見つかりませんでした: {address}")
    else:
        print(f"{address}")
        print(f"  lat={result['lat']}, lng={result['lng']}")
        print(f"  display_name={result['display_name']}")
