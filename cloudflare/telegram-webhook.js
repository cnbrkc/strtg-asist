// strtg-asist Telegram webhook.
//
// Telegram güncellemesini alır, fotoğraf + caption bilgisini doğrular ve
// GitHub Actions workflow_dispatch ile kart üretimini başlatır. Bot token'ı ve
// GitHub token'ı yalnızca Cloudflare Worker secret olarak tutulmalıdır.

const UPDATE_ID_RE = /^\d{1,32}$/;
const TELEGRAM_CAPTION_LIMIT = 1024;
const WORKFLOW_FILE = "telegram-story.yml";
const WORKFLOW_REF = "main";
const DISPATCH_ATTEMPTS = 2;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/setup") {
      return setupWebhook(env, url);
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

    // Her yol 200 döner: Telegram 2xx olmayan yanıtta aynı update'i tekrar
    // gönderir ve bu, aynı görsel için üst üste kart üretilmesine yol açar.
    try {
      await handleUpdate(env, update);
    } catch (error) {
      console.log("Webhook handler failed", String(error).slice(0, 1000));
    }
    return new Response("OK", { status: 200 });
  },
};

async function handleUpdate(env, update) {
  const message = update?.message;
  const chatId = message?.chat?.id;
  if (!chatId) return;

  if (!chatAllowed(env, chatId)) {
    await notify(env, chatId, "⛔ Bu bot yalnızca yetkili sohbetlerde çalışıyor.");
    return;
  }

  if (isCommand(message?.text, "start") || isCommand(message?.text, "help")) {
    await notify(env, chatId, helpText());
    return;
  }

  const image = extractImage(message);
  if (!image) {
    await notify(
      env,
      chatId,
      "🖼️ Lütfen bir görsel gönder ve açıklama alanını şu biçimde doldur:\n\n"
        + "İLK SATIR: başlık\n"
        + "Diğer satırlar: alt metin / fiyat / detay\n\n"
        + "Görseli Telegram'da Fotoğraf olarak göndermen en iyi sonucu verir.",
    );
    return;
  }

  const caption = String(message.caption || "").trim();
  if (!caption) {
    await notify(
      env,
      chatId,
      "✍️ Görseli aldım. Şimdi görseli açıklama ekleyerek tekrar gönder.\n\n"
        + "İlk satır başlık, sonraki satırlar alt metin olacak.",
    );
    return;
  }

  // Telegram sınırı kod noktası bazlıdır; String.length emojileri iki sayar.
  if ([...caption].length > TELEGRAM_CAPTION_LIMIT) {
    await notify(
      env,
      chatId,
      `⚠️ Açıklama ${TELEGRAM_CAPTION_LIMIT} karakteri geçemez. Kısaltıp tekrar gönder.`,
    );
    return;
  }

  const updateId = String(update.update_id ?? "");
  if (!UPDATE_ID_RE.test(updateId)) return;

  await notify(env, chatId, "📥 Görselini ve metnini aldım. Story kartı hazırlanıyor...");

  const dispatch = await dispatchWorkflow(env, {
    file_id: image.file_id,
    chat_id: String(chatId),
    caption,
    filename: image.filename || `telegram_${updateId}.jpg`,
    update_id: updateId,
  });

  if (!dispatch.ok) {
    const detail = (await dispatch.text().catch(() => "")).slice(0, 700);
    console.log("GitHub dispatch failed", dispatch.status, detail);
    await notify(
      env,
      chatId,
      `❌ Üretim kuyruğa alınamadı.\n\nHTTP ${dispatch.status}\n${detail}\n\n`
        + "Birkaç saniye sonra görseli tekrar gönderebilirsin.",
    );
  }
}

function isCommand(text, name) {
  // Gruplarda Telegram komutu `/start@BotAdi` biçiminde iletir.
  return new RegExp(`^/${name}(@[A-Za-z0-9_]+)?$`).test(String(text || "").trim());
}

/** Bildirim gönderemezsek akışı kesmeyelim; hata log'a düşsün. */
async function notify(env, chatId, text) {
  try {
    await telegram(env, "sendMessage", { chat_id: chatId, text });
  } catch (error) {
    console.log("sendMessage failed", String(error).slice(0, 500));
  }
}

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

async function setupWebhook(env, url) {
  const key = url.searchParams.get("key");
  if (!env.TELEGRAM_WEBHOOK_SECRET || key !== env.TELEGRAM_WEBHOOK_SECRET) {
    return new Response("Unauthorized", { status: 401 });
  }

  try {
    const result = await telegram(env, "setWebhook", {
      url: `${url.origin}/`,
      secret_token: env.TELEGRAM_WEBHOOK_SECRET,
      allowed_updates: ["message"],
      drop_pending_updates: true,
    });
    return text(result.ok ? "OK - Telegram webhook aktif.\n" : `ERROR - ${JSON.stringify(result)}\n`,
      result.ok ? 200 : 500);
  } catch (error) {
    return text(`ERROR - ${String(error).slice(0, 500)}\n`, 500);
  }
}

function text(body, status) {
  return new Response(body, {
    status,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}

async function dispatchWorkflow(env, input) {
  const repository = String(env.GITHUB_REPOSITORY || "").trim();
  if (!repository || !env.GITHUB_TOKEN) {
    throw new Error("GITHUB_REPOSITORY veya GITHUB_TOKEN yapılandırılmamış.");
  }

  const body = JSON.stringify({
    ref: WORKFLOW_REF,
    inputs: {
      telegram_file_id: input.file_id,
      telegram_chat_id: input.chat_id,
      telegram_caption: input.caption,
      telegram_filename: input.filename,
      telegram_update_id: input.update_id,
    },
  });

  let response;
  for (let attempt = 1; attempt <= DISPATCH_ATTEMPTS; attempt += 1) {
    response = await fetch(
      `https://api.github.com/repos/${repository}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "strtg-asist-telegram-webhook",
          "content-type": "application/json",
        },
        body,
      },
    );
    // 4xx yapılandırma hatasıdır, tekrar denemek işe yaramaz.
    if (response.ok || response.status < 500 || attempt === DISPATCH_ATTEMPTS) break;
    await new Promise((resolve) => setTimeout(resolve, 500 * attempt));
  }
  return response;
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
  const raw = await response.text();
  let result;
  try {
    result = JSON.parse(raw);
  } catch {
    result = { ok: false, description: raw };
  }
  if (!response.ok || !result.ok) {
    throw new Error(`Telegram API ${response.status}: ${result.description || "bilinmeyen hata"}`);
  }
  return result;
}
