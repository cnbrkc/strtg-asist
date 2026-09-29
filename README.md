# STRtg Asist — Telegram Story Kartı

`cnbrkc/str-asist` içindeki Streamlit Story Asistanı, `rls-asist` → `rlstg-asist` taşınmasındaki çalışma modeline benzer şekilde Telegram'a taşındı.

Bu sürümde:

- Telegram'dan gelen görsel ve açıklama Cloudflare Worker tarafından alınır.
- Worker, GitHub Actions'taki `Telegram Story Card` workflow'unu tetikler.
- GitHub Actions görseli Telegram'dan indirir ve Pillow ile orijinal 1080x1920 Story şablonunu üretir.
- Hazır PNG aynı Telegram sohbetine geri gönderilir.
- Üretim Gemini, sunucu veya veritabanı gerektirmez; yalnızca Telegram, Cloudflare Worker ve GitHub Actions kullanır.

## 1. Telegram'da nasıl kullanılacak?

Botu kurduktan sonra bota özel sohbetten şu şekilde gönder:

1. Görseli **Fotoğraf** olarak seç.
2. Açıklama/caption alanına ilk satıra başlığı yaz.
3. İkinci ve sonraki satırlara alt metni, fiyatı veya detayı yaz.
4. Gönder.

Örnek caption:

```text
DAYANIKLILIĞIN ADI: TOYOTA COROLLA
Sadece bu hafta geçerlidir! Fiyat: 1.250.000 TL
```

İlk satır, eski Streamlit uygulamasındaki **Başlık** alanına; kalan satırlar **Alt Metin** alanına karşılık gelir. Başlık Türkçe kurallara göre büyük harfe çevrilir. Alt metinde yazdığın satır sonları kartta da korunur. Sonuç 1080x1920 PNG story kartıdır.

`/start` veya `/help` komutları kullanım talimatını gösterir. Görsel açıklamasız gönderilirse bot nasıl göndermen gerektiğini söyler.

## 2. Kullanılan mimari

```text
Telegram
   ↓ webhook
Cloudflare Worker
   ↓ GitHub workflow_dispatch
GitHub Actions (Pillow)
   ↓ sendPhoto
Telegram'a hazır Story kartı
```

Dosya yapısı:

```text
strtg-asist/
├─ strtg_asist/                  # Tek Python paketi
│  ├─ story_card.py              # Streamlit'ten bağımsız, ortak story üretim motoru
│  └─ telegram_worker.py         # Actions içinde görsel indirme, üretim ve gönderim
├─ story_asistani.py             # Yerel Streamlit arayüzü (isteğe bağlı)
├─ cloudflare/
│  ├─ telegram-webhook.js        # Telegram webhook'u ve GitHub dispatch köprüsü
│  └─ wrangler.toml              # Worker yapılandırması
├─ .github/workflows/
│  ├─ telegram-story.yml         # Üretim workflow'u
│  └─ ci.yml                     # Test + lint + yapılandırma tutarlılık kontrolleri
├─ assets/                       # Logo ve Roboto fontları
├─ tests/                        # Kart motoru ve Telegram worker testleri
├─ pyproject.toml                # pytest + ruff yapılandırması
├─ requirements.txt              # Streamlit arayüzü + motor
├─ requirements-telegram.txt     # Actions üretim runtime'ı (yalnızca Pillow)
└─ requirements-dev.txt          # Test ve lint araçları
```

> Paket adı bilerek `telegram` değil `strtg_asist`: üst seviyede `telegram` adlı bir
> paket, PyPI'daki `python-telegram-bot` kütüphanesinin `telegram` modülünü gölgeler.

## 3. Ön hazırlık

### 3.1 Telegram botu oluştur

1. Telegram'da [@BotFather](https://t.me/BotFather) hesabını aç.
2. `/newbot` gönder ve bot adını belirle.
3. BotFather'ın verdiği **HTTP API token** değerini güvenli bir yere kopyala.
4. Botla özel sohbet aç. Güvenlik için ilk kurulumda grup yerine özel sohbet kullanılması önerilir.

Bot token'ını GitHub'a veya bu repoya yazma; aşağıdaki secret alanlarına koy.

### 3.2 Telegram chat ID değerini öğren

