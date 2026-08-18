# 空品測站連續觀測台

兩個環境部資料來源並列：

| 來源 | 輸入什麼 | 解析度 | 範圍 |
|---|---|---|---|
| **智慧城鄉空品微型感測器** | 裝置編號（**不是**裝置名稱），例如 `13580653094` | 3 分鐘 | 全國約 10,999 點，2017 年 6 月起 |
| **國家空品測站** | 測站名稱，例如 `板橋` | 每小時 | 77 站，1998 年起 |

同一個測項（例如兩邊都有的 PM2.5）會疊在同一張圖上，用不同顏色區分測站，
可以直接看微型感測器相對於法規等級測站的偏差方向與時間結構。

純靜態網頁，無後端、無 build step、無 API key。

---

## 檔案

| 檔案 | 用途 |
|---|---|
| `index.html` | 整個網站，單一檔案 |
| `worker.js` | Cloudflare Worker CORS proxy，**只有被 CORS 擋下時才需要** |
| `README.md` | 本說明 |

---

## 部署到 GitHub Pages

```bash
# 1. 建 repo（名稱自取，例如 air-observer）
git init
git add index.html worker.js README.md
git commit -m "空品測站連續觀測台"
git branch -M main
git remote add origin https://github.com/<你的帳號>/air-observer.git
git push -u origin main
```

2. GitHub repo → **Settings → Pages**
3. Source 選 **Deploy from a branch**，Branch 選 `main` / `(root)`，Save
4. 約 1 分鐘後上線：`https://<你的帳號>.github.io/air-observer/`

> 檔名必須是 `index.html`（放在 repo 根目錄），Pages 才會直接開啟。

---

## 微型感測器：裝置編號怎麼來

在**空氣網**（<https://wot.moenv.gov.tw>）地圖上點任一感測點，詳細面板中間那串粗體字就是裝置編號：

```
13580653094          ← 純數字，對應 properties/stationID
TW040203A0506884     ← TW 開頭，對應 properties/locationId
```

**這是裝置編號，不是裝置名稱。** 輸入「中山國小」「XX 路口」之類的地點名稱查不到，
那些是顯示用的名稱，不是 API 的查詢鍵。

輸入值會依序嘗試四種比對，命中即停：

| 順序 | 比對欄位 | 範例 |
|---|---|---|
| 1 | `properties/locationId` | `TW040203A0506884` |
| 2 | `properties/stationID` | `13580653094` |
| 3 | `name` 完全相符 | `智慧城鄉空品微型感測器-13580653094` |
| 4 | 名稱片段（`substringof` / `contains`） | 部分關鍵字 |

也可以展開「改用座標找附近的微型感測器」，用經緯度 + 半徑搜尋。

---

## 國家空品測站：打測站名稱

切到「國家空品測站」分頁，直接輸入測站名稱：

```
板橋    萬華    三重    土城    菜寮    新莊
```

不確定名稱就按 **列出國家測站**，會把該 endpoint 上的測站全部列出來，點「加入」即可。

比對順序：`properties/stationName` → `name` → `properties/stationID` → 名稱片段。

> 國家測站的 endpoint（`STA_AirQuality_v2`）同一個服務裡同時收錄環境部國家測站與中研院校園微型感測器，
> 本頁以 `properties/authority` 判別並優先列出環境部的站，清單上也會標出 authority。

---

## 測項與圖表

- 加入測站後會自動讀取該站的 datastream 清單，產生**可複選**的測項勾選列；
  標「共同」的測項代表兩個來源都有，會疊在同一張圖上。
- **每個測項一張圖**，共用同一條時間軸；同一張圖裡多站以不同顏色區分。
- 細線＝微型感測器（3 分鐘值）；粗線加空心圓點＝國家空品測站（小時值）。
- 「重點測項」決定下方小時 pattern 與統計表要看哪一個測項（預設 PM2.5）。

---

