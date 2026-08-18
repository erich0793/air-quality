# CLAUDE.md — 空品測站連續觀測台

> 這份檔案是專案的交接文件。開始動工前請先讀完，並讀 `README.md`。

---

## 專案目標

讓使用者用裝置編號（微型感測器）或測站名稱（國家空品測站）取回原始觀測值，畫出連續變化與小時 pattern，
並讓兩個來源在同一張圖上疊圖比較。

**核心使用情境**：評估特定路口／住家附近的空氣品質日變化（diurnal pattern），特別是交通尖峰時段的相對差異；
以及用國家空品測站當參考，檢驗鄰近微型感測器的系統性偏差。使用者具醫學與流行病學背景，重視方法學嚴謹度勝過視覺華麗。

---

## 現況

| 檔案 | 狀態 |
|---|---|
| `index.html` | 單檔靜態網頁，兩個資料來源（微型感測器＋國家空品測站），多測項疊圖 |
| `worker.js` | Cloudflare Worker CORS proxy，備援用，尚未部署 |
| `README.md` | 部署與使用說明 |

部署目標：GitHub Pages（純靜態，無 build step）。

**驗證狀態**：微型感測器路線由使用者在真實瀏覽器實測可用（裝置編號 `13580653094`）。
國家空品測站路線與分頁修正只在 Chromium + 合成 STA 回應下驗證過（見下方「未驗證」），**尚未打過真實的國家測站 API**，
且該 endpoint 本身是**高風險假設**（見下方專節）。「來源間偏差」面板有已知的方法學問題，
**在「下一輪必修」處理完之前，那個面板的數字不得用於任何結論**。

---

## 已驗證的事實（請勿重新猜測或更改）

以下出自民生公共物聯網官方 API 文件或官方套件設定，已確認：

| 項目 | 值 |
|---|---|
| 微型感測器 endpoint | `https://sta.colife.org.tw/STA_AirQuality_EPAIoT/v1.0/`（鏡像：`https://sta.ci.taiwan.gov.tw/STA_AirQuality_EPAIoT/v1.0/`） |
| 國家空品測站 endpoint | **不在這張表裡——這是高風險假設，見下一節。** |
| 協定 | OGC SensorThings API v1.0 |
| API key | **不需要** |
| 資料集（微型） | 環境部「智慧城鄉空品微型感測器」，約 10,999 點，更新頻率 3 分鐘，2017 年 6 月起 |
| 資料集（國家） | 環境部「國家空品測站」，77 站，每小時，1998 年起 |
| 授權 | 政府資料開放授權條款第 1 版 |
| 時間欄位 | `phenomenonTime`，**UTC**，需 +8 小時才是台灣時間 |
| 分頁 | 單頁上限 **100 筆**，用 `$skip` 迴圈；`@iot.count` 給總筆數；FROST 另給 `@iot.nextLink` |
| 裝置編號欄位 | `Thing.properties.locationId`，格式如 `TW020101A0201227` |
| 另一組編號 | `Thing.properties.stationID`，純數字如 `13580653094`、`7737132222` — **使用者已實測 `13580653094` 可查到測站** |
| Thing 名稱格式（微型） | `智慧城鄉空品微型感測器-<stationID>` |
| 空間查詢 | 支援 `$filter=geo.intersects(Locations/location,geography'POLYGON((...))')` |
| 字串包含 | 伺服器為 FROST，支援 `substringof('x',name)`；OData 4 的 `contains()` 亦一併嘗試 |
| 批次歷史下載 | <https://history.colife.org.tw>（大量歷史資料走這裡比逐筆 API 有效率） |
| 其他來源（備查） | 科技部智慧園區 `STA_AirQuality_MOST/v1.0/`、暨大在地感測器 `STA_AirQuality_Local/v1.0/`（同樣出自 pyCIOT 設定） |

---

## 高風險假設（未經證實，且有明確的過期跡象）

### 國家空品測站的 endpoint

程式碼目前預設 `https://sta.ci.taiwan.gov.tw/STA_AirQuality_v2/v1.0/`，並以
`properties/authority` 區分 `行政院環境保護署`＝國家測站、`中研院`＝校園微型感測器。

