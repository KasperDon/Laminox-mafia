# 🎮 Mafia O'yini Boshlovchi Bot

Telegram guruhlar uchun to'liq avtomatlashtirilgan Mafia o'yini boshlovchisi.

---

## 📋 Talablar

- Python 3.12+
- Telegram bot token (BotFather orqali)

---

## 🚀 Ishga tushirish (Noutbuk)

### 1. BotFather'dan token olish

1. Telegram'da [@BotFather](https://t.me/BotFather) ga o'ting
2. `/newbot` buyrug'ini yuboring
3. Bot nomini kiriting (masalan: `Mafia Game Bot`)
4. Username kiriting (masalan: `my_mafia_game_bot`)
5. Berilgan tokenni nusxalab oling

### 2. Loyihani sozlash

```bash
# Papkaga o'tish
cd mafia_bot

# Virtual muhit yaratish (tavsiya etiladi)
python -m venv venv

# Virtual muhitni yoqish (Windows)
venv\Scripts\activate

# Virtual muhitni yoqish (Linux/Mac)
source venv/bin/activate

# Kutubxonalarni o'rnatish
pip install -r requirements.txt
```

### 3. .env faylini sozlash

```bash
# .env.example ni nusxalash
copy .env.example .env     # Windows
cp .env.example .env       # Linux/Mac
```

`.env` faylini oching va tokeningizni kiriting:

```
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
```

### 4. Botni ishga tushirish

```bash
python bot.py
```

**Muhim:** Noutbukda ishlatilganda terminal ochiq turishi kerak!

---

## 🤖 Guruhga qo'shish va sozlash

### Guruhga qo'shish

1. Guruhingizni oching
2. "Add member" ni bosing
3. Botingizni qidiring va qo'shing

### Botga admin huquqi berish

1. Guruh sozlamalariga kiring
2. "Administrators" → "Add Administrator"
3. Botni toping
4. Quyidagi ruxsatlarni bering:
   - ✅ Change group info
   - ✅ Delete messages
   - ✅ Restrict members
5. "Save" ni bosing

---

## 🎮 O'yin qoidalari

### Buyruqlar

| Buyruq | Tavsif |
|--------|--------|
| `/start` | Bot haqida ma'lumot |
| `/newgame` | Yangi o'yin boshlash |
| `/startgame` | O'yinni ishga tushirish (admin) |
| `/cancelgame` | O'yinni bekor qilish (admin) |
| `/status` | Joriy o'yin holati |
| `/settings` | O'yin sozlamalari (admin) |
| `/set_day_time <s>` | Kunduz vaqtini o'rnatish |
| `/set_vote_time <s>` | Ovoz berish vaqtini o'rnatish |
| `/set_night_time <s>` | Tun vaqtini o'rnatish |

### O'yin ketma-ketligi

```
/newgame → O'yinchilar qo'shiladi → /startgame →
Rollar tasdiqlanadi → Rollar tarqatiladi →
[Kunduz muhokama → Ovoz berish → Tun → Tong] × N raund →
G'olib e'lon qilinadi
```

### Rollar va o'yinchilar soni

| O'yinchilar | Mafiya | Don | Komissar | Doktor | Manyak | Tinch |
|------------|--------|-----|---------|--------|--------|-------|
| 5–6        | 1      | —   | 1       | 1      | —      | 2–3   |
| 7–9        | 2      | —   | 1       | 1      | —      | 3–5   |
| 10–11      | 2      | 1   | 1       | 1      | —      | 5–6   |
| 12+        | 3      | 1   | 1       | 1      | 1      | 5+    |

### Rollar tavsifi

- 👤 **Tinch aholi** — Mafia kimligini topib chiqaradi
- 🔫 **Mafiya** — Tunda bir odamni o'ldiradi
- 👑 **Don** — Mafiya boshlig'i, komissarni tekshira oladi
- 🔍 **Komissar** — Tunda bir odamni tekshiradi
- 💊 **Doktor** — Tunda bir odamni davolaydi
- 🔪 **Manyak** — Yakka o'ynaydi, yolg'iz qolsa g'olib

### G'alaba shartlari

- 🏙 **Shahar** — Barcha mafiyalar chiqarilsa
- 🔫 **Mafiya** — Mafiya soni tinch aholi soniga teng yoki ko'p bo'lsa
- 🔪 **Manyak** — Yolg'iz qolsa

---

## 🌐 Railway/VPS ga ko'chirish (keyinroq)

### Railway

```bash
# Railway CLI o'rnatish
npm install -g @railway/cli

# Login
railway login

# Loyiha yaratish
railway init

# Muhit o'zgaruvchisini o'rnatish
railway variables set BOT_TOKEN=your_token_here

# Deploy
railway up
```

### VPS (Ubuntu/Debian)

```bash
# Dependencylar
sudo apt update && sudo apt install python3.12 python3.12-venv -y

# Loyihani yuklash
git clone <repo_url> mafia_bot
cd mafia_bot

# Virtual muhit
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# .env sozlash
cp .env.example .env
nano .env  # BOT_TOKEN ni kiriting

# systemd service yaratish (24/7 uchun)
sudo nano /etc/systemd/system/mafia-bot.service
```

`mafia-bot.service` fayl mazmuni:
```ini
[Unit]
Description=Mafia Telegram Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/mafia_bot
Environment=PATH=/home/ubuntu/mafia_bot/venv/bin
ExecStart=/home/ubuntu/mafia_bot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable mafia-bot
sudo systemctl start mafia-bot

# Holat tekshirish
sudo systemctl status mafia-bot

# Loglarni ko'rish
journalctl -u mafia-bot -f
```

---

## 📁 Loyiha tuzilishi

```
mafia_bot/
├── bot.py              # Asosiy kirish nuqtasi
├── config.py           # Konfiguratsiya (pydantic-settings)
├── database.py         # aiosqlite repository layer
├── keyboards.py        # InlineKeyboard qurilmalari
├── roles.py            # Rol ta'riflari va taqsimlash mantiq
├── game_engine.py      # O'yin mantiq: tun hisob, g'olib aniqlash
├── handlers/
│   ├── commands.py     # /newgame, /cancelgame va boshqalar
│   ├── callbacks.py    # Inline tugma callback'lari + o'yin bosqichlari
│   └── private_actions.py  # Tundagi shaxsiy harakat callback'lari
├── services/
│   ├── permissions.py  # Guruh mute/unmute
│   └── scheduler.py    # asyncio.Task asosidagi taymer
├── requirements.txt
├── .env.example
├── mafia.db            # SQLite (avtomatik yaratiladi)
└── mafia_bot.log       # Log fayl (avtomatik yaratiladi)
```

---

## ⚠️ Muammolar va yechimlar

**"Bot admin emas" xatosi**
→ Botga guruhda administrator huquqi bering

**O'yinchi rol olmadi**
→ O'yinchi avval botga shaxsiy xabarda `/start` bosishi kerak

**Bot to'xtab qoldi (noutbukda)**
→ Terminal ochiq turishi shart. Restart bo'lsa, faol o'yinlar avtomatik tiklanadi.

**"Telegram Bad Request" xatosi**
→ `mafia_bot.log` faylini tekshiring