Botu yalnızca senin kullanmanı istiyorsan chat ID allowlist'ini aç:

1. Telegram'da [@userinfobot](https://t.me/userinfobot) hesabından chat ID değerini öğren veya kendi küçük yardımcı botunu kullan.
2. Değeri ileride Cloudflare Worker'daki `ALLOWED_CHAT_IDS` değişkenine yaz.
3. Birden fazla sohbet için virgülle ayır: `123456789,-100987654321`.

`ALLOWED_CHAT_IDS` boş bırakılırsa bot gelen herkese açık olur. Üretim kotası ve Actions dakikaları açısından allowlist kullanılması kuvvetle önerilir.

### 3.3 GitHub Actions secret'ı ekle

`cnbrkc/strtg-asist` → **Settings → Secrets and variables → Actions → New repository secret** yolunu aç ve şu secret'ı ekle:

| Secret | Değer |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather'ın verdiği Telegram token'ı |

Workflow başka bir Gemini veya Cloudflare secret'ı istemez.

### 3.4 GitHub dispatch token'ı oluştur

Cloudflare Worker'ın bu repodaki workflow'u başlatabilmesi için bir GitHub token gerekir. Fine-grained token tercih et:

1. GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens**.
2. Repository access bölümünde yalnızca `cnbrkc/strtg-asist` reposunu seç.
3. Repository permissions altında **Actions: Read and write** izni ver.
4. Token'ı oluştur ve bir daha gösterilmeyeceği için kopyala.

Bu token'ı GitHub secret'ı olarak değil, Cloudflare Worker secret'ı olarak kullanacağız. Sohbete veya koda yazma.

## 4. Cloudflare Worker kurulumu

Cloudflare hesabında **Workers & Pages → Create application → Worker** yoluyla bir Worker oluşturabilirsin. Bilgisayardan Wrangler ile yapmak daha kolaydır.

### 4.1 Wrangler ile giriş

Node.js kurulu değilse önce Node.js LTS kur. Sonra repo klasöründe:

```bash
npx wrangler login
```

Bu repodaki hazır ayar dosyası `cloudflare/wrangler.toml` içindedir. Worker adı `strtg-asist-webhook`, GitHub reposu da `cnbrkc/strtg-asist` olarak ayarlanmıştır.

### 4.2 Worker'ı yayınla

```bash
npx wrangler deploy --config cloudflare/wrangler.toml
```

Komut sonunda buna benzer bir adres göreceksin:

```text
https://strtg-asist-webhook.<hesap-adı>.workers.dev
```

Bu adresi not al; `WORKER_URL` olarak kullanacağız.

### 4.3 Secret'ları ekle

Aşağıdaki komutları tek tek çalıştır. Komut senden secret değerini güvenli şekilde ister; değerleri terminal komutunun içine yazmak zorunda kalmazsın.

```bash
npx wrangler secret put TELEGRAM_BOT_TOKEN --config cloudflare/wrangler.toml
npx wrangler secret put TELEGRAM_WEBHOOK_SECRET --config cloudflare/wrangler.toml
npx wrangler secret put GITHUB_TOKEN --config cloudflare/wrangler.toml
```

- `TELEGRAM_BOT_TOKEN`: BotFather token'ı.
- `TELEGRAM_WEBHOOK_SECRET`: Telegram webhook doğrulaması için rastgele gizli metin.
- `GITHUB_TOKEN`: Bir önceki bölümde oluşturduğun, yalnızca `strtg-asist` için Actions `Read and write` yetkili GitHub fine-grained token'ı.

Webhook secret üretmek için örnek:

```bash
openssl rand -hex 32
```

Bu değeri `TELEGRAM_WEBHOOK_SECRET` secret'ı olarak kullan ve sonradan `/setup` komutunda aynı değeri yaz.

### 4.4 İsteğe bağlı chat allowlist'i ekle

`cloudflare/wrangler.toml` içindeki yorum satırını açıp kendi chat ID'ni yaz:

```toml
[vars]
GITHUB_REPOSITORY = "cnbrkc/strtg-asist"
ALLOWED_CHAT_IDS = "123456789"
```

Ardından tekrar yayınla:

```bash
npx wrangler deploy --config cloudflare/wrangler.toml
```

Birden fazla ID:

