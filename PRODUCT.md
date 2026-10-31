# Product

<!-- impeccable:product-schema 1 -->

## Platform

web (mobile-first; ochiladigan joylar: Telegram Mini App ichidagi WebView va oddiy brauzer)

## Stack

delegated: FastAPI backend (lexrag paketini import qiladi) + Vite/React/TypeScript frontend, `npm run build` natijasini FastAPI o'zi statik fayl sifatida beradi. Sabab: streaming, manba paneli, tarix va filtrlar holatini React'da boshqarish oson, ishga tushirish esa bitta uvicorn buyrug'i bo'lib qoladi.

## Users

O'zbekiston qonunchiligi bo'yicha tez javob izlayotgan oddiy fuqaro yoki talaba; ko'pincha telefonda, Telegram bot ichidan ochadi. Ikkinchi auditoriya: "Sun'iy intellekt" fani ustozi, loyihani baholaydi (manbalar to'g'riligi, iqtiboslar, ishonchlilik).

## Product Purpose

Savolga lex.uz Milliy bazasidagi amaldagi qonun, kodeks va Konstitutsiya moddalariga tayangan javob berish. Har bir da'vo [n] iqtibos bilan aniq moddaga bog'lanadi va lex.uz'dagi rasmiy matnga havola beriladi. Muvaffaqiyat: foydalanuvchi javobni va uning manbasini bir qarashda tekshira oladi.

## Positioning

Umumiy chatbot emas: javob faqat bazadagi moddalardan yoziladi, mos modda topilmasa ochiq "topilmadi" deydi. Har javob yonida manba kartochkasi: hujjat, modda, bob, holat, oxirgi tahrir sanasi.

## Operating Context

- Baza: 1618 hujjat (1588 qonun, 28 kodeks, 2 Konstitutsiya), 39 961 modda bo'lagi, holat sanasi 31.10.2026.
- Qidiruv: bge-m3 + BM25 gibrid, RRF. Kirillcha savolni backend lotinga o'giradi.
- LLM: foydalanuvchining o'z kaliti ("AI ulash": Gemini, OpenAI yoki Claude, kalit faqat qurilmada) yoki server kaliti bilan kuniga bir necha bepul savol (standart gemini-3.1-flash-lite, zaxira modellar bilan).
- Standart filtr: faqat amaldagi hujjatlar, o'zgartirish kirituvchi qonunlarsiz.

## Capabilities and Constraints

- Interfeys tili: o'zbek lotin (ʻ va ʼ belgilari to'g'ri).
- Telegram Mini App: safe-area, Telegram tema ranglari, viewport balandligi hisobga olinadi.
- Keyingi bosqichlar (arxitekturada joy qoldiriladi): baholash to'plami (recall@5), reranker, internetga chiqarish.
- Hech qachon commit qilinmaydi: data/, .env.

## Brand Commitments

- Nom tanlanmagan (variantlar taklif qilinadi). Nomda "lex.uz" bo'lmaydi.
- Davlat gerbi va rasmiy belgilar ishlatilmaydi; rasmiy sayt deb adashtirmaslik kerak.
- Vizual yo'nalish foydalanuvchi tomonidan belgilangan: Dribbble "AI chat UI Mobile" (Narima Digital) uslubi: yumshoq pastel fon, oq havodor kartochkalar, markazda salomlashish va savol, pastda pill input va yumaloq "orb" tugma.
- Foydalanuvchi generik "AI shablon"ni yoqtirmaydi; bitta aksent rang, yaxshi tipografiya.

## Evidence on Hand

- Real manbalar: `python -m lexrag search` natijalari (design/data/sample_sources.json).
- Statistika: report.md.
- LLM javobi hali haqiqiy kalit bilan sinalmagan; maketdagi javob matni manbalar asosida qo'lda yozilgan va shunday belgilanadi.

## Product Principles

1. Manba javobdan muhimroq: har da'vo tekshiriladigan moddaga bog'lanadi.
2. Bilmasa, "topilmadi" deydi; taxmin qilmaydi.
3. Telefonda bir qo'l bilan ishlatiladi.
4. Rasmiy davlat sayti emas, rasmiy matnga yo'l ko'rsatuvchi.

## Accessibility & Inclusion

Kontrast WCAG AA, 44px teginish nishonlari, kirillcha kiritish qo'llab-quvvatlanadi, prefers-reduced-motion hurmat qilinadi.
