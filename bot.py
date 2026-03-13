"""
Vigilanza Bot — Sistema Check-in Turni Notturni
Gira 24/7 su Railway/Render, zero browser necessario.
"""

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ── LOGGING ────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# ── CONFIG DA ENVIRONMENT ──────────────────────────────────────────────────
BOT_TOKEN   = os.environ["BOT_TOKEN"]          # token del bot
COORD_ID    = int(os.environ["COORD_ID"])       # tuo chat id
INTERVAL    = int(os.environ.get("INTERVAL", "15"))    # minuti tra ping
THRESHOLD   = int(os.environ.get("THRESHOLD", "5"))    # minuti soglia ritardo
PING_MSG    = os.environ.get(
    "PING_MSG",
    "🔔 CHECK-IN — Rispondi OK per confermare la tua presenza. [{time}]"
)

# ── PERSISTENZA ────────────────────────────────────────────────────────────
DATA_FILE = Path("data.json")

def load_data():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text())
        except Exception:
            pass
    return {"volunteers": {}, "session": None}

def save_data(data):
    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

data = load_data()
# volunteers: {chat_id_str: {"name": str, "tg_name": str, "active": bool}}
# session: None oppure {"started": iso, "ping_count": int, "last_ping": iso,
#                       "pending": {chat_id: sent_ts}, "stats": {ok, late}}

# ── HELPERS ────────────────────────────────────────────────────────────────
def is_coord(update: Update) -> bool:
    return update.effective_user.id == COORD_ID

def session_active() -> bool:
    return data.get("session") is not None

def now_str() -> str:
    return datetime.now().strftime("%H:%M")

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def fmt_volunteers() -> str:
    vols = data["volunteers"]
    if not vols:
        return "Nessun volontario registrato."
    lines = []
    for cid, v in vols.items():
        stato = "✅ attivo" if v.get("active") else "⏸ escluso"
        lines.append(f"• {v['name']} (@{v.get('tg_user','?')}) — {stato}")
    return "\n".join(lines)

# ── COMANDI COORDINATORE ───────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    tg_name = update.effective_user.first_name
    tg_user = update.effective_user.username or tg_name

    if update.effective_user.id == COORD_ID:
        await update.message.reply_text(
            "👋 Ciao coordinatore!\n\n"
            "Comandi disponibili:\n"
            "/avvia — avvia sessione notturna\n"
            "/ferma — ferma sessione\n"
            "/volontari — lista volontari registrati\n"
            "/attiva [nome] — attiva volontario per stasera\n"
            "/escludi [nome] — escludi volontario da stasera\n"
            "/ping — invia ping immediato\n"
            "/stato — stato sessione corrente\n\n"
            f"Intervallo ping: ogni {INTERVAL} min\n"
            f"Soglia ritardo: {THRESHOLD} min"
        )
        return

    # Registrazione volontario
    if uid not in data["volunteers"]:
        data["volunteers"][uid] = {
            "name": tg_name,
            "tg_name": tg_name,
            "tg_user": tg_user,
            "active": True
        }
        save_data(data)
        log.info(f"Nuovo volontario registrato: {tg_name} ({uid})")
        await update.message.reply_text(
            f"✅ Registrato con successo, {tg_name}!\n"
            "Il coordinatore ti aggiungerà alle sessioni di turno.\n\n"
            "Quando sei di turno riceverai un messaggio ogni "
            f"{INTERVAL} minuti — rispondi semplicemente OK."
        )
        # Notifica coordinatore
        await ctx.bot.send_message(
            COORD_ID,
            f"📥 Nuovo volontario registrato:\n"
            f"👤 {tg_name} (@{tg_user})\n"
            f"ID: {uid}\n\n"
            f"Usa /volontari per vedere la lista completa."
        )
    else:
        # Aggiorna nome se cambiato
        data["volunteers"][uid]["tg_name"] = tg_name
        data["volunteers"][uid]["tg_user"] = tg_user
        save_data(data)
        await update.message.reply_text(
            f"👋 Ciao {tg_name}, sei già registrato!\n"
            "Aspetta il check-in quando sei di turno."
        )


