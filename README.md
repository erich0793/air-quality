# 空品測站連續觀測台

輸入空氣網的裝置編號，直接取回該感測器 **3 分鐘解析度**的原始觀測值，畫出連續變化與小時 pattern。

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

## 裝置編號怎麼來

在**空氣網**（<https://wot.moenv.gov.tw>）地圖上點任一感測點，詳細面板中間那串粗體字就是：

```
TW040203A0506884
```

複製貼進網站左上角的輸入框，按 **加入測站** 即可。

輸入值會依序嘗試四種比對，命中即停：

| 順序 | 比對欄位 | 範例 |
|---|---|---|
| 1 | `properties/locationId` | `TW040203A0506884` |
| 2 | `properties/stationID` | `7737132222` |
| 3 | `name` 完全相符 | `智慧城鄉空品微型感測器-7737132222` |
| 4 | 名稱片段（`substringof` / `contains`） | 部分關鍵字 |

也可以展開「改用座標找附近的測站」，用經緯度 + 半徑搜尋。

---

## 可分享的網址

加入測站後網址列會自動帶上參數，可直接加書籤或傳給別人：

```
https://<你的帳號>.github.io/air-observer/#device=TW040203A0506884&days=3&end=2026-08-19
```

多站以逗號分隔（上限 3 站）：

```
#device=TW040203A0506884,TW040203A0506885&days=7
```

開啟時會自動載入。

---

## 如果畫面顯示「無法連線到資料來源」

多半是瀏覽器的跨來源（CORS）限制。解法：

1. Cloudflare Dashboard → **Workers & Pages → Create → Worker**
2. 把 `worker.js` 全部貼上，**Deploy**
3. 回到網站 → 展開「資料來源與 proxy 設定」→ 在 **CORS proxy 前綴** 填入：

```
https://<你的-worker>.<你的帳號>.workers.dev/?url=
```

Worker 內建網域允許清單（只轉發 `sta.colife.org.tw` 與 `history.colife.org.tw`），不是開放式 proxy。免費方案每天 10 萬次請求，這個用途綽綽有餘。

---

## 資料來源

- **民生公共物聯網資料服務平台** — <https://ci.taiwan.gov.tw/dsp/Views/dataset/air.aspx>
- 資料集：環境部「智慧城鄉空品微型感測器」（全國約 10,999 點，更新頻率 3 分鐘，2017 年 6 月起）
- 介接：OGC SensorThings API v1.0 — `https://sta.colife.org.tw/STA_AirQuality_EPAIoT/v1.0/`
- 授權：政府資料開放授權條款第 1 版
- 大批量歷史資料另有批次下載入口：<https://history.colife.org.tw>

---

## 已知限制

- **微型感測器不是法規等級儀器**。多為光散射法，環境部明示其數據不宜直接比對空氣品質標準，只適合看相對趨勢與時間 pattern；高濕度下對 PM2.5 常有正偏誤。
- 圖上的顏色採 AQI 的 PM2.5 分段濃度值，但 **AQI 正式定義是 24 小時移動平均**，本頁畫的是小時平均，兩者不等價。
- 缺值不內插，時序中斷處直接斷線；小時有效筆數 < 5 會以半透明標記。
- 單次查詢上限 3 站 × 7 天，避免對來源站造成不必要的負載。
- 若要引用於論文或正式報告，應改用國家測站經品保程序後的數據。
