# 老人ホーム送迎ルート最適化

## 主な昨日
- **利用者・車両管理**: 要介護度や車いす対応、稼働曜日の設定
- **ルート最適化**: OR-Toolsを用いた効率的な訪問順の計算（定員オーバー時の多便運行対応）
- **交通規制回避**: 独自の規制データ（CSV）に基づく指定時間帯のスクールゾーンや一方通行の自動迂回
- **配車表出力**: 実際の座席レイアウトに合わせた現場用Excelファイル（.xlsx）の生成

## 環境構築と実行方法


```bash
git clone https://github.com/B24023/soysoy

pip install -r requirements.txt

streamlit run app.py