async def cmd_avvia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_coord(update):
        return
    if session_active():
        await update.message.reply_text("⚠️ Sessione già attiva! Usa /ferma prima.")
        return

    attivi = {cid: v for cid, v in data["volunteers"].items() if v.get("active")}
    if len(attivi) < 2:
        await update.message.reply_text(
            "⚠️ Servono almeno 2 volontari attivi.\n"
            f"Attivi ora: {len(attivi)}\n\n"
            "Usa /attiva [nome] per attivare i volontari di stasera,\n"
            "oppure chiedili di scrivere al bot per registrarsi."
        )
        return

    data["session"] = {
        "started": now_iso(),
        "ping_count": 0,
        "last_ping": None,
        "pending": {},
        "stats": {"ok": 0, "late": 0}
    }
    save_data(data)

    nomi = ", ".join(v["name"] for v in attivi.values())
    await update.message.reply_text(
        f"▶️ Sessione avviata!\n\n"
        f"👥 Volontari attivi: {nomi}\n"
        f"⏱ Ping ogni {INTERVAL} minuti\n"
        f"⚠️ Alert dopo {THRESHOLD} minuti senza risposta\n\n"
        "Invio primo ping tra pochi secondi…"
    )

    # Schedula il primo ping subito (5 secondi) e poi ogni INTERVAL minuti
    ctx.job_queue.run_once(job_ping, when=5, name="first_ping")
    ctx.job_queue.run_repeating(
        job_ping,
        interval=INTERVAL * 60,
        first=INTERVAL * 60,
        name="ping_loop"
    )

    log.info(f"Sessione avviata con {len(attivi)} volontari")


