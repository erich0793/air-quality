#!/usr/bin/env python3
"""從 history.colife.org.tw 取出指定裝置的觀測值，輸出成小檔進 repo。

為什麼需要這個腳本：SensorThings API 只保留約 2 小時，跨日資料只在 history 站的
每日 ZIP 裡；但那些檔案每天每測項約 176 MB 且不允許跨來源存取，瀏覽器不可能處理。
所以在 GitHub Actions 上下載、解壓、篩出目標裝置，輸出成每台裝置每月一個小 CSV，
網頁再以同源方式讀取。

只用標準函式庫（GitHub runner 內建 Python 即可，不裝任何套件）。

用法：
  # 步驟 0：探勘，只印結構不寫檔（第一次一定要先跑這個）
  python3 scripts/hist_extract.py --date 20260819 --param humidity --dry-run

  # 步驟 1：確認檔名裡有哪些測項代碼（只讀開頭幾百 bytes）
  python3 scripts/hist_extract.py --date 20260819 --probe

  # 步驟 2：時區。先存一份 API 快照（API 只留 ~2 小時，過了就沒了），
  #         隔天該日檔案產出後再跑 --tz-check 逐筆比對。
  python3 scripts/hist_extract.py --api-snapshot --devices 13580653094 \
      --label "Relative humidity" --out data
  python3 scripts/hist_extract.py --date 20260821 --param humidity \
      --devices 13580653094 --label "Relative humidity" --tz-check --out data

  # 步驟 3：正式萃取（時區必須明講，沒有預設值）
  python3 scripts/hist_extract.py --date 20260819 --param humidity \
      --devices 13580653094 --tz taipei --out data
"""

import argparse, base64, csv, io, json, os, sys, tempfile, urllib.parse, urllib.request, zipfile
from datetime import datetime, timedelta, timezone

BASE = "https://history.colife.org.tw"
DIR = "/空氣品質/環境部_智慧城鄉空品微型感測器"
TPE = timezone(timedelta(hours=8))
STA = "https://sta.colife.org.tw/STA_AirQuality_EPAIoT/v1.0"

# 2026-08-21 由 --dry-run 實測確認的表頭（僅供對照，程式仍自動偵測欄位）：
#   stationID, Relative humidity, phenomenonTime, StationLongitude, StationLatitude
#   13580653094, 73.46, 2026-08-19 00:00:00, 121.124306, 25.062393

# ZIP 內的欄位名未知，這裡列出可能的候選；找不到就大聲失敗，不猜。
DEVICE_HINTS = ("stationid", "station_id", "deviceid", "device_id", "locationid", "location_id", "裝置編號", "測站編號")
TIME_HINTS = ("time", "datetime", "timestamp", "phenomenontime", "datacreationdate", "obs_time", "時間", "觀測時間")
VALUE_HINTS = ("value", "result", "數值", "觀測值", "concentration")

# 檔名裡的測項代碼只實測確認了 humidity，其餘是候選，要用 --probe 逐一驗證存在才可用。
PROBE_CODES = "humidity,pm25,pm2.5,pm2_5,PM25,PM2.5,pm10,temperature,temp,voc,co2"


def log(*a):
    print(*a, flush=True)


def build_url(date: str, param: str) -> str:
    """date=YYYYMMDD, param 例如 humidity；回傳完整下載網址。"""
    path = "%s/%s/moenviot_%s_%s.zip" % (DIR, date[:6], param, date)
    b64 = base64.b64encode(path.encode("utf-8")).decode("ascii")
    return "%s/?r=/download&path=%s" % (BASE, urllib.parse.quote(b64, safe=""))


def download(url: str, dest: str) -> int:
    req = urllib.request.Request(url, headers={
        "User-Agent": "air-quality-observer/1.0 (+https://github.com/erich0793/air-quality)",
        "Accept": "*/*",
    })
    total = 0
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
            if total % (32 << 20) < (1 << 20):
                log("  已下載 %.0f MB" % (total / 1048576))
    return total


