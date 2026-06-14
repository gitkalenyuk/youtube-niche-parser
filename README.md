<p align="center">
  <img src="banner.png" alt="YouTube Niche Parser Pro V3" width="100%">
</p>

<h1 align="center">YouTube Niche Parser Pro V3</h1>

<p align="center">
  Парсер ніш YouTube <b>без API</b>. Вставив запити — отримав дашборд:<br>
  перегляди · підписники · тривалість · графіки · 💎 самородки.
</p>

---

## 📥 Завантажити

| Система | Файл | Що робити |
|---|---|---|
| 🪟 **Windows** | **[⬇️ Завантажити .zip](../../releases/latest/download/YouTube-Niche-Parser-Windows.zip)** | Розпакуй → `START.bat`. Python усередині. |
| 🍎 **Mac (готове)** | **[⬇️ Завантажити .dmg](../../releases/latest/download/YouTube-Niche-Parser.dmg)** | Відкрий → перетягни в Applications. Universal. |
| 🍎 **Mac (вихідники)** | **[⬇️ Завантажити .zip](../../releases/latest/download/YouTube-Niche-Parser-Mac.zip)** | `START.command` (треба Python) або `build_mac.sh`. |

📖 Інструкція — всередині кожного архіву (файл **«ЯК ЗАПУСТИТИ.txt»**).

> **Mac, перший запуск:** правий клік на проzі → «Відкрити» → «Відкрити» (бо непідписаний — це нормально).

---

## ✨ Можливості

- 🎯 Фільтри ніші: макс. підписників, мін. переглядів, тип / тривалість / дата / характеристики
- 💎 **V/S** (перегляди ÷ підписники) — одразу видно самородки (малі канали з вірусними відео)
- 📊 Дашборд з графіками наживо + 📜 живий лог пошуку
- 🎨 4 теми оформлення · ⚡ багатопоточний пошук · 💾 експорт CSV / TXT

<p align="center"><img src="dashboard.png" alt="Дашборд" width="85%"></p>

## 🔒 Як працює

НЕ використовує твій акаунт і НЕ лізе в браузер. Робить **анонімні** запити до YouTube
(як відвідувач в інкогніто) — без логіну, без кукі. Браузер потрібен лише щоб намалювати вікно.

## 🛠 Збірка macOS .dmg

Автоматична через **GitHub Actions** ([`.github/workflows/build-mac.yml`](.github/workflows/build-mac.yml)):
PyInstaller пакує застосунок + universal2 Python у `.app`, `hdiutil` робить `.dmg`, він публікується в Releases.
Перезібрати: вкладка **Actions → Build macOS .dmg → Run workflow**.
