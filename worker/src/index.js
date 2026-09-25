// Cloudflare Worker untuk pencarian semantik Lentera Riset.
//
// Halaman pencarian mengirim teks pertanyaan ke POST /embed. Worker mengubahnya
// menjadi vektor makna dengan model embedding Gemini (kunci API disimpan sebagai
// secret GEMINI_API_KEY, tidak pernah sampai ke peramban), lalu mengembalikan
// vektornya. Model dan dimensinya harus sama dengan [embeddings] di
// config/topics.toml, karena vektor makalah dibuat dengan pengaturan itu.

const MAX_CHARS = 300;
const GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/";

function allowedOrigins(env) {
  return (env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function json(body, status, headers) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });
}

function settings(env) {
  return {
    model: env.EMBED_MODEL || "gemini-embedding-001",
    dimensions: Number(env.EMBED_DIMENSIONS || 256),
  };
}

async function embed(text, env) {
  const { model, dimensions } = settings(env);
  const resp = await fetch(`${GEMINI_URL}${model}:embedContent`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-goog-api-key": env.GEMINI_API_KEY },
    body: JSON.stringify({
      content: { parts: [{ text }] },
      taskType: "RETRIEVAL_QUERY",
      outputDimensionality: dimensions,
    }),
  });
  if (!resp.ok) {
    const detail = (await resp.text()).slice(0, 300);
    const error = new Error(`Gemini ${resp.status}: ${detail}`);
    error.status = resp.status;
    throw error;
  }
  const data = await resp.json();
  const values = data.embedding && data.embedding.values;
  if (!Array.isArray(values) || values.length !== dimensions) {
    throw new Error("respons Gemini tidak berisi vektor yang sesuai");
  }
  return values;
}

async function cached(key, compute) {
  // Cache API tidak aktif di subdomain workers.dev; di domain sendiri ia menghemat kuota.
  const cache = typeof caches !== "undefined" ? caches.default : null;
  const req = new Request(key);
  if (cache) {
    try {
      const hit = await cache.match(req);
      if (hit) return hit.json();
    } catch (e) {
      /* abaikan */
    }
  }
  const value = await compute();
  if (cache) {
    try {
      await cache.put(req, new Response(JSON.stringify(value), {
        headers: { "Content-Type": "application/json", "Cache-Control": "public, max-age=604800" },
      }));
    } catch (e) {
      /* abaikan */
    }
  }
  return value;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";
    const allowed = allowedOrigins(env).includes(origin);
    const cors = allowed ? corsHeaders(origin) : { Vary: "Origin" };

    if (request.method === "OPTIONS") {
      return new Response(null, { status: allowed ? 204 : 403, headers: cors });
    }

    if (request.method === "GET" && (url.pathname === "/" || url.pathname === "/health")) {
      return json({ ok: true, ...settings(env), key_configured: Boolean(env.GEMINI_API_KEY) }, 200, cors);
    }

    if (url.pathname !== "/embed" || request.method !== "POST") {
      return json({ error: "tidak ditemukan" }, 404, cors);
    }
    // Hanya halaman Lentera Riset yang boleh memakai kuota Gemini lewat Worker ini.
    if (!allowed) {
      return json({ error: "asal permintaan tidak diizinkan" }, 403, cors);
    }
    if (!env.GEMINI_API_KEY) {
      return json({ error: "GEMINI_API_KEY belum diisi di Worker" }, 500, cors);
    }
    if (env.LIMITER) {
      const ip = request.headers.get("CF-Connecting-IP") || "anon";
      const { success } = await env.LIMITER.limit({ key: ip });
      if (!success) {
        return json({ error: "terlalu banyak permintaan, coba lagi sebentar lagi" }, 429, cors);
      }
    }

    let text;
    try {
      const body = await request.json();
      text = typeof body.text === "string" ? body.text.trim().replace(/\s+/g, " ") : "";
    } catch (e) {
      text = "";
    }
    if (text.length < 2) {
      return json({ error: "teks pencarian kosong" }, 400, cors);
    }
    text = text.slice(0, MAX_CHARS);

    const { model, dimensions } = settings(env);
    const key = `https://lentera-cache.internal/embed?m=${model}&d=${dimensions}&q=${encodeURIComponent(text.toLowerCase())}`;
    try {
      const embedding = await cached(key, () => embed(text, env));
      return json({ model, dimensions, embedding }, 200, cors);
    } catch (e) {
      const status = e.status === 429 ? 503 : 502;
      const message = e.status === 429 ? "kuota Gemini sedang habis" : "gagal menghubungi Gemini";
      console.log(`embed gagal: ${e.message}`);
      return json({ error: message }, status, cors);
    }
  },
};
