// Pengujian Worker dengan node --test (Node 20 ke atas), tanpa pustaka tambahan.
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import worker from "./src/index.js";

const ORIGIN = "https://feliksmakarios.github.io";
const env = {
  GEMINI_API_KEY: "kunci-uji",
  EMBED_MODEL: "gemini-embedding-001",
  EMBED_DIMENSIONS: "4",
  ALLOWED_ORIGINS: `${ORIGIN},http://localhost:8000`,
};
const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
});

function post(body, origin = ORIGIN) {
  return new Request("https://w.example/embed", {
    method: "POST",
    headers: { "Content-Type": "application/json", Origin: origin },
    body: JSON.stringify(body),
  });
}

function mockGemini(status, payload) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(payload), { status });
  };
  return calls;
}

test("mengembalikan vektor pertanyaan dan header CORS", async () => {
  const calls = mockGemini(200, { embedding: { values: [0.1, 0.2, 0.3, 0.4] } });
  const resp = await worker.fetch(post({ text: "  terjemahan   mesin Batak " }), env);
  assert.equal(resp.status, 200);
  assert.equal(resp.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  const data = await resp.json();
  assert.deepEqual(data, { model: "gemini-embedding-001", dimensions: 4, embedding: [0.1, 0.2, 0.3, 0.4] });
  assert.match(calls[0].url, /models\/gemini-embedding-001:embedContent$/);
  assert.equal(calls[0].init.headers["x-goog-api-key"], "kunci-uji");
  const sent = JSON.parse(calls[0].init.body);
  assert.equal(sent.taskType, "RETRIEVAL_QUERY");
  assert.equal(sent.outputDimensionality, 4);
  assert.equal(sent.content.parts[0].text, "terjemahan mesin Batak");
});

test("menolak asal halaman yang tidak diizinkan", async () => {
  const calls = mockGemini(200, {});
  const resp = await worker.fetch(post({ text: "abc" }, "https://contoh.com"), env);
  assert.equal(resp.status, 403);
  assert.equal(resp.headers.get("Access-Control-Allow-Origin"), null);
  assert.equal(calls.length, 0);
});

test("preflight CORS", async () => {
  const req = new Request("https://w.example/embed", { method: "OPTIONS", headers: { Origin: ORIGIN } });
  const resp = await worker.fetch(req, env);
  assert.equal(resp.status, 204);
  assert.equal(resp.headers.get("Access-Control-Allow-Methods"), "GET, POST, OPTIONS");
});

test("teks kosong ditolak tanpa memanggil Gemini", async () => {
  const calls = mockGemini(200, {});
  const resp = await worker.fetch(post({ text: " " }), env);
  assert.equal(resp.status, 400);
  assert.equal(calls.length, 0);
});

test("teks dipotong 300 karakter", async () => {
  const calls = mockGemini(200, { embedding: { values: [1, 0, 0, 0] } });
  await worker.fetch(post({ text: "a".repeat(1000) }), env);
  assert.equal(JSON.parse(calls[0].init.body).content.parts[0].text.length, 300);
});

test("batas per IP", async () => {
  mockGemini(200, { embedding: { values: [1, 0, 0, 0] } });
  const limited = { ...env, LIMITER: { limit: async () => ({ success: false }) } };
  const resp = await worker.fetch(post({ text: "abc" }), limited);
  assert.equal(resp.status, 429);
});

test("kuota Gemini habis menjadi 503", async () => {
  mockGemini(429, { error: { message: "quota" } });
  const resp = await worker.fetch(post({ text: "abc" }), env);
  assert.equal(resp.status, 503);
  assert.equal((await resp.json()).error, "kuota Gemini sedang habis");
});

test("vektor dengan dimensi salah ditolak", async () => {
  mockGemini(200, { embedding: { values: [1, 2] } });
  const resp = await worker.fetch(post({ text: "abc" }), env);
  assert.equal(resp.status, 502);
});

test("pemeriksaan kesehatan", async () => {
  const resp = await worker.fetch(new Request("https://w.example/health"), env);
  assert.deepEqual(await resp.json(), {
    ok: true, model: "gemini-embedding-001", dimensions: 4, key_configured: true,
  });
});
