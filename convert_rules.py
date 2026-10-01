import pandas as pd
import numpy as np

def parse_coords(coord_str):
    """ '経度 緯度;経度 緯度' の文字列を [[緯度, 経度], ...] のリストに変換する """
    if pd.isna(coord_str):
        return None
    points = str(coord_str).split(';')
    coords = []
    for p in points:
        parts = p.split(' ')
        if len(parts) == 2:
            try:
                # OSRM等の標準である [lat, lon] の順序に合わせる
                lon, lat = float(parts[0]), float(parts[1])
                coords.append([lat, lon])
            except ValueError:
                pass
    return coords if coords else None

def main():
    input_file = "大阪府警_202607_k_2.1改変版.csv.xlsx"
    output_file = "data/traffic_rules.csv"
    
    print(f"[{input_file}] を読み込んでいます...")
    try:
        # Excelファイルの読み込み（1つ目のシート）
        df = pd.read_excel(input_file, sheet_name=0)
    except Exception as e:
        print(f"ファイルの読み込みに失敗しました。ファイル名や配置場所を確認してください: {e}")
        return

    # ルート計算に必要なカラムのみを抽出
    columns_to_keep = [
        '県別規制種別名称', 
        '規制条件',
        '規制時間1_開始', 
        '規制時間1_終了',
        '規制場所の経度緯度'
    ]
    df_filtered = df[columns_to_keep].copy()

    # 一方通行、進入禁止、右左折禁止など、ルートに影響する規制のみをフィルタリング
    target_regs = df_filtered[
        df_filtered['県別規制種別名称'].str.contains('通禁|一通|右禁|左禁|指定方向外', na=False)
    ].copy()

    # 座標文字列をリストに変換
    print("座標データと時間データをシステム向けに加工しています...")
    target_regs['coordinates'] = target_regs['規制場所の経度緯度'].apply(parse_coords)

    # 最終的な出力用にカラムを整理
    final_df = target_regs[['県別規制種別名称', '規制条件', '規制時間1_開始', '規制時間1_終了', 'coordinates']].copy()
    final_df.columns = ['規制種別', '条件詳細', '開始時間', '終了時間', '座標リスト(緯度,経度)']

    # 座標がうまく取得できなかったエラー行を削除
    final_df = final_df.dropna(subset=['座標リスト(緯度,経度)'])

    # CSVとして保存 (BOM付きUTF-8で文字化け防止)
    final_df.to_csv(output_file, index=False, encoding="utf-8-sig")
    
    print(f"完了しました！ {len(final_df)}件の規制データを [{output_file}] に出力しました。")

if __name__ == "__main__":
    main()