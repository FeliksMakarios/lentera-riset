// Fungsi bersama untuk /embed dan /ask.

export const GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/";

export function json(body, status, headers) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...headers },
  });
}
