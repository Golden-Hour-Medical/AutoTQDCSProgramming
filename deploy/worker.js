export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return json({ ok: true, service: "autotq-gate" }, 200);
    }

    if (url.pathname === "/resolve" && request.method === "POST") {
      return handleResolve(request, env, url);
    }

    if (url.pathname === "/download" && request.method === "GET") {
      return handleDownload(url, env);
    }

    return json({ error: "not_found" }, 404);
  },
};

async function handleResolve(request, env, url) {
  const body = await safeJson(request);
  const password = typeof body.password === "string" ? body.password : "";
  if (!password || password !== env.ACCESS_PASSWORD) {
    return json({ error: "unauthorized" }, 401);
  }

  const key = env.CURRENT_OBJECT_KEY;
  if (!key) {
    return json({ error: "server_not_configured", detail: "CURRENT_OBJECT_KEY missing" }, 500);
  }

  const ttl = parseInt(env.URL_TTL_SECONDS || "900", 10);
  const exp = Math.floor(Date.now() / 1000) + (Number.isFinite(ttl) ? ttl : 900);
  const payload = `${key}.${exp}`;
  const sig = await signPayload(payload, env.SIGNING_SECRET || "");

  const zipUrl = `${url.origin}/download?key=${encodeURIComponent(key)}&exp=${exp}&sig=${sig}`;
  const version = env.CURRENT_VERSION || key;
  return json({ zip_url: zipUrl, version }, 200);
}

async function handleDownload(url, env) {
  const key = url.searchParams.get("key") || "";
  const exp = parseInt(url.searchParams.get("exp") || "0", 10);
  const sig = url.searchParams.get("sig") || "";

  if (!key || !exp || !sig) {
    return json({ error: "invalid_request" }, 400);
  }

  if (key !== env.CURRENT_OBJECT_KEY) {
    return json({ error: "invalid_key" }, 403);
  }

  const now = Math.floor(Date.now() / 1000);
  if (exp < now) {
    return json({ error: "expired" }, 403);
  }

  const payload = `${key}.${exp}`;
  const expected = await signPayload(payload, env.SIGNING_SECRET || "");
  if (expected !== sig) {
    return json({ error: "invalid_signature" }, 403);
  }

  const object = await env.RELEASES.get(key);
  if (!object) {
    return json({ error: "missing_object" }, 404);
  }

  const headers = new Headers();
  headers.set("content-type", "application/zip");
  headers.set("cache-control", "no-store");
  headers.set("content-disposition", `attachment; filename="AutoTQProduction.zip"`);
  if (object.httpEtag) {
    headers.set("etag", object.httpEtag);
  }

  return new Response(object.body, { status: 200, headers });
}

async function safeJson(request) {
  try {
    return await request.json();
  } catch {
    return {};
  }
}

async function signPayload(payload, secret) {
  if (!secret) {
    return "";
  }
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(payload));
  return base64Url(sig);
}

function base64Url(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function json(body, status) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}