**這是猜的，不是事實。** 唯一依據是官方套件 pyCIOT 1.1.0 的 `data_source.json`。
而那份設定檔裡 `authority` 仍寫「行政院環境保護署」——環保署已於 2023 年 8 月改制為**環境部**，
代表該設定檔至少兩年沒更新過。一份兩年沒更新的設定檔，裡面的 endpoint 同樣可能已經遷移、
改版或停用。

因此在使用者提供實測確認的 endpoint 之前：

- **不得把這個 endpoint 當成已知事實**，也不得以它為前提再往下推論（例如「因為 v2 收錄兩種來源，所以…」）。
- `index.html` 裡它只是一個**可覆寫的預設值**，UI 上的 endpoint 欄位就是為此保留的。
- 任何說明文字（README、UI、commit message）提到它時都要標明未經實測。
- 拿到正確 endpoint 後：更新這一節、把它移進「已驗證的事實」、同步 README 與 `worker.js` 白名單，
  並重新檢視下面第 2、3 項是否還成立。

---

## 未驗證，需要實測確認

1. **CORS** — 最關鍵的未知數。兩台主機都要測：

```bash
   for h in sta.colife.org.tw/STA_AirQuality_EPAIoT sta.ci.taiwan.gov.tw/STA_AirQuality_v2; do
     curl -sI -H "Origin: https://example.github.io" "https://$h/v1.0/Things?\$top=1" | grep -i access-control
   done
```

   有輸出 → 直接部署 GitHub Pages 即可，`worker.js` 用不到。
   無輸出 → 走 `worker.js` 路線（`worker.js` 的白名單目前只有 `sta.colife.org.tw` 與 `history.colife.org.tw`，
   要用國家測站得把 `sta.ci.taiwan.gov.tw` 加進去）。

2. **國家空品測站的 Thing 欄位** — 程式碼假設有 `properties.stationName`（測站名稱，如「板橋」）、
   `properties.stationID`、`properties.authority`。比對順序：`stationName` → `name` → `stationID` → 名稱片段。
   實測後若確認實際欄位名，請把命中的那個排第一，並把猜錯的移除。

3. **`authority` 的字串** — 環保署 2023 年改制為環境部，pyCIOT 設定裡仍寫 `行政院環境保護署`。
   程式碼「列出國家測站」按鈕依序試 `行政院環境保護署` → `環境部` → 不過濾，實測後可簡化。

4. **國家測站的 `phenomenonTime` 格式** — 小時值有可能是時間區間（`起/迄`）。
   程式碼遇到含 `/` 的字串會取**區間起點**當時標；若實際是區間終點代表該小時，時間軸會整體偏移一小時，需修正。

5. **Datastream 清單** — 兩個來源各有哪些測項、`name` 字串長什麼樣（`PM2.5`／`O3`／`RH`／`AMB_TEMP`…）？
   程式碼是加入測站後動態讀取後產生勾選清單，但沒看過真實回應。

6. **7 天只出現 1 天的成因** — **三個候選成因，尚未確認是哪一個（也可能都不是）**：

   | | 成因 | 現況 |
   |---|---|---|
   | A | 分頁請求被來源站限流（429／5xx），失敗的頁被靜默丟掉 | 已改成重試＋失敗計數，狀態列會出現「N 頁抓取失敗」 |
   | B | 伺服器沒回 `@iot.count`，程式只取到第一頁 100 筆 | 已改成改跟 `@iot.nextLink` 逐頁走 |
   | C | **STA endpoint 只保留近期觀測值，較舊的資料只在 <https://history.colife.org.tw>** | **完全沒處理，程式碼目前假設 STA 有完整歷史** |

   A、B 是「修掉了但沒覆核」，C 是**還沒驗證也還沒處理**的可能性。
   如果 C 成立，那麼不管分頁寫得多好，超過保留期的區間都不會有資料，
   長區間必須改走 history 的批次下載，或在 UI 上明講可查詢的時間範圍。

   **判別方式**（直接問該 datastream 最舊與最新的一筆）：