```toml
ALLOWED_CHAT_IDS = "123456789,-100987654321"
```

## 5. Telegram webhook'unu etkinleştir

`TELEGRAM_WEBHOOK_SECRET` olarak kullandığın değeri ve Worker adresini yerleştir:

```bash
curl -i "https://WORKER_URL/setup?key=TELEGRAM_WEBHOOK_SECRET"
```

Örnek:

```bash
curl -i "https://strtg-asist-webhook.ornek.workers.dev/setup?key=9f4c..."
```

Başarılı cevapta `OK - Telegram webhook aktif.` görmelisin. Worker'ın temel adresini tarayıcıda açtığında da `STRtg Telegram Webhook OK` cevabı alınır.

Kurulumdan sonra bota `/start` gönder. Yardım mesajı geliyorsa webhook çalışıyor demektir.

> Güvenlik: `/setup?key=...` adresini paylaşma. Kurulumdan sonra webhook secret'ını yeniden değiştirmek istersen hem Worker secret'ını hem de `/setup` çağrısını güncelle.

## 6. Yerel Streamlit arayüzünü çalıştırma (isteğe bağlı)

Telegram kurulumu için gerekli değildir; eski `str-asist` deneyimini bilgisayarda korur.

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell için: .venv\Scripts\Activate.ps1

pip install -r requirements.txt
python -m streamlit run story_asistani.py
```

Tarayıcıda Streamlit adresi açılır. Telegram ve Streamlit aynı
`strtg_asist/story_card.py` motorunu kullanır.

## 7. Sorun giderme

### Bot hiç cevap vermiyor

- `/setup?key=...` komutunu doğru Worker URL'siyle tekrar çalıştır.
- Worker URL'sini tarayıcıda açıp `STRtg Telegram Webhook OK` gördüğünü doğrula.
- Cloudflare Worker secret'larında `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_WEBHOOK_SECRET` isimlerinin birebir doğru olduğuna bak.
- `/start` göndererek test et.

### "Üretim kuyruğa alınamadı" mesajı

- Cloudflare'daki `GITHUB_TOKEN` gerçekten fine-grained token mı kontrol et.
- Token'ın repository access listesinde `cnbrkc/strtg-asist` var mı kontrol et.
- **Actions: Read and write** iznini aç.
- `GITHUB_REPOSITORY` değerinin `cnbrkc/strtg-asist` olduğundan emin ol.
- GitHub reposunda `.github/workflows/telegram-story.yml` dosyasının `main` dalında bulunduğunu kontrol et.

### Workflow kırmızı oluyor

GitHub → **Actions → Telegram Story Card** → başarısız run'a gir. En sık sebepler:

- GitHub repo secret'ı `TELEGRAM_BOT_TOKEN` eksik veya yanlış.
- Telegram dosyası indirilemedi; fotoğrafı yeniden gönder.
- Caption boş veya ilk satır/alt metin bilgisi eklenmemiş.
- Telegram'ın fotoğraf boyutu sınırı aşılmış; görseli küçültüp tekrar dene.

### Kullanıcı yetkisiz uyarısı alıyor

`ALLOWED_CHAT_IDS` aktifse Telegram chat ID'sini tam olarak, başında/sonunda boşluk olmadan yaz. Grup ID'leri genellikle `-100...` ile başlar.

## 8. Geliştirme ve test

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

pytest                                            # birim testleri
ruff check strtg_asist tests story_asistani.py    # lint
node --check cloudflare/telegram-webhook.js       # Worker sözdizimi
```

Her pull request'te aynı kontroller GitHub Actions CI tarafından çalıştırılır. CI
ayrıca iki ek güvenlik ağı içerir:

- **Telegram runtime importu:** Worker yalnızca `requirements-telegram.txt`
  (Pillow) ile import edilebiliyor mu? Üretim workflow'u Streamlit kurmadığı için
  kazara eklenen bir bağımlılık ancak üretimde patlardı.
- **`workflow_dispatch` input eşleşmesi:** Cloudflare Worker'ın gönderdiği input
  adları ile workflow'un beklediği adlar ayrışırsa GitHub dispatch'i `422` ile
  reddeder ve bot sessizce çalışmaz olur. Bu kontrol farkı PR'da yakalar.
