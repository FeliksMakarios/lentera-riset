// Batas pemakaian harian untuk seluruh pengunjung (bukan per IP).
//
// Batas per IP di wrangler.toml ([[ratelimits]]) hanya menahan satu pengguna yang bertanya
// terlalu cepat. Batas harian ini menjaga kuota Gemini secara keseluruhan, karena kunci yang
// sama (atau proyek Google yang sama) juga dipakai alur kerja harian untuk meringkas makalah.
//
// Hitungannya disimpan di satu Durable Object ("global"). Setiap permintaan ke Durable Object
// diproses berurutan, jadi hitungan tidak bisa terlewat walaupun ada permintaan serentak.
// Hitungan direset otomatis setiap pergantian hari UTC.

import { json } from "./util.js";

export function today() {
  return new Date().toISOString().slice(0, 10);
}

export class UsageCounter {
  constructor(state) {
    this.storage = state.storage;
  }

  async fetch(request) {
    const url = new URL(request.url);
    const kind = (url.searchParams.get("kind") || "lain").replace(/[^a-z]/g, "");
    const limit = Number(url.searchParams.get("limit") || 0);
    const day = today();
    const key = `${day}:${kind}`;
    const used = (await this.storage.get(key)) || 0;
    if (limit > 0 && used >= limit) {
      return json({ ok: false, used, limit }, 200);
    }
    await this.storage.put(key, used + 1);
    if (used === 0) {
      // Hari baru: buang hitungan hari-hari sebelumnya.
      const old = await this.storage.list({ end: day });
      const stale = [...old.keys()].filter((k) => !k.startsWith(day));
      if (stale.length) await this.storage.delete(stale);
    }
    return json({ ok: true, used: used + 1, limit }, 200);
  }
}

// Ambil satu jatah dari batas harian `kind`. Jika Durable Object tidak terpasang atau
// gagal dihubungi, permintaan tetap dilayani (batas per IP tetap berlaku).
export async function takeDaily(env, kind, limit) {
  if (!env.USAGE || !(limit > 0)) return { ok: true };
  try {
    const stub = env.USAGE.get(env.USAGE.idFromName("global"));
    const resp = await stub.fetch(`https://usage.internal/take?kind=${kind}&limit=${limit}`);
    return await resp.json();
  } catch (e) {
    console.log(`batas harian tidak bisa diperiksa: ${e.message}`);
    return { ok: true };
  }
}

// Detik sampai pergantian hari UTC, untuk header Retry-After.
export function secondsToReset(now = new Date()) {
  const next = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1);
  return Math.max(60, Math.ceil((next - now.getTime()) / 1000));
}