```bash
   BASE=https://sta.colife.org.tw/STA_AirQuality_EPAIoT/v1.0
   Q=13580653094        # 裝置編號（stationID）

   # 1) 由裝置編號取得 Thing id
   TID=$(curl -sG "$BASE/Things" \
     --data-urlencode "\$filter=properties/stationID eq '$Q'" | jq -r '.value[0]["@iot.id"]')

   # 2) 取得 PM2.5 的 datastream id
   DS=$(curl -sG "$BASE/Things($TID)/Datastreams" \
     --data-urlencode "\$filter=name eq 'PM2.5'" | jq -r '.value[0]["@iot.id"]')

   # 3) 最舊的一筆、最新的一筆、總筆數
   curl -sG "$BASE/Datastreams($DS)/Observations" \
     --data-urlencode "\$orderby=phenomenonTime asc"  --data-urlencode "\$top=1" \
     --data-urlencode "\$select=phenomenonTime" | jq -r '.value[0].phenomenonTime'
   curl -sG "$BASE/Datastreams($DS)/Observations" \
     --data-urlencode "\$orderby=phenomenonTime desc" --data-urlencode "\$top=1" \
     --data-urlencode "\$select=phenomenonTime" | jq -r '.value[0].phenomenonTime'
   curl -sG "$BASE/Datastreams($DS)/Observations" \
     --data-urlencode "\$count=true" --data-urlencode "\$top=1" | jq -r '.["@iot.count"]'
```

   判讀：

   - 最舊一筆只到**幾天前**（總筆數也只有幾千）→ **成因 C 成立**：STA 只留近期資料。
     此時要嘛把可選天數限制在保留期內，要嘛長區間改走 history.colife.org.tw。
   - 最舊一筆是 **2017 年附近、總筆數上百萬** → C 不成立，回頭看狀態列：
     有「N 頁抓取失敗」＝成因 A；沒有失敗卻只拿到 100 筆＝成因 B。
   - 國家測站要一併測的話，把 `BASE` 換成國家測站 endpoint、`Q` 換成 stationID 再跑一次
     （但那個 endpoint 本身還是高風險假設，見上一節）。

**確認完請把結果寫回這份 CLAUDE.md，把項目從「未驗證」移到「已驗證」。**

---

## 不可退讓的原則

這幾條是專案的方法學底線，任何重構都不得破壞：

1. **時區**：`phenomenonTime` 是 UTC。所有分組、繪圖、統計一律先轉 UTC+8 再處理。
   絕不可直接拿 UTC 的小時數當作台灣時間的小時。

2. **缺值不內插**。感測器離線造成的時序中斷必須以斷線呈現。
   斷線門檻＝該序列取樣間隔中位數的 2.5 倍，且至少 20 分鐘（3 分鐘序列即維持原本的 20 分鐘判定；
   小時序列則是 2.5 小時）。不得用線性內插、前值填補或任何平滑處理來「補好看」。

3. **微型感測器 ≠ 法規等級數據**。多為光散射法，環境部明示不宜直接比對空氣品質標準。
   UI 上必須保留這項說明，不得為了版面精簡而刪除。高濕度下對 PM2.5 有正偏誤。
   **兩個來源疊圖是為了看偏差方向與時間結構，不是校正**，也不可逐點相減（時間解析度不同）。
   **兩個測點不是 co-location**（實測配置相距約 2 km），因此兩者的差值不等於儀器偏差，
   不得稱為 bias，也不得作為校正依據——詳見下方「下一輪必修」。

4. **AQI 的定義是 24 小時移動平均**。目前用 AQI 的 PM2.5 分段濃度值來著色小時平均，
   這是刻意的近似，UI 必須明白標示兩者不等價。不得把小時平均直接稱為 AQI。
   **AQI 配色只用於 PM2.5**；其他測項（O3、RH…）改用單色深淺，不得套 AQI 顏色。

