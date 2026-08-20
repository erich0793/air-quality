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

  # 正式萃取（時區必須明講，沒有預設值）
  python3 scripts/hist_extract.py --date 20260819 --param humidity \
      --devices 13580653094 --tz taipei --out data
"""

import argparse, base64, csv, io, json, os, sys, tempfile, urllib.parse, urllib.request, zipfile
from datetime import datetime, timedelta, timezone

BASE = "https://history.colife.org.tw"
DIR = "/空氣品質/環境部_智慧城鄉空品微型感測器"
TPE = timezone(timedelta(hours=8))

# ZIP 內的欄位名未知，這裡列出可能的候選；找不到就大聲失敗，不猜。
DEVICE_HINTS = ("stationid", "station_id", "deviceid", "device_id", "locationid", "location_id", "裝置編號", "測站編號")
TIME_HINTS = ("time", "datetime", "timestamp", "phenomenontime", "datacreationdate", "obs_time", "時間", "觀測時間")
VALUE_HINTS = ("value", "result", "數值", "觀測值", "concentration")


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


def update_manifest(outdir: str):
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
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"generated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                   "source": "history.colife.org.tw（環境部_智慧城鄉空品微型感測器）",
                   "note": "time_utc 為 UTC；本檔由 scripts/hist_extract.py 產生",
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
    ap.add_argument("--col-device", type=int, default=-1)
    ap.add_argument("--col-time", type=int, default=-1)
    ap.add_argument("--col-value", type=int, default=-1)
    a = ap.parse_args()

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
    if not a.dry_run:
        if not devices:
            ap.error("正式萃取需要 --devices")
        if not a.tz:
            ap.error("正式萃取需要 --tz（先跑 --dry-run 對照 API 確認來源時區，不要用猜的）")

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
                size = download(url, zpath)
                log("  完成 %.1f MB" % (size / 1048576))
            log("處理 %s" % (date or url))
            if a.dry_run:
                rc = dry_run(zpath)
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

    if not a.dry_run:
        update_manifest(a.out)
        log("完成，共寫入 %d 列" % total_rows)
        if total_rows == 0:
            log("!! 一列都沒有寫入——請確認裝置編號與欄位對應是否正確")
            sys.exit(4)


if __name__ == "__main__":
    main()
