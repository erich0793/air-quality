# CLAUDE.md — 空品測站連續觀測台

> 這份檔案是專案的交接文件。開始動工前請先讀完，並讀 `README.md`。

---

## 專案目標

讓使用者貼上空氣網（<https://wot.moenv.gov.tw>）的裝置編號，直接取回該感測器 3 分鐘解析度的原始觀測值，畫出連續變化與小時 pattern。

**核心使用情境**：評估特定路口／住家附近的空氣品質日變化（diurnal pattern），特別是交通尖峰時段的相對差異。使用者具醫學與流行病學背景，重視方法學嚴謹度勝過視覺華麗。

---

## 現況

| 檔案 | 狀態 |
|---|---|
| `index.html` | 單檔靜態網頁，功能完整，**尚未在真實瀏覽器對真實 API 驗證過** |
| `worker.js` | Cloudflare Worker CORS proxy，備援用，尚未部署 |
| `README.md` | 部署與使用說明 |

部署目標：GitHub Pages（純靜態，無 build step）。

---

## 已驗證的事實（請勿重新猜測或更改）

以下均出自民生公共物聯網官方 API 文件，已確認：

| 項目 | 值 |
|---|---|
| Endpoint | `https://sta.colife.org.tw/STA_AirQuality_EPAIoT/v1.0/` |
| 協定 | OGC SensorThings API v1.0 |
| API key | **不需要** |
| 資料集 | 環境部「智慧城鄉空品微型感測器」，約 10,999 點，更新頻率 3 分鐘，2017 年 6 月起 |
| 授權 | 政府資料開放授權條款第 1 版 |
| 時間欄位 | `phenomenonTime`，**UTC**，需 +8 小時才是台灣時間 |
| 分頁 | 單頁上限 **100 筆**，用 `$skip` 迴圈；`@iot.count` 給總筆數 |
| 裝置編號欄位 | `Thing.properties.locationId`，格式如 `TW020101A0201227` |
| 另一組編號 | `Thing.properties.stationID`，純數字如 `7737132222` |
| Thing 名稱格式 | `智慧城鄉空品微型感測器-<stationID>` |
| 空間查詢 | 支援 `$filter=geo.intersects(Locations/location,geography'POLYGON((...))')` |
| 字串包含 | 伺服器為 FROST，支援 `substringof('x',name)`；OData 4 的 `contains()` 亦一併嘗試 |
| 批次歷史下載 | <https://history.colife.org.tw>（大量歷史資料走這裡比逐筆 API 有效率） |
| 國家空品測站 | 另一組資料集，77 站，每小時，1998 年起（endpoint 需另查） |

---

## 未驗證，需要實測確認

1. **CORS** — 最關鍵的未知數。`sta.colife.org.tw` 是否回傳 `Access-Control-Allow-Origin`？
   先跑這個確認，再決定要不要部署 proxy：

```bash
   curl -sI -H "Origin: https://example.github.io" \
     "https://sta.colife.org.tw/STA_AirQuality_EPAIoT/v1.0/Things?\$top=1" \
     | grep -i access-control
```

   有輸出 → 直接部署 GitHub Pages 即可，`worker.js` 用不到。
   無輸出 → 走 `worker.js` 路線。

2. **裝置編號欄位** — 空氣網介面上顯示的粗體編號（樣本：`TW040203A0506884`）究竟對應
   `locationId` 還是別的欄位？目前程式碼採四段式 fallback 比對，命中即停。實測後若確認是
   `locationId`，可保留 fallback 但把它排第一（現況已是）。

3. **Datastream 清單** — 除了 `PM2.5`，各站還有哪些測項（溫度、濕度的實際 `name` 字串為何）？
   程式碼目前是動態讀取後填入下拉選單，但沒看過真實回應。

4. **國家空品測站的 STA endpoint** — 尚未確認。可從民生公共物聯網資料集頁的「API網址」按鈕取得。

**確認完請把結果寫回這份 CLAUDE.md，把項目從「未驗證」移到「已驗證」。**

---

## 不可退讓的原則

這幾條是專案的方法學底線，任何重構都不得破壞：

1. **時區**：`phenomenonTime` 是 UTC。所有分組、繪圖、統計一律先轉 UTC+8 再處理。
   絕不可直接拿 UTC 的小時數當作台灣時間的小時。

2. **缺值不內插**。感測器離線造成的時序中斷必須以斷線呈現（目前判定：間隔 > 20 分鐘即斷開）。
   不得用線性內插、前值填補或任何平滑處理來「補好看」。

3. **微型感測器 ≠ 法規等級數據**。多為光散射法，環境部明示不宜直接比對空氣品質標準。
   UI 上必須保留這項說明，不得為了版面精簡而刪除。高濕度下對 PM2.5 有正偏誤。

4. **AQI 的定義是 24 小時移動平均**。目前用 AQI 的 PM2.5 分段濃度值來著色小時平均，
   這是刻意的近似，UI 必須明白標示兩者不等價。不得把小時平均直接稱為 AQI。

5. **不得產生假資料**。任何情況下都不要用 mock data、示範資料或內插值來填補 API 失敗，
   也不要在 API 無回應時偽造成功畫面。失敗就顯示失敗，並說明原因與修復方式。

6. **低樣本標記**：小時有效筆數 < 5 時必須視覺區隔（目前用半透明）。

7. **介面文字一律正體中文**，專業／技術名詞保留英文（PM2.5、SensorThings API、CORS、proxy 等）。
   不得出現簡體字。

---

## 程式碼慣例

- **單檔、零依賴**：`index.html` 內含全部 HTML/CSS/JS，不引入框架、不用 npm、不需要 build step。
  維持這個特性，因為部署目標是 GitHub Pages 且要能離線開啟檢視。
- **不使用 `localStorage` / `sessionStorage`**。狀態一律存在 URL hash（`#device=...&days=3&end=...`），
  這同時提供可分享／可加書籤的深連結。
- **圖表自繪 SVG**，不引入 Chart.js 等圖表庫。
- **併發上限 4**（常數 `CONCURRENCY`），避免對政府來源站造成不必要負載。
- **同時比較上限 3 站**（常數 `MAX_STATIONS`）。
- 錯誤訊息要說明「發生什麼事」＋「怎麼修」，不要只寫「發生錯誤」。

---

## 待辦（依優先序）

1. **實測 CORS**，依結果決定是否部署 `worker.js`，並更新 README。
2. **實測裝置編號比對**，用 `TW040203A0506884` 走一次完整流程（加入測站 → 載入 3 天資料 → 出圖）。
3. **加入國家空品測站**（板橋站等，小時值）作為第二資料來源，與微型感測器並列比對，
   用來檢驗微型感測器相對於法規測站的系統性偏差。這是本專案最有分析價值的功能。
4. **平日 vs 假日、尖峰 vs 離峰的分層統計**，含樣本數與離散度，不要只給平均值。
5. **長期資料累積**：目前每次都重新打 API。可考慮把抓過的觀測值寫入 Supabase（使用者已有帳號），
   歷史資料不變動故可永久快取；累積數月後才有足夠樣本做 diurnal pattern 的統計檢定。
6. 響應式與無障礙檢查：手機寬度、鍵盤 focus 可見、`prefers-reduced-motion`。

---

## 回報格式

完成任務時請說明：**改了什麼、為什麼、以及哪些部分你沒有實際驗證過**。
未經瀏覽器實測的功能請明講「未驗證」，不要用「應該可以運作」帶過。