def probe_params(date: str, codes):
    """測項在檔名裡的代碼只確認了 humidity，其餘用猜的會靜默抓到錯的檔。
       這裡對每個候選代碼發一次請求，只讀前幾百 bytes 就關掉，回報是不是真的 ZIP。"""
    log("探測 %s 這一天有哪些測項檔（只讀開頭幾百 bytes 就中斷）：" % date)
    hits = []
    for code in codes:
        url = build_url(date, code)
        req = urllib.request.Request(url, headers={"User-Agent": "air-quality-observer/1.0", "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                head = r.read(512)
                ctype = r.headers.get("Content-Type", "?")
                clen = r.headers.get("Content-Length", "?")
                status = r.status
        except Exception as e:                                    # noqa: BLE001
            log("  %-12s 失敗：%s" % (code, e))
            continue
        # ZIP 的開頭是 PK\x03\x04；回 HTML 代表這個檔名不存在（站方回錯誤頁而不是 404）
        is_zip = head[:2] == b"PK"
        size = ("%.1f MB" % (int(clen) / 1048576)) if str(clen).isdigit() else str(clen)
        log("  %-12s HTTP %s  %-28s %-12s 開頭=%s  %s"
            % (code, status, ctype, size, head[:4].hex(), "← ZIP" if is_zip else "不是 ZIP"))
        if is_zip:
            hits.append(code)
    log("\n可用的測項代碼：%s" % (", ".join(hits) if hits else "（一個都沒有）"))
    return hits


def sta_get(path: str, **query):
    """query 一律用 urlencode 編碼：$orderby 的值含空白，直接串進網址會被 urllib 擋下。"""
    url = STA + path
    if query:
        # quote_via=quote：空白編成 %20 而不是 +，OData 伺服器對 + 的解讀不一定一致
        url += "?" + urllib.parse.urlencode(query, quote_via=urllib.parse.quote)
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": "air-quality-observer/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def api_snapshot(outdir: str, device: str, label: str):
    """把 API 現在還留著的那 ~2 小時原封不動存下來，供日後與 history 檔逐筆比對時區。

    為什麼要存：API 只保留約 2 小時，history 檔卻要隔天才產出，兩者在同一時刻不會重疊，
    無法即時對照。先把 API 的值（UTC，來源明確）存起來，等隔天檔案出來再比對，
    才能用「同一裝置同一分鐘的數值是否相同」直接證明 history 的時間欄位是哪個時區。
    """
    things = sta_get("/Things", **{"$filter": "properties/stationID eq '%s'" % device,
                                   "$expand": "Datastreams"})
    vals = things.get("value") or []
    if not vals:
        log("!! API 查不到裝置 %s" % device)
        return None
    streams = vals[0].get("Datastreams") or []
    ds = next((s for s in streams if s.get("name") == label), None)
    if ds is None:
        log("!! 裝置 %s 沒有名為「%s」的 datastream，實際有：%s"
            % (device, label, [s.get("name") for s in streams]))
        return None
    obs = sta_get("/Datastreams(%s)/Observations" % ds["@iot.id"],
                  **{"$top": "500", "$orderby": "phenomenonTime desc"})
    rows = [[o["phenomenonTime"], o["result"]] for o in obs.get("value") or []]
    if not rows:
        log("!! datastream %s 沒有觀測值" % ds["@iot.id"])
        return None
    d = os.path.join(outdir, "_tzcheck")
    os.makedirs(d, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(d, "%s_%s_%s.json" % (device, label.replace(" ", "-"), stamp))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"device": device, "param": label, "datastream": ds["@iot.id"],
                   "taken": stamp, "note": "phenomenonTime 為 UTC（API 原樣）",
                   "observations": rows}, f, ensure_ascii=False, indent=1)
    log("已存 %s（%d 筆，%s ～ %s）" % (path, len(rows), rows[-1][0], rows[0][0]))
    return path


def pick_column(header, hints, sample_rows=None, match_values=None):
    """先用欄位名猜；猜不到就看實際內容有沒有命中目標值（欄位名不可靠時的保險）。"""
    low = [h.strip().lower() for h in header]
    for i, h in enumerate(low):
        if any(k in h for k in hints):
            return i
    if sample_rows and match_values:
        for i in range(len(header)):
            for row in sample_rows:
                if i < len(row) and row[i].strip() in match_values:
                    return i
    return -1


def pick_value_column(header, sample_rows, param_names, skip):
    """數值欄位常直接叫測項名（pm2.5／humidity），所以先比對測項名，
       再退回「第一個看起來是數字的欄位」。仍找不到就回 -1 讓呼叫端失敗。"""
    low = [h.strip().lower() for h in header]
    i = pick_column(header, VALUE_HINTS)
    if i >= 0:
        return i
    for want in [p.strip().lower() for p in param_names if p]:
        for i, h in enumerate(low):
            if h == want or want in h or h in want:
                if i not in skip:
                    return i
    for i in range(len(header)):
        if i in skip:
            continue
        seen = 0
        for row in sample_rows:
            if i < len(row):
                v = row[i].strip()
                if v == "":
                    continue
                try:
                    float(v)
                    seen += 1
                except ValueError:
                    seen = -99
                    break
        if seen > 0:
            return i
    return -1


def parse_time(raw: str, tz: str):
    """回傳 UTC 的 ISO 字串。tz 由呼叫端明講，腳本不猜。"""
    s = raw.strip().replace("/", "-")
    if s.endswith("Z"):
        return datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    s = s.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        dt = dt.replace(tzinfo=TPE if tz == "taipei" else timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return None


def dry_run(zpath: str):
    """只回報結構：ZIP 內容、第一個 CSV 的表頭與前 3 列、列數。不寫任何檔案。"""
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        log("ZIP 內含 %d 個檔案：" % len(names))
        for n in names[:20]:
            info = z.getinfo(n)
            log("  %-60s %10d bytes" % (n, info.file_size))
        if len(names) > 20:
            log("  …（其餘 %d 個略）" % (len(names) - 20))
        csvs = [n for n in names if n.lower().endswith((".csv", ".txt"))]
        if not csvs:
            log("!! ZIP 裡沒有 CSV/TXT，需要重新確認格式")
            return 2
        with z.open(csvs[0]) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
            rd = csv.reader(text)
            rows = 0
            for i, row in enumerate(rd):
                if i < 4:
                    log("  第 %d 列：%s" % (i, row))
                rows += 1
            log("  %s 共 %d 列" % (csvs[0], rows))
    log("\n請把以上內容回報，確認欄位對應與時區後才能正式萃取。")
    return 0


def scan_raw(zpath: str, devices, param_label: str, param_code: str, cols):
    """把原始時間字串原封不動讀出來（不套任何時區），供時區判定使用。
       回傳 (全體裝置的逐時累計, 目標裝置的 {raw_label: value})。"""
    col_device, col_time, col_value = cols
    all_sum, all_n = [0.0] * 24, [0] * 24
    raw = {d: {} for d in devices}
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            if not name.lower().endswith((".csv", ".txt")):
                continue
            with z.open(name) as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
                rd = csv.reader(text)
                header = next(rd, None)
                if header is None:
                    continue
                head = [h.strip() for h in header]
                sample = []
                for _ in range(200):
                    r = next(rd, None)
                    if r is None:
                        break
                    sample.append(r)
                di = col_device if col_device >= 0 else pick_column(head, DEVICE_HINTS, sample, set(devices))
                ti = col_time if col_time >= 0 else pick_column(head, TIME_HINTS)
                vi = col_value if col_value >= 0 else pick_value_column(
                    head, sample, [param_label, param_code], {di, ti})
                if min(di, ti, vi) < 0:
                    continue
                log("  欄位對應：裝置=%r 時間=%r 數值=%r" % (head[di], head[ti], head[vi]))
                for row in sample + [r for r in rd]:
                    if len(row) <= max(di, ti, vi):
                        continue
                    s = row[ti].strip()
                    try:
                        val = float(row[vi].strip())
                    except ValueError:
                        continue
                    if val < 0:
                        continue
                    # 「YYYY-MM-DD HH:MM:SS」的第 11、12 個字就是小時
                    if len(s) >= 13 and s[11:13].isdigit():
                        h = int(s[11:13])
                        if 0 <= h < 24:
                            all_sum[h] += val
                            all_n[h] += 1
                    if row[di].strip() in raw:
                        raw[row[di].strip()][s] = val
    return (all_sum, all_n), raw


def tz_check(zpath: str, devices, label: str, code: str, cols, snapdir: str):
    """判定 history 檔的時間欄位是台灣時間還是 UTC。兩條互相獨立的證據：

    A. 逐時剖面（推論）：相對濕度在清晨 04–07 時最高、午後 13–16 時最低（氣溫相反）。
       全國上萬台裝置平均後這個日夜週期非常乾淨，8 小時的偏移不可能看錯。
    B. 與 API 快照逐筆比對（直接證明）：同一裝置、同一分鐘的數值相不相同。
       這條才是決定性的，A 只是輔證。沒有快照時只會有 A。
    """
    log("\n=== 時區判定 ===")
    (asum, an), raw = scan_raw(zpath, devices, label, code, cols)

    log("\nA. 依「原始字串裡的小時」計算的全國平均 %s 逐時剖面：" % label)
    prof = [(asum[h] / an[h]) if an[h] else None for h in range(24)]
    ok = [p for p in prof if p is not None]
    if not ok:
        log("  沒有可用的值，無法判定")
    else:
        lo, hi = min(ok), max(ok)
        span = (hi - lo) or 1.0
        for h in range(24):
            if prof[h] is None:
                log("  %02d  （無資料）" % h)
            else:
                bar = "█" * int(round((prof[h] - lo) / span * 40))
                log("  %02d  %8.2f  %s" % (h, prof[h], bar))
        hmax = max(range(24), key=lambda h: prof[h] if prof[h] is not None else -1e9)
        hmin = min(range(24), key=lambda h: prof[h] if prof[h] is not None else 1e9)
        log("\n  標籤上的最大值在 %02d 時、最小值在 %02d 時" % (hmax, hmin))
        log("  若標籤是台灣時間 → 實際台灣時間 最大 %02d 時／最小 %02d 時" % (hmax, hmin))
        log("  若標籤是 UTC     → 實際台灣時間 最大 %02d 時／最小 %02d 時"
            % ((hmax + 8) % 24, (hmin + 8) % 24))
        log("  對照：相對濕度應在清晨 04–07 時最高、午後 13–16 時最低（氣溫相反）")

    log("\nB. 與 API 快照逐筆比對（決定性證據）：")
    snaps = []
    if os.path.isdir(snapdir):
        snaps = [os.path.join(snapdir, f) for f in sorted(os.listdir(snapdir)) if f.endswith(".json")]
    if not snaps:
        log("  沒有任何 API 快照（%s）。" % snapdir)
        log("  請先跑 --api-snapshot 把 API 當下那 2 小時存起來，隔天檔案產出後再跑一次本檢查。")
        return 0
    verdict = {"taipei": 0, "utc": 0}
    for path in snaps:
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
        dev, rows = snap["device"], snap["observations"]
        table = raw.get(dev)
        if not table:
            log("  %s：這個檔案裡沒有裝置 %s 的資料" % (os.path.basename(path), dev))
            continue
        if snap.get("param") != label:
            continue
        hit = {"taipei": 0, "utc": 0}
        overlap = 0
        for iso, val in rows:
            t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            found = False
            for tzname, shifted in (("utc", t), ("taipei", t.astimezone(TPE))):
                # history 是整分鐘（秒為 00），API 實測是 :30，所以比對到「分」為止
                key = shifted.strftime("%Y-%m-%d %H:%M:00")
                if key in table:
                    found = True
                    if abs(table[key] - float(val)) < 0.51:
                        hit[tzname] += 1
            if found:
                overlap += 1
        log("  %s：裝置 %s，%d 筆快照，對得上時間的 %d 筆 → 以 UTC 解讀吻合 %d 筆、以台灣時間解讀吻合 %d 筆"
            % (os.path.basename(path), dev, len(rows), overlap, hit["utc"], hit["taipei"]))
        verdict["utc"] += hit["utc"]
        verdict["taipei"] += hit["taipei"]
    if verdict["utc"] == verdict["taipei"] == 0:
        log("\n  兩種解讀都對不上（多半是快照與這一天的檔案沒有時間重疊）。")
        log("  請確認快照的日期，或改用涵蓋快照時刻的那一天的檔案再比對一次。")
    else:
        win = "utc" if verdict["utc"] > verdict["taipei"] else "taipei"
        log("\n  結論：history 檔的時間欄位是 %s（吻合 %d 筆 vs %d 筆）"
            % ("UTC" if win == "utc" else "台灣時間 UTC+8",
               max(verdict.values()), min(verdict.values())))
        log("  → 正式萃取請用 --tz %s" % win)
        with open(os.path.join(snapdir, "CONFIRMED"), "w", encoding="utf-8") as f:
            f.write("%s\n以 API 快照逐筆比對確認：吻合 %d 筆（另一種解讀 %d 筆）\n%s\n"
                    % (win, max(verdict.values()), min(verdict.values()),
                       datetime.now(timezone.utc).isoformat()))
        log("  已寫入 %s/CONFIRMED，manifest 會標示時區已驗證" % snapdir)
    return 0


def extract(zpath: str, devices, tz: str, param_label: str, param_code: str,
            col_device: int, col_time: int, col_value: int):
    """回傳 {device: {utc_iso: value}}。缺值直接丟棄，不補值。"""
    out = {d: {} for d in devices}
    scanned = matched = bad_time = bad_value = 0
    parsed_members = 0
    skipped = []
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            if not name.lower().endswith((".csv", ".txt")):
                continue
            with z.open(name) as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace", newline="")
                rd = csv.reader(text)
                header = next(rd, None)
                if header is None:
                    continue
                head = [h.strip() for h in header]
                sample = []
                for _ in range(200):
                    r = next(rd, None)
                    if r is None:
                        break
                    sample.append(r)
                di = col_device if col_device >= 0 else pick_column(head, DEVICE_HINTS, sample, set(devices))
                ti = col_time if col_time >= 0 else pick_column(head, TIME_HINTS)
                vi = col_value if col_value >= 0 else pick_value_column(
                    head, sample, [param_label, param_code], {di, ti})
                if min(di, ti, vi) < 0:
                    # 壓縮檔裡常夾雜 readme 之類的檔案，單一成員認不出來就跳過；
                    # 若所有成員都認不出來才中止（見迴圈結束後的檢查）。
                    skipped.append("%s header=%s" % (name, head[:6]))
                    continue
                parsed_members += 1
                for row in [r for r in sample] + [r for r in rd]:
                    scanned += 1
                    if len(row) <= max(di, ti, vi):
                        continue
                    dev = row[di].strip()
                    if dev not in out:
                        continue
                    iso = parse_time(row[ti], tz)
                    if iso is None:
                        bad_time += 1
                        continue
                    raw = row[vi].strip()
                    try:
                        val = float(raw)
                    except ValueError:
                        bad_value += 1
                        continue
                    if val < 0:
                        bad_value += 1
                        continue
                    out[dev][iso] = val
                    matched += 1
    for s in skipped:
        log("  略過無法辨識的成員：%s" % s)
    if parsed_members == 0:
        log("!! ZIP 裡沒有任何成員能對應出「裝置／時間／數值」三個欄位")
        log("!! device 找 %s；time 找 %s；value 找欄位名含測項代碼或第一個數值欄" % (DEVICE_HINTS[:3], TIME_HINTS[:3]))
        log("!! 請先跑 --dry-run 看結構，再用 --col-device/--col-time/--col-value 指定（0 起算）")
        sys.exit(3)
    log("  掃描 %d 列（%d 個成員），命中 %d 列（時間無法解析 %d、數值無效 %d，皆丟棄不補值）"
        % (scanned, parsed_members, matched, bad_time, bad_value))
    return out


def merge_write(outdir: str, device: str, param: str, data: dict):
    """把該測項併進 data/iot/<device>/<YYYY-MM>.csv（寬表，以時間去重）。"""
    by_month = {}
    for iso, val in data.items():
        by_month.setdefault(iso[:7], {})[iso] = val
    written = 0
    for month, rows in by_month.items():
        d = os.path.join(outdir, "iot", device)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, month + ".csv")
        table, params = {}, []
        if os.path.exists(path):
            with open(path, newline="", encoding="utf-8") as f:
                rd = csv.reader(f)
                head = next(rd, ["time_utc"])
                params = head[1:]
                for r in rd:
                    table[r[0]] = dict(zip(params, r[1:]))
        if param not in params:
            params.append(param)
        for iso, val in rows.items():
            table.setdefault(iso, {})[param] = ("%g" % val)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time_utc"] + params)
            for iso in sorted(table):
                w.writerow([iso] + [table[iso].get(p, "") for p in params])
        written += len(rows)
        log("  寫入 %s（該月共 %d 列，本次新增/更新 %d 列）" % (path, len(table), len(rows)))
    return written


def update_manifest(outdir: str, tz: str = None):
    root = os.path.join(outdir, "iot")
    devices = {}
    if os.path.isdir(root):
        for dev in sorted(os.listdir(root)):
            months, params, first, last, rows = [], set(), None, None, 0
            for fn in sorted(os.listdir(os.path.join(root, dev))):
                if not fn.endswith(".csv"):
                    continue
                months.append(fn[:-4])
                with open(os.path.join(root, dev, fn), newline="", encoding="utf-8") as f:
                    rd = csv.reader(f)
                    head = next(rd, ["time_utc"])
                    params.update(head[1:])
                    for r in rd:
                        rows += 1
                        if first is None or r[0] < first:
                            first = r[0]
                        if last is None or r[0] > last:
                            last = r[0]
            devices[dev] = {"months": months, "params": sorted(params),
                            "first": first, "last": last, "rows": rows}
    path = os.path.join(outdir, "manifest.json")
    os.makedirs(outdir, exist_ok=True)
    # 保留「來源時間是用哪個時區解讀的」與「有沒有實測驗證過」，讓網頁能誠實標示。
    verified = os.path.exists(os.path.join(outdir, "_tzcheck", "CONFIRMED"))
    meta = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"generated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                   "source": "history.colife.org.tw（環境部_智慧城鄉空品微型感測器）",
                   "note": "time_utc 為 UTC；本檔由 scripts/hist_extract.py 產生",
                   "source_tz": tz or meta.get("source_tz"),
                   "source_tz_verified": verified,
                   "devices": devices}, f, ensure_ascii=False, indent=1)
    log("已更新 %s（%d 台裝置）" % (path, len(devices)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYYMMDD")
    ap.add_argument("--until", help="YYYYMMDD，給定則處理 --date 到 --until 的每一天")
    ap.add_argument("--param", default="humidity", help="檔名裡的測項代碼，例如 humidity")
    ap.add_argument("--label", help="輸出 CSV 的欄位名稱，預設同 --param")
    ap.add_argument("--url", help="直接指定完整下載網址（除錯用）")
    ap.add_argument("--from-file", help="不下載，直接處理本機 ZIP（測試用）")
    ap.add_argument("--devices", default="", help="裝置編號，逗號分隔")
    ap.add_argument("--tz", choices=["taipei", "utc"], help="來源時間欄位的時區；正式萃取時必填")
    ap.add_argument("--out", default="data")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-missing", action="store_true",
                    help="某一天的檔案還沒產出時跳過該天（整批都沒抓到仍會失敗）")
    ap.add_argument("--tz-check", action="store_true",
                    help="判定來源時間欄位的時區（逐時剖面＋與 API 快照逐筆比對），不寫資料")
    ap.add_argument("--api-snapshot", action="store_true",
                    help="把 API 目前保留的那 ~2 小時存進 <out>/_tzcheck，供日後比對時區")
    ap.add_argument("--probe", nargs="?", const=PROBE_CODES, default=None,
                    help="探測某一天有哪些測項檔（逗號分隔的候選代碼，預設試常見的幾種）")
    ap.add_argument("--col-device", type=int, default=-1)
    ap.add_argument("--col-time", type=int, default=-1)
    ap.add_argument("--col-value", type=int, default=-1)
    a = ap.parse_args()

    probing = a.probe is not None
    if a.api_snapshot:
        if not a.devices.strip():
            ap.error("--api-snapshot 需要 --devices")
        label = a.label or a.param
        for dev in [d.strip() for d in a.devices.split(",") if d.strip()]:
            if api_snapshot(a.out, dev, label) is None:
                sys.exit(5)
        return

    dates = []
    if a.from_file:
        dates = [None]
    elif a.date:
        d0 = datetime.strptime(a.date, "%Y%m%d")
        d1 = datetime.strptime(a.until, "%Y%m%d") if a.until else d0
        while d0 <= d1:
            dates.append(d0.strftime("%Y%m%d"))
            d0 += timedelta(days=1)
    elif a.url:
        dates = [None]
    else:
        ap.error("需要 --date 或 --url 或 --from-file")

    devices = [d.strip() for d in a.devices.split(",") if d.strip()]
    if a.tz_check and not devices:
        ap.error("--tz-check 需要 --devices（要比對哪一台裝置）")
    if not (a.dry_run or a.tz_check or probing):
        if not devices:
            ap.error("正式萃取需要 --devices")
        if not a.tz:
            ap.error("正式萃取需要 --tz（先跑 --tz-check 確認來源時區，不要用猜的）")

    if probing:
        codes = [c.strip() for c in a.probe.split(",") if c.strip()]
        for date in dates:
            probe_params(date, codes)
        return

    label = a.label or a.param
    total_rows = 0
    for date in dates:
        with tempfile.TemporaryDirectory() as tmp:
            if a.from_file:
                zpath, url = a.from_file, "(本機檔案) " + a.from_file
            else:
                url = a.url or build_url(date, a.param)
                zpath = os.path.join(tmp, "d.zip")
                log("下載 %s" % url)
                try:
                    size = download(url, zpath)
                except Exception as e:                            # noqa: BLE001
                    # 當天的檔案還沒產出是正常的（站方約在台灣時間 03:00 才放上去）。
                    # 但「抓不到」與「抓到空的」是兩回事，這裡只跳過，不會偽造成功。
                    if a.skip_missing:
                        log("  取不到 %s 的檔案（%s），跳過這一天" % (date, e))
                        continue
                    raise
                log("  完成 %.1f MB" % (size / 1048576))
            log("處理 %s" % (date or url))
            if a.dry_run:
                rc = dry_run(zpath)
                if rc:
                    sys.exit(rc)
                continue
            if a.tz_check:
                rc = tz_check(zpath, devices, label, a.param,
                              (a.col_device, a.col_time, a.col_value),
                              os.path.join(a.out, "_tzcheck"))
                if rc:
                    sys.exit(rc)
                continue
            data = extract(zpath, devices, a.tz, label, a.param,
                           a.col_device, a.col_time, a.col_value)
            for dev, rows in data.items():
                if rows:
                    total_rows += merge_write(a.out, dev, label, rows)
                else:
                    log("  裝置 %s 在這個檔案裡沒有資料" % dev)

    if not (a.dry_run or a.tz_check):
        update_manifest(a.out, a.tz)
        log("完成，共寫入 %d 列" % total_rows)
        if total_rows == 0:
            log("!! 一列都沒有寫入——請確認裝置編號與欄位對應是否正確")
            sys.exit(4)


if __name__ == "__main__":
    main()