5. **不得產生假資料**。任何情況下都不要用 mock data、示範資料或內插值來填補 API 失敗，
   也不要在 API 無回應時偽造成功畫面。失敗就顯示失敗，並說明原因與修復方式。
   分頁失敗、涵蓋天數不足都必須在狀態列明講，**不得靜默略過**。
   （測試腳手架裡用合成回應驗證前端邏輯可以，但那些檔案不得進到 `index.html`。）

6. **低樣本標記**：小時有效筆數不足時必須視覺區隔（目前用半透明）。
   門檻隨取樣頻率調整：`min(5, ceil(每小時應有筆數 × 0.6))`，
   3 分鐘序列＝原本的 < 5 筆；小時序列每小時本來就只有 1 筆，不套用此標記。

7. **介面文字一律正體中文**，專業／技術名詞保留英文（PM2.5、SensorThings API、CORS、proxy 等）。
   不得出現簡體字。

---

## 下一輪必修：「來源間偏差」面板的方法學問題

現行 `renderBias()`／`blandAltman()`／`rhStrata()` 有以下問題，**在修好之前，這個面板的數字
不得用於任何結論，也不得寫進報告**。使用者（醫學／流行病學背景）已逐項指出：

1. **非 co-location，不能叫 bias。** 使用者實測的兩個測點相距約 2 km。
   兩者的差值同時混合了「儀器／方法差異」與「真實的空間濃度梯度」，兩者無法用現有資料拆開。
   → 面板名稱與所有欄位改為**「兩測點差異」**（difference between sites），
   移除 `bias` 字樣；並明寫**不可作為校正依據**。
   若日後真的做 co-location（兩機並置），才可以重新談儀器偏差。

2. **95% CI 低估。** 逐時 PM2.5 有強烈自相關，現行 `mean ± 1.96·SD/√n` 把 n 當成獨立樣本數，
   信賴區間必然過窄。→ 改以**「日」為 block 的 block bootstrap**（重抽整天，保留日內相關結構）
   估計差異平均值的 CI；報告時說明重抽次數與 block 定義。

3. **樣本量門檻改以天數計。** 現行 `n < 24` 才示警，是把小時數當樣本數。
   有效獨立樣本接近「天數」而非「小時數」。→ 門檻改為天數（例如 < 7 天即標示證據薄弱），
   UI 上同時顯示涵蓋天數與配對小時數。

4. **Pearson r 不是一致性指標。** r 衡量的是線性相關，兩台儀器可以 r = 0.99 卻系統性差一倍。
   與 Bland–Altman 並列會讓讀者誤以為 r 高＝一致。
   → **移除**，或保留但明確標註「相關性 ≠ 一致性，僅供參考」。傾向直接移除。

5. **固定 ±1.96SD 的 LoA 可能不適用。** 若差值的離散度隨濃度放大（heteroscedasticity，PM2.5 常見），
   固定寬度的一致性界限在低濃度過寬、高濃度過窄。
   → 先檢查差值 vs 平均值的散布是否有喇叭狀；若有，改用 **log 轉換後的 LoA**（結果以比值呈現）
   或 **回歸式 LoA**（差值與 SD 皆對濃度做迴歸）。UI 要標明用的是哪一種。

6. **確認 Bland–Altman 的 x 軸。** 現行 `blandAltman()` 的 x 軸**確實是 (微型 + 國家)/2**
   （`xs = pairs.map(p => (p.micro + p.nat)/2)`），y 軸是 `micro − nat`，符合標準 BA 圖。
   但要注意：**當其中一方是參考標準時**（國家測站經品保程序），Krouwer 建議 x 軸改用
   **參考值本身**而非兩者平均，否則參考值的誤差會同時進入 x 與 y 而造成人工相關。
   本專案的情況介於兩者之間（國家測站是參考級但非同址），修的時候要一併決定並在 UI 標明。

**做這一輪時請一併重讀原則 3。** 面板改名後，README 與 UI 文案也要同步。

---

## 程式碼慣例

- **單檔、零依賴**：`index.html` 內含全部 HTML/CSS/JS，不引入框架、不用 npm、不需要 build step。
  維持這個特性，因為部署目標是 GitHub Pages 且要能離線開啟檢視。
