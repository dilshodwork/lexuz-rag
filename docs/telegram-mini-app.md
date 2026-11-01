# Dalil'ni Telegram Mini App qilib ulash

Bu ishni Space ishga tushib, `https://<user>-dalil.hf.space` manzili brauzerda ochilgandan keyin qiling.
Telegram faqat HTTPS manzilni qabul qiladi — Hugging Face manzili HTTPS, alohida sertifikat kerak emas.

## 1. Bot yaratish (BotFather)

1. Telegram'da **@BotFather** ni oching (ko'k belgili rasmiy bot) va **Start** bosing.
2. `/newbot` yuboring.
3. Botning ko'rinadigan nomini yozing, masalan: `Dalil — qonunchilik`.
4. Username yozing — oxiri `bot` bilan tugashi shart, masalan: `dalil_uz_bot`. Band bo'lsa boshqasini sinang.
5. BotFather token beradi: `1234567890:AA...` ko'rinishida. **Bu parol.** Hech kimga, hech qaysi chatga
   (shu jumladan AI yordamchiga) yubormang. Faqat pastdagi 3-qadamdagi joylarga qo'yasiz.

## 2. Mini App'ni ulash

Ikki yo'l bor, ikkalasini ham qilish mumkin.

**A. Menyu tugmasi** (chat pastidagi "Ochish" tugmasi — eng qulayi):

1. BotFather'da `/mybots` → botingizni tanlang → **Bot Settings** → **Menu Button** → **Configure menu button**.
2. URL so'raganda Space manzilini yuboring: `https://<user>-dalil.hf.space`
3. Tugma nomini yozing, masalan: `Dalil`.

**B. Asosiy Mini App** (bot profilida "Open App" tugmasi va `t.me/<bot>?startapp` havolasi):

1. `/mybots` → botingiz → **Bot Settings** → **Configure Mini App** → **Enable Mini App**.
2. URL: `https://<user>-dalil.hf.space`

Ixtiyoriy: `/setdescription` (bot nima qilishi), `/setuserpic` (rasm), `/setabouttext`.

## 3. Token qayerga qo'yiladi

Token server Mini App foydalanuvchisini ishonchli aniqlashi uchun kerak: Telegram har ochilishda `initData`
yuboradi, server uning imzosini token bilan tekshiradi (HMAC). Shunda bepul limit Telegram akkaunti bo'yicha
hisoblanadi va uni brauzer xotirasini tozalab chetlab o'tib bo'lmaydi.

* **Lokal kompyuterda:** loyiha papkasidagi `.env` fayliga bir qator: `TELEGRAM_BOT_TOKEN=1234567890:AA...`
* **Hugging Face'ga:** `.env` ga yozgandan keyin `.venv/bin/python scripts/hf_deploy.py --only secrets` —
  skript tokenni `.env` dan o'qib, Space'ga secret sifatida qo'yadi (ekranga chiqarmaydi).
  Yoki qo'lda: Space sahifasi → **Settings** → **Variables and secrets** → **New secret** →
  nomi `TELEGRAM_BOT_TOKEN`, qiymati — token.

Secret qo'shilgach Space o'zi qayta ishga tushadi. Tekshirish: `https://<user>-dalil.hf.space/api/health`
javobida `"telegram_auth": true`.

Token bo'lmasa ham Mini App ishlaydi — faqat foydalanuvchi qurilma ID + IP bo'yicha aniqlanadi.

## 4. Sinash

1. Telefonda botingizni oching → pastdagi **Dalil** tugmasi.
2. Birinchi ochilishda (Space uxlab qolgan bo'lsa) "Tayyorlanmoqda…" yozuvi 1–2 daqiqa turishi mumkin —
   bu normal: server indeks va modelni yuklayapti. Shu paytda yozilgan savol tayyor bo'lishi bilan yuboriladi.
3. Tekshiring: tema Telegram temasiga mos (yorug'/qorong'i), yuqori va pastki chekkalar kesilmagan,
   chatdan "orqaga" tugmasi bosh sahifaga qaytaradi, "Ulashish" → Telegram chat tanlash oynasini ochadi.
4. Kompyuterda: https://web.telegram.org da ham ochiladi (u Mini App'ni iframe ichida ko'rsatadi —
   server CSP `frame-ancestors` bunga ruxsat beradi).

## Nimalar allaqachon kodda bor

`web/src/telegram.ts`: `ready()`, `expand()`, vertikal suring bilan yopilmaslik, Telegram tema rangi
(sarlavha, fon, pastki panel), `safeAreaInset` + `contentSafeAreaInset`, `viewportStableHeight`,
"orqaga" tugmasi (`BackButton`), javob yozilayotganda yopishdan oldin so'rash (`enableClosingConfirmation`),
haptic, kalitni `CloudStorage` da saqlash, ulashish `openTelegramLink("https://t.me/share/url?...")` orqali
(Mini App yopilmaydi), tashqi havolalar `openLink` bilan tizim brauzerida.

## Muammo bo'lsa

* **Oq ekran** — Space uxlagan yoki build xato bergan: Space sahifasidagi **Logs** ni ko'ring.
* **"Bugungi bepul savollar tugadi"** — `FREE_DAILY_LIMIT` (Space → Settings → Variables).
* **Bepul tarifda Space 48 soat hech kim ochmasa uxlaydi**, keyingi ochilishda 1–2 daqiqada uyg'onadi;
  bepul limit hisoblagichi ham shunda nolga qaytadi (README, "Internetga chiqarish").
