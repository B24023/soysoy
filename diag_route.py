"""
ルーティング API 診断スクリプト
各エンジンに実際にリクエストを投げてエラーを特定する
"""
import sys, json
sys.stdout.reconfigure(encoding='utf-8')

# テスト座標（大阪市内2点: 梅田 → 難波）
DEPOT = {"lat": 34.6937, "lng": 135.5023}
PT_A  = {"lat": 34.6818, "lng": 135.4862}

def test_osrm_get():
    """従来の OSRM GET 方式"""
    import requests
    coords = f"{DEPOT['lng']},{DEPOT['lat']};{PT_A['lng']},{PT_A['lat']}"
    url = f"http://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson"
    print(f"\n[OSRM GET] {url}")
    try:
        r = requests.get(url, timeout=15)
        print(f"  Status: {r.status_code}")
        d = r.json()
        print(f"  code:   {d.get('code')}")
        if d.get("routes"):
            route = d["routes"][0]
            print(f"  distance: {route['distance']/1000:.2f} km")
            print(f"  duration: {route['duration']/60:.1f} min")
            print(f"  coords[0]: {route['geometry']['coordinates'][0]}")
            print("  --> OK")
        else:
            print(f"  --> FAIL: {json.dumps(d)[:200]}")
    except Exception as e:
        print(f"  --> EXCEPTION: {e}")


def test_osrm_get_exclude():
    """OSRM GET + exclude=ferry"""
    import requests
    coords = f"{DEPOT['lng']},{DEPOT['lat']};{PT_A['lng']},{PT_A['lat']}"
    url = f"http://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson&exclude=ferry"
    print(f"\n[OSRM GET + exclude=ferry] {url}")
    try:
        r = requests.get(url, timeout=15)
        print(f"  Status: {r.status_code}")
        d = r.json()
        print(f"  code:   {d.get('code')}")
        if d.get("routes"):
            print(f"  distance: {d['routes'][0]['distance']/1000:.2f} km")
            print("  --> OK")
        else:
            print(f"  --> FAIL: {json.dumps(d)[:200]}")
    except Exception as e:
        print(f"  --> EXCEPTION: {e}")


def test_valhalla():
    """Valhalla POST"""
    import requests
    body = {
        "locations": [
            {"lon": DEPOT["lng"], "lat": DEPOT["lat"]},
            {"lon": PT_A["lng"],  "lat": PT_A["lat"]},
        ],
        "costing": "auto",
        "units": "km"
    }
    for url in [
        "https://valhalla1.openstreetmap.de/route",
        "https://valhalla.openstreetmap.de/route",
    ]:
        print(f"\n[Valhalla POST] {url}")
        try:
            r = requests.post(url, json=body, timeout=12)
            print(f"  Status: {r.status_code}")
            if r.status_code == 200:
                d = r.json()
                km = d["trip"]["summary"]["length"]
                sec = d["trip"]["summary"]["time"]
                print(f"  distance: {km:.2f} km / {sec/60:.1f} min")
                print("  --> OK")
            else:
                print(f"  --> FAIL: {r.text[:200]}")
        except Exception as e:
            print(f"  --> EXCEPTION: {e}")


def test_osrm_table():
    """OSRM /table でサーバー疎通確認"""
    import requests
    coords = f"{DEPOT['lng']},{DEPOT['lat']};{PT_A['lng']},{PT_A['lat']}"
    url = f"http://router.project-osrm.org/table/v1/driving/{coords}"
    print(f"\n[OSRM TABLE] {url}")
    try:
        r = requests.get(url, timeout=10)
        print(f"  Status: {r.status_code} --> {'OK' if r.status_code==200 else 'FAIL'}")
    except Exception as e:
        print(f"  --> EXCEPTION: {e}")


def test_polyline_decode():
    """polyline ライブラリのデコード確認"""
    try:
        import polyline
        # Valhalla サンプルエンコード
        encoded = "me{cF{~shXeAg@"
        dec = polyline.decode(encoded, 6)
        print(f"\n[polyline decode] OK: {dec[:2]}")
    except Exception as e:
        print(f"\n[polyline decode] EXCEPTION: {e}")


if __name__ == "__main__":
    print("=" * 55)
    print("ルーティング API 診断")
    print("=" * 55)
    test_osrm_get()
    test_osrm_get_exclude()
    test_valhalla()
    test_osrm_table()
    test_polyline_decode()
    print("\n" + "=" * 55)
