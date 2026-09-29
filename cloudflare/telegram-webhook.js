// strtg-asist Telegram webhook.
//
// Telegram güncellemesini alır, fotoğraf + caption bilgisini doğrular ve
// GitHub Actions workflow_dispatch ile kart üretimini başlatır. Bot token'ı ve
// GitHub token'ı yalnızca Cloudflare Worker secret olarak tutulmalıdır.

const UPDATE_ID_RE = /^\d{1,32}$/;
const TELEGRAM_CAPTION_LIMIT = 1024;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/setup") {
      return setupWebhook(request, env, url);
    }

    if (request.method === "GET") {
      return new Response("STRtg Telegram Webhook OK\n", { status: 200 });
    }

    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    const secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
    if (!env.TELEGRAM_WEBHOOK_SECRET || secret !== env.TELEGRAM_WEBHOOK_SECRET) {
      return new Response("Unauthorized", { status: 401 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("Bad JSON", { status: 400 });
    }

    const message = update?.message;
    const chatId = message?.chat?.id;
    if (!chatId) return new Response("OK", { status: 200 });

    if (!chatAllowed(env, chatId)) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "⛔ Bu bot yalnızca yetkili sohbetlerde çalışıyor.",
      }).catch(() => {});
      // Telegram aynı update'i tekrar tekrar göndermesin.
      return new Response("OK", { status: 200 });
    }

    if (message.text === "/start" || message.text === "/help") {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: helpText(),
      });
      return new Response("OK", { status: 200 });
    }

    const image = extractImage(message);
    if (!image) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "🖼️ Lütfen bir görsel gönder ve açıklama alanını şu biçimde doldur:\n\n"
          + "İLK SATIR: başlık\n"
          + "Diğer satırlar: alt metin / fiyat / detay\n\n"
          + "Görseli Telegram'da Fotoğraf olarak göndermen en iyi sonucu verir.",
      });
      return new Response("OK", { status: 200 });
    }

    const caption = String(message.caption || "").trim();
    if (!caption) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "✍️ Görseli aldım. Şimdi görseli açıklama ekleyerek tekrar gönder.\n\n"
          + "İlk satır başlık, sonraki satırlar alt metin olacak.",
      });
      return new Response("OK", { status: 200 });
    }
    if (caption.length > TELEGRAM_CAPTION_LIMIT) {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: `⚠️ Açıklama ${TELEGRAM_CAPTION_LIMIT} karakteri geçemez. Kısaltıp tekrar gönder.`,
      });
      return new Response("OK", { status: 200 });
    }

    const updateId = String(update.update_id ?? "");
    if (!UPDATE_ID_RE.test(updateId)) return new Response("OK", { status: 200 });

    try {
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "📥 Görselini ve metnini aldım. Story kartı hazırlanıyor...",
      });

      const dispatch = await dispatchWorkflow(env, {
        file_id: image.file_id,
        chat_id: String(chatId),
        caption,
        filename: image.filename || `telegram_${updateId}.jpg`,
        update_id: updateId,
      });

      if (!dispatch.ok) {
        const detail = (await dispatch.text()).slice(0, 700);
        await telegram(env, "sendMessage", {
          chat_id: chatId,
          text: `❌ Üretim kuyruğa alınamadı.\n\nHTTP ${dispatch.status}\n${detail}`,
        }).catch(() => {});
        return new Response("GitHub dispatch failed", { status: 502 });
      }
    } catch (error) {
      console.log("Story dispatch failed", String(error).slice(0, 1000));
      await telegram(env, "sendMessage", {
        chat_id: chatId,
        text: "❌ Story kartı başlatılamadı. Birkaç saniye sonra tekrar dene.",
      }).catch(() => {});
      return new Response("Dispatch failed", { status: 502 });
    }

    return new Response("OK", { status: 200 });
  },
};

function helpText() {
  return "🤖 STR Story Asistanı hazır.\n\n"
    + "1. Bir görsel gönder.\n"
    + "2. Açıklamaya ilk satırda başlığı yaz.\n"
    + "3. İkinci ve sonraki satırlara alt metin, fiyat veya detayı yaz.\n\n"
    + "Örnek:\n"
    + "DAYANIKLILIĞIN ADI: TOYOTA COROLLA\n"
    + "Sadece bu hafta geçerlidir! Fiyat: 1.250.000 TL\n\n"
    + "Bot, 1080x1920 story kartını hazırlayıp geri gönderir.";
}

function extractImage(message) {
  if (Array.isArray(message?.photo) && message.photo.length > 0) {
    const photo = message.photo[message.photo.length - 1];
    return {
      file_id: photo.file_id,
      filename: "telegram_photo.jpg",
    };
  }
  if (message?.document && String(message.document.mime_type || "").startsWith("image/")) {
    return {
      file_id: message.document.file_id,
      filename: safeFilename(message.document.file_name || "telegram_image"),
    };
  }
  return null;
}

function safeFilename(value) {
  const name = String(value || "telegram_image").replaceAll("\\", "/").split("/").pop();
  return name.replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 160) || "telegram_image";
}

function allowedChats(env) {
  const raw = String(env.ALLOWED_CHAT_IDS || "").trim();
  if (!raw) return null;
  return new Set(raw.split(",").map((item) => item.trim()).filter(Boolean));
}

function chatAllowed(env, chatId) {
  const allowlist = allowedChats(env);
  return !allowlist || allowlist.has(String(chatId));
}

async function setupWebhook(request, env, url) {
  const key = url.searchParams.get("key");
  if (!env.TELEGRAM_WEBHOOK_SECRET || key !== env.TELEGRAM_WEBHOOK_SECRET) {
    return new Response("Unauthorized", { status: 401 });
  }

  const result = await telegram(env, "setWebhook", {
    url: `${url.origin}/`,
    secret_token: env.TELEGRAM_WEBHOOK_SECRET,
    allowed_updates: ["message"],
    drop_pending_updates: true,
  });
  return new Response(
    result.ok ? "OK - Telegram webhook aktif.\n" : `ERROR - ${JSON.stringify(result)}\n`,
    { status: result.ok ? 200 : 500, headers: { "content-type": "text/plain; charset=utf-8" } },
  );
}

async function dispatchWorkflow(env, input) {
  const repository = String(env.GITHUB_REPOSITORY || "").trim();
  if (!repository || !env.GITHUB_TOKEN) {
    throw new Error("GITHUB_REPOSITORY veya GITHUB_TOKEN yapılandırılmamış.");
  }
  return fetch(
    `https://api.github.com/repos/${repository}/actions/workflows/telegram-story.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "strtg-asist-telegram-webhook",
        "content-type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs: {
        telegram_file_id: input.file_id,
        telegram_chat_id: input.chat_id,
        telegram_caption: input.caption,
        telegram_filename: input.filename,
        telegram_update_id: input.update_id,
      }}),
    },
  );
}

async function telegram(env, method, payload) {
  if (!env.TELEGRAM_BOT_TOKEN) throw new Error("TELEGRAM_BOT_TOKEN yapılandırılmamış.");
  const response = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  const text = await response.text();
  let result;
  try {
    result = JSON.parse(text);
  } catch {
    result = { ok: false, description: text };
  }
  if (!response.ok || !result.ok) {
    throw new Error(`Telegram API ${response.status}: ${result.description || "bilinmeyen hata"}`);
  }
  return result;
}