- **不使用 `localStorage` / `sessionStorage`**。狀態一律存在 URL hash
  （`#dev=iot:13580653094,epa:板橋&params=PM2.5,O3&days=7&end=2026-08-19&focus=PM2.5`），
  這同時提供可分享／可加書籤的深連結。舊格式 `#device=<id>` 仍相容，一律視為微型感測器。
- **兩個 endpoint**：`SOURCES.iot` / `SOURCES.epa` 各自對應一個輸入框，切換 tab 只換來源與提示文字。
  新增第三個來源就往 `SOURCES` 加一筆。
- **分頁**：`fetchSeries()` 先 `$count=true` 取總數再用 `$skip` 併發取；伺服器沒回 `@iot.count` 時
  改跟 `@iot.nextLink` 逐頁走。單頁失敗自動重試（**只對 429／5xx**；`TypeError`＝CORS／離線，重試沒意義）。
  仍失敗就計數並在狀態列標示。單序列頁數上限 `MAX_PAGES`。
- **圖表自繪 SVG**，不引入 Chart.js 等圖表庫。每個測項一張圖，共用同一條時間軸；
  同一測項的多站疊在同一張圖，顏色依測站（`SERIES_COLORS`）。小時值序列畫粗線加空心圓點，3 分鐘序列畫細線。
- **統計一律以小時平均為單位**（`hourlyMap()`）：兩個來源時間解析度不同，先降頻成台灣時間整點才可比。
  降頻是統計處理，不是內插；有效筆數不足的小時**整格排除**（門檻同 `lowN()`），並在畫面上講明排除幾格。
  分層與偏差面板的 `n` 一律是「有效小時數」，不是原始筆數，UI 不得寫成筆數。
- **併發上限 4**（常數 `CONCURRENCY`），避免對政府來源站造成不必要負載。
- **同時比較上限 3 站**（常數 `MAX_STATIONS`）。
- 錯誤訊息要說明「發生什麼事」＋「怎麼修」，不要只寫「發生錯誤」。

---

## 待辦（依優先序）

1. **修「來源間偏差」面板的方法學問題** — 見上方「下一輪必修」六項。這是目前最高優先，
   因為那個面板現在會產出看起來可信、實際上有誤導性的數字。
2. **取得並確認國家空品測站的正確 endpoint**（使用者提供），解除上方「高風險假設」。
3. **實測 CORS**（兩台主機都要），依結果決定是否部署 `worker.js`，並更新 README 與 worker 白名單。
4. **釐清 7 天問題的真因**（成因 A／B／C，判別 curl 見上方未驗證第 6 項）。
   若成因 C 成立，要規劃 history.colife.org.tw 路線或限制可選天數。
5. ~~平日 vs 假日、尖峰 vs 離峰的分層統計~~ — 已做（「分層統計」面板，`renderStrat()`）。
   統計單位是小時平均，`n` ＝有效小時數；尖峰＝台灣時間 07–09／17–19；
   **假日只認週六日，國定假日與補班日尚未納入**（要做得先內建假日表，或改抓行政院行事曆）。
   注意：這個面板的 `n` 同樣有自相關問題（同「下一輪必修」第 2、3 項），做那一輪時一併檢視。
6. **長期資料累積**：目前每次都重新打 API。可考慮把抓過的觀測值寫入 Supabase（使用者已有帳號），
   歷史資料不變動故可永久快取；累積數月後才有足夠樣本做 diurnal pattern 的統計檢定。
7. 無障礙檢查：鍵盤 focus 可見（已加 `:focus-visible`）、`prefers-reduced-motion`（已加）、
   圖表的文字替代（目前只有 `aria-label`，可考慮補一段統計摘要）。

---

## 回報格式

完成任務時請說明：**改了什麼、為什麼、以及哪些部分你沒有實際驗證過**。
未經瀏覽器實測的功能請明講「未驗證」，不要用「應該可以運作」帶過。
用合成資料測過的，要講明是合成資料，不能當成對真實 API 的驗證。
