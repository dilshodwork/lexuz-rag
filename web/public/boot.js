/* Tema birinchi chizishdan oldin (oq "chaqnash" bo'lmasin). Alohida fayl: CSP inline skriptga ruxsat bermaydi. */
try {
  var t = JSON.parse(localStorage.getItem("dalil.theme") || "null");
  var tg = window.Telegram && Telegram.WebApp && Telegram.WebApp.initData ? Telegram.WebApp.colorScheme : null;
  document.documentElement.dataset.theme = t || tg || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
} catch (e) {}
