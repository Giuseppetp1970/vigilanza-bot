# 🚨 Vigilanza Bot — Guida Deploy su Railway

Bot Telegram per check-in turni notturni. Gira 24/7 su server gratuito.

---

## 📁 File inclusi

| File | Descrizione |
|------|-------------|
| `bot.py` | Il bot (tutto qui) |
| `requirements.txt` | Dipendenze Python |
| `railway.toml` | Configurazione Railway |

---

## 🚀 Deploy su Railway (gratis, 5 minuti)

### 1. Crea account Railway
Vai su [railway.app](https://railway.app) → Sign up with GitHub

### 2. Carica i file su GitHub
1. Vai su [github.com](https://github.com) → New repository → nome: `vigilanza-bot`
2. Carica i 3 file: `bot.py`, `requirements.txt`, `railway.toml`

### 3. Crea progetto su Railway
1. Railway dashboard → **New Project** → **Deploy from GitHub repo**
2. Seleziona `vigilanza-bot`
3. Railway lo rileva e avvia il build automaticamente

### 4. Aggiungi le variabili d'ambiente
In Railway → il tuo progetto → **Variables** → aggiungi:

| Variabile | Valore | Obbligatorio |
|-----------|--------|-------------|
| `BOT_TOKEN` | Token di @BotFather | ✅ |
| `COORD_ID` | Il tuo Chat ID (da @userinfobot) | ✅ |
| `INTERVAL` | Minuti tra ping (default: 15) | ⬜ |
| `THRESHOLD` | Minuti soglia ritardo (default: 5) | ⬜ |
| `PING_MSG` | Messaggio personalizzato | ⬜ |

### 5. Deploy!
Dopo aver aggiunto le variabili → **Redeploy** → il bot è online 🎉

---

## 📱 Comandi Telegram (solo per te, coordinatore)

| Comando | Funzione |
|---------|----------|
| `/volontari` | Mostra rubrica con bottoni per attivare/disattivare |
| `/avvia` | Avvia sessione notturna |
| `/ferma` | Ferma sessione |
| `/stato` | Stato attuale (ping, conferme, ritardi) |
| `/ping` | Invia ping immediato |
| `/attiva Mario` | Attiva Mario per la sessione |
| `/escludi Mario` | Escludi Mario dalla sessione |

---

## 🔄 Flusso ogni notte

1. I volontari di turno cercano `@nometuobot` → `/start` → si registrano
2. Tu scrivi `/volontari` → spunti chi è in turno → `/avvia`
3. Il bot invia ping ogni 15 minuti automaticamente
4. I volontari rispondono **ok** → tu ricevi notifica Telegram con tempo di risposta
5. Mancata risposta entro soglia → alert Telegram a te
6. Fine turno → `/ferma`

---

## ℹ️ Note

- **Railway free tier**: 500 ore/mese gratis (bastano per ~20 giorni continui)
- **Alternativa gratuita illimitata**: usa [Render.com](https://render.com) con un `Procfile` contenente `web: python bot.py`
- I dati dei volontari vengono salvati in `data.json` — persistono tra i riavvii
- Se il bot si riavvia durante una sessione attiva, la ripristina automaticamente e avvisa il coordinatore