## 可分享的網址

加入測站後網址列會自動帶上參數，可直接加書籤或傳給別人：

```
https://<你的帳號>.github.io/air-observer/#dev=iot:13580653094,epa:板橋&params=PM2.5,O3&days=7&end=2026-08-19&focus=PM2.5
```

- `dev` — `iot:` 是微型感測器、`epa:` 是國家測站，逗號分隔（上限 3 站）
- `params` — 要載入的測項，逗號分隔
- `days` / `end` — 往前天數與結束日（台灣時間）
- `focus` — 小時 pattern 與統計表使用的測項

舊格式 `#device=<編號>` 仍可開啟，一律視為微型感測器。

---

## 如果畫面顯示「無法連線到資料來源」

多半是瀏覽器的跨來源（CORS）限制。解法：

1. Cloudflare Dashboard → **Workers & Pages → Create → Worker**
2. 把 `worker.js` 全部貼上，**Deploy**
3. 回到網站 → 展開「資料來源與 proxy 設定」→ 在 **CORS proxy 前綴** 填入：

```
https://<你的-worker>.<你的帳號>.workers.dev/?url=
```

Worker 內建網域允許清單（只轉發 `sta.colife.org.tw`、`sta.ci.taiwan.gov.tw` 與 `history.colife.org.tw`），
不是開放式 proxy。免費方案每天 10 萬次請求，這個用途綽綽有餘。

---

## 資料量沒抓滿怎麼辦

狀態列會直說，不會靜默略過：

- **「N 頁抓取失敗，資料不完整」** — 來源站擋了部分分頁請求（多半是短時間請求太多）。
  程式已對 429／5xx 自動重試三次；仍失敗就是這則訊息。縮短天數或減少同時載入的測項再試。
- **「實際只涵蓋 X 天（要求 N 天）」** — 取回的資料涵蓋範圍明顯短於要求。
  可能是感測器該區間離線，也可能是伺服器沒把分頁資訊回完整。換個結束日可以區分兩者。

---

## 資料來源

- **民生公共物聯網資料服務平台** — <https://ci.taiwan.gov.tw/dsp/Views/dataset/air.aspx>
- 微型感測器：環境部「智慧城鄉空品微型感測器」— `https://sta.colife.org.tw/STA_AirQuality_EPAIoT/v1.0/`
- 國家測站：環境部「國家空品測站」— `https://sta.ci.taiwan.gov.tw/STA_AirQuality_v2/v1.0/`
- 介接：OGC SensorThings API v1.0，免 API key
- 授權：政府資料開放授權條款第 1 版
- 大批量歷史資料另有批次下載入口：<https://history.colife.org.tw>

---

## 已知限制

- **微型感測器不是法規等級儀器**。多為光散射法，環境部明示其數據不宜直接比對空氣品質標準，
  只適合看相對趨勢與時間 pattern；高濕度下對 PM2.5 常有正偏誤。
- **兩個來源疊圖是為了看偏差方向與時間結構，不是校正**。國家測站是小時值（已是該小時平均），
  微型感測器是 3 分鐘瞬時值，時間解析度不同，不可逐點相減。
- 圖上的顏色採 AQI 的 PM2.5 分段濃度值，但 **AQI 正式定義是 24 小時移動平均**，本頁畫的是小時平均，
  兩者不等價。AQI 配色只用於 PM2.5，其他測項改用單色深淺。
- 缺值不內插，時序中斷處直接斷線（門檻＝取樣間隔中位數的 2.5 倍，至少 20 分鐘）；
  小時有效筆數不足會以半透明標記（3 分鐘序列 < 5 筆；小時值序列不套用）。
- 單次查詢上限 3 站，避免對來源站造成不必要的負載。天數與測項越多，請求數越多（載入按鈕下方會先估算給你看）。
- 若要引用於論文或正式報告，應改用國家測站經品保程序後的數據，並註明資料擷取日期。
