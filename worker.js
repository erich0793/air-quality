/**
 * 空品觀測台 — CORS proxy（Cloudflare Worker）
 *
 * 只有在瀏覽器擋下對 sta.colife.org.tw 的跨來源請求時才需要部署這個。
 * 部署後把 Worker 網址（結尾要有 ?url=）填進網站的「CORS proxy 前綴」欄位：
 *
 *   https://你的名稱.你的帳號.workers.dev/?url=
 *
 * 部署方式（免費方案即可）：
 *   1. dash.cloudflare.com → Workers & Pages → Create → Worker
 *   2. 把這個檔案全部貼上，Deploy
 *
 * 安全性：只轉發 ALLOWED_HOSTS 裡的網域，不是開放式 proxy。
 */

const ALLOWED_HOSTS = [
  "sta.colife.org.tw",
  "history.colife.org.tw"
];

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,OPTIONS",
  "Access-Control-Allow-Headers": "Accept,Content-Type"
};

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS });
    }
    if (request.method !== "GET") {
      return json({ error: "只接受 GET" }, 405);
    }

    const target = new URL(request.url).searchParams.get("url");
    if (!target) {
      return json({ error: "缺少 ?url= 參數" }, 400);
    }

    let dest;
    try {
      dest = new URL(target);
    } catch {
      return json({ error: "url 參數不是合法網址" }, 400);
    }

    if (dest.protocol !== "https:" || !ALLOWED_HOSTS.includes(dest.hostname)) {
      return json({ error: "不在允許清單內的網域：" + dest.hostname }, 403);
    }

    try {
      const upstream = await fetch(dest.toString(), {
        headers: { Accept: "application/json" },
        // 歷史觀測值不會變動，讓 Cloudflare 邊緣節點快取 5 分鐘
        cf: { cacheTtl: 300, cacheEverything: true }
      });

      return new Response(upstream.body, {
        status: upstream.status,
        headers: {
          ...CORS,
          "Content-Type": upstream.headers.get("Content-Type") || "application/json;charset=UTF-8",
          "Cache-Control": "public, max-age=120"
        }
      });
    } catch (err) {
      return json({ error: "上游請求失敗：" + err.message }, 502);
    }
  }
};

function json(body, status) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json;charset=UTF-8" }
  });
}