async def cmd_ferma(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_coord(update):
        return
    if not session_active():
        await update.message.reply_text("Nessuna sessione attiva.")
        return

    s = data["session"]
    data["session"] = None
    save_data(data)

    # Cancella job schedulati
    for job in ctx.job_queue.get_jobs_by_name("ping_loop"):
        job.schedule_removal()
    for job in ctx.job_queue.get_jobs_by_name("first_ping"):
        job.schedule_removal()
    for job in ctx.job_queue.get_jobs_by_name("threshold_check"):
        job.schedule_removal()

    await update.message.reply_text(
        f"⏹ Sessione terminata.\n\n"
        f"📊 Riepilogo:\n"
        f"• Ping inviati: {s['ping_count']}\n"
        f"• Conferme ricevute: {s['stats']['ok']}\n"
        f"• Ritardi: {s['stats']['late']}"
    )
    log.info("Sessione terminata")


async def cmd_volontari(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_coord(update):
        return
    vols = data["volunteers"]
    if not vols:
        await update.message.reply_text(
            "Nessun volontario registrato.\n"
            f"Devono cercare @{(await ctx.bot.get_me()).username} e premere Start."
        )
        return

    # Mostra bottoni inline per attivare/disattivare
    keyboard = []
    for cid, v in vols.items():
        stato = "✅" if v.get("active") else "⏸"
        keyboard.append([
            InlineKeyboardButton(
                f"{stato} {v['name']}",
                callback_data=f"toggle_{cid}"
            )
        ])
    keyboard.append([InlineKeyboardButton("✔ Conferma lista", callback_data="conferma")])

    await update.message.reply_text(
        "👥 Volontari registrati\nPremi per attivare/disattivare dalla sessione:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cmd_stato(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_coord(update):
        return
    if not session_active():
        await update.message.reply_text("Nessuna sessione attiva.")
        return
    s = data["session"]
    attivi = {cid: v for cid, v in data["volunteers"].items() if v.get("active")}
    pending = s.get("pending", {})
    pending_nomi = [data["volunteers"][cid]["name"] for cid in pending if cid in data["volunteers"]]
    await update.message.reply_text(
        f"📡 Sessione attiva\n\n"
        f"🕐 Avviata: {s['started'][:16].replace('T',' ')}\n"
        f"📤 Ping inviati: {s['ping_count']}\n"
        f"✅ Conferme: {s['stats']['ok']}\n"
        f"🔴 Ritardi: {s['stats']['late']}\n"
        f"👥 Volontari attivi: {len(attivi)}\n"
        + (f"⏳ In attesa di: {', '.join(pending_nomi)}" if pending_nomi else "✅ Tutti hanno risposto")
    )


async def cmd_ping_immediato(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_coord(update):
        return
    if not session_active():
        await update.message.reply_text("Nessuna sessione attiva. Usa /avvia prima.")
        return
    await update.message.reply_text("📤 Invio ping immediato…")
    await do_ping(ctx)


async def cmd_attiva(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_coord(update):
        return
    args = ctx.args
    if not args:
        await update.message.reply_text("Uso: /attiva [nome]\nEs: /attiva Mario")
        return
    nome = " ".join(args).lower()
    trovato = False
    for cid, v in data["volunteers"].items():
        if nome in v["name"].lower():
            v["active"] = True
            trovato = True
            await update.message.reply_text(f"✅ {v['name']} attivato per la sessione.")
    if not trovato:
        await update.message.reply_text(f"Nessun volontario trovato con nome '{nome}'.")
    save_data(data)


async def cmd_escludi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_coord(update):
        return
    args = ctx.args
    if not args:
        await update.message.reply_text("Uso: /escludi [nome]\nEs: /escludi Mario")
        return
    nome = " ".join(args).lower()
    trovato = False
    for cid, v in data["volunteers"].items():
        if nome in v["name"].lower():
            v["active"] = False
            trovato = True
            await update.message.reply_text(f"⏸ {v['name']} escluso dalla sessione.")
    if not trovato:
        await update.message.reply_text(f"Nessun volontario trovato con nome '{nome}'.")
    save_data(data)


# ── CALLBACK BOTTONI INLINE ────────────────────────────────────────────────

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "conferma":
        attivi = [v["name"] for v in data["volunteers"].values() if v.get("active")]
        esclusi = [v["name"] for v in data["volunteers"].values() if not v.get("active")]
        txt = "✅ Lista confermata!\n\n"
        if attivi:
            txt += f"Attivi stasera: {', '.join(attivi)}\n"
        if esclusi:
            txt += f"Esclusi: {', '.join(esclusi)}"
        await query.edit_message_text(txt)
        return

    if query.data.startswith("toggle_"):
        cid = query.data[7:]
        if cid in data["volunteers"]:
            v = data["volunteers"][cid]
            v["active"] = not v.get("active", True)
            save_data(data)

        # Ricostruisci tastiera aggiornata
        keyboard = []
        for cid2, v2 in data["volunteers"].items():
            stato = "✅" if v2.get("active") else "⏸"
            keyboard.append([InlineKeyboardButton(
                f"{stato} {v2['name']}",
                callback_data=f"toggle_{cid2}"
            )])
        keyboard.append([InlineKeyboardButton("✔ Conferma lista", callback_data="conferma")])
        await query.edit_message_reply_markup(InlineKeyboardMarkup(keyboard))


# ── RISPOSTA OK DAI VOLONTARI ──────────────────────────────────────────────

async def msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    text = (update.message.text or "").strip().lower()

    # Ignora messaggi del coordinatore
    if update.effective_user.id == COORD_ID:
        return

    # Controlla se è una risposta OK durante sessione attiva
    ok_words = {"ok", "okay", "sì", "si", "✅", "👍", "ok!", "OK", "Ok"}
    if text in ok_words and session_active():
        s = data["session"]
        if uid in s.get("pending", {}):
            sent_ts_str = s["pending"].pop(uid)
            sent_ts = datetime.fromisoformat(sent_ts_str)
            now = datetime.now(timezone.utc)
            diff = now - sent_ts
            diff_sec = int(diff.total_seconds())
            diff_min = diff_sec // 60
            diff_s   = diff_sec % 60

            s["stats"]["ok"] += 1
            save_data(data)

            label = f"{diff_min}m {diff_s}s" if diff_min > 0 else f"{diff_s}s"
            nome = data["volunteers"].get(uid, {}).get("name", "Sconosciuto")
            ts   = datetime.now().strftime("%H:%M")

            # Conferma al volontario
            await update.message.reply_text(f"✅ Check-in registrato! ({label})")

            # Notifica coordinatore
            await ctx.bot.send_message(
                COORD_ID,
                f"✅ CHECK-IN OK\n"
                f"👤 {nome} ha confermato alle {ts}\n"
                f"⏱ Risposta in {label}"
            )
            log.info(f"{nome} confermato in {label}")

        else:
            await update.message.reply_text("👍 Ricevuto! Nessun check-in pendente al momento.")

    elif uid not in data["volunteers"]:
        # Non registrato → invita a fare /start
        await update.message.reply_text(
            "Ciao! Per registrarti come volontario scrivi /start"
        )


# ── JOB: PING PERIODICO ────────────────────────────────────────────────────

async def job_ping(ctx: ContextTypes.DEFAULT_TYPE):
    await do_ping(ctx)

async def do_ping(ctx: ContextTypes.DEFAULT_TYPE):
    if not session_active():
        return

    s = data["session"]
    attivi = {cid: v for cid, v in data["volunteers"].items() if v.get("active")}
    if not attivi:
        return

    s["ping_count"] += 1
    ts = now_str()
    sent_iso = now_iso()
    msg = PING_MSG.replace("{time}", ts)

    # Cancella eventuali check threshold precedenti
    for job in ctx.job_queue.get_jobs_by_name("threshold_check"):
        job.schedule_removal()

    # Segna tutti come pending
    s["pending"] = {cid: sent_iso for cid in attivi}
    s["last_ping"] = sent_iso
    save_data(data)

    # Invia messaggio a ogni volontario
    failed = []
    for cid, v in attivi.items():
        try:
            await ctx.bot.send_message(int(cid), msg)
        except Exception as e:
            log.warning(f"Errore invio a {v['name']}: {e}")
            failed.append(v["name"])

    log.info(f"Ping #{s['ping_count']} inviato a {len(attivi)} volontari ({ts})")

    # Schedula controllo soglia
    ctx.job_queue.run_once(
        job_threshold_check,
        when=THRESHOLD * 60,
        name="threshold_check"
    )


async def job_threshold_check(ctx: ContextTypes.DEFAULT_TYPE):
    """Controlla chi non ha risposto entro la soglia."""
    if not session_active():
        return
    s = data["session"]
    pending = s.get("pending", {})
    if not pending:
        return

    ritardatari = []
    for cid in list(pending.keys()):
        v = data["volunteers"].get(cid)
        if v:
            ritardatari.append(v["name"])
            s["stats"]["late"] += 1

    if ritardatari:
        save_data(data)
        nomi = ", ".join(ritardatari)
        ts = (s.get("last_ping") or "")[:16].replace("T", " ")
        await ctx.bot.send_message(
            COORD_ID,
            f"⚠️ ALERT VIGILANZA\n\n"
            f"🔴 Non hanno risposto entro {THRESHOLD} minuti:\n"
            f"👤 {nomi}\n\n"
            f"Ping inviato alle: {now_str()}"
        )
        log.warning(f"Ritardatari: {nomi}")


# ── RIPRISTINO SESSIONE AL RIAVVIO ─────────────────────────────────────────

async def post_init(app: Application):
    """Viene chiamato all'avvio — ripristina la sessione se era attiva."""
    if session_active():
        log.info("Sessione attiva trovata — ripristino job scheduler")
        app.job_queue.run_repeating(
            job_ping,
            interval=INTERVAL * 60,
            first=30,  # primo ping dopo 30 secondi dal riavvio
            name="ping_loop"
        )
        try:
            await app.bot.send_message(
                COORD_ID,
                f"🔄 Bot riavviato — sessione ripristinata.\n"
                f"Prossimo ping tra circa {INTERVAL} minuti."
            )
        except Exception:
            pass


# ── MAIN ──────────────────────────────────────────────────────────────────

def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Handlers
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("avvia",     cmd_avvia))
    app.add_handler(CommandHandler("ferma",     cmd_ferma))
    app.add_handler(CommandHandler("volontari", cmd_volontari))
    app.add_handler(CommandHandler("stato",     cmd_stato))
    app.add_handler(CommandHandler("ping",      cmd_ping_immediato))
    app.add_handler(CommandHandler("attiva",    cmd_attiva))
    app.add_handler(CommandHandler("escludi",   cmd_escludi))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))

    log.info("Bot avviato ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
