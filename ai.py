"""
ai.py — Anthropic-Anbindung: Screenshots auslesen (Forex-fähig),
Urteil pro Trade, KI-Review, "Frag dein Journal", Coach-Profil.

Hinweis: Claude verarbeitet kein Audio. Sprachnotizen entstehen über die
Diktierfunktion von Mac/Chrome direkt im Textfeld; hier kommt nur Text an.
"""
import base64
import json
import os

import streamlit as st

MODEL = "claude-sonnet-4-6"          # guenstiger: "claude-haiku-4-5"


def _secret(name):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


def _client():
    key = _secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("Kein ANTHROPIC_API_KEY in den Secrets gefunden.")
    from anthropic import Anthropic
    return Anthropic(api_key=key)


def _text(msg):
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def _json(text):
    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(t)


def _media_type(filename):
    f = (filename or "").lower()
    if f.endswith(".png"):
        return "image/png"
    if f.endswith(".webp"):
        return "image/webp"
    if f.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


# --- 1) Screenshot auslesen (Forex / CFD / Aktien / Krypto) --------------
EXTRACT_PROMPT = """Du bekommst den Screenshot eines Trades — Forex/CFD (z.B. EURUSD, GBPJPY, XAUUSD),
Aktie, Index oder Krypto, aus einer Broker-/Order-Ansicht oder einem TradingView-Chart.

Lies die Handelsdaten aus und antworte AUSSCHLIESSLICH mit einem JSON-Objekt
(ohne Markdown, ohne Erklaerung):
{
  "symbol": "z.B. EURUSD / GBPJPY / XAUUSD / AAPL / BTCUSD",
  "direction": "Long oder Short",
  "entry_price": Zahl (alle Nachkommastellen genau, z.B. 1.08423),
  "exit_price": Zahl,
  "stop_price": Zahl,
  "quantity": Zahl (Lot-Groesse bei Forex, sonst Stueck/Kontrakte),
  "pnl": Zahl (Gewinn positiv, Verlust negativ, in Kontowaehrung),
  "notes": "kurze Beobachtung, falls erkennbar"
}
Wichtig fuer Forex: Achte auf 4-5 Nachkommastellen; bei JPY-Paaren 2-3.
Rate nicht — wenn ein Wert nicht klar im Bild steht, setze ihn auf null."""


def extract_trade_from_image(image_bytes: bytes, filename: str) -> dict:
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    msg = _client().messages.create(
        model=MODEL, max_tokens=1024,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
             "media_type": _media_type(filename), "data": b64}},
            {"type": "text", "text": EXTRACT_PROMPT},
        ]}],
    )
    data = _json(_text(msg))
    allowed = {"symbol", "direction", "entry_price", "exit_price",
               "stop_price", "quantity", "pnl", "notes"}
    return {k: v for k, v in data.items() if k in allowed}


# --- 2) Urteil pro Trade (Setup / Ausfuehrung / Psyche) ------------------
SCORE_SYSTEM = """Du bist ein ehrlicher, konstruktiver Trading-Coach. Bewerte NUR Prozess,
Ausfuehrung und Psychologie des Traders — keine Anlageberatung, keine Marktprognose."""

SCORE_PROMPT = """Hier ein einzelner Trade (inkl. der eigenen Reflexion des Traders):

{trade}

Antworte AUSSCHLIESSLICH mit JSON:
{{
  "setup": 1-10,
  "execution": 1-10,
  "psych": 1-10,
  "weakness": "die EINE konkreteste Schwaeche in einem kurzen Satz",
  "tip": "EIN konkreter Tipp fuer naechstes Mal, ein Satz"
}}"""


def score_trade(trade: dict) -> dict:
    msg = _client().messages.create(
        model=MODEL, max_tokens=400, system=SCORE_SYSTEM,
        messages=[{"role": "user", "content": SCORE_PROMPT.format(trade=_fmt_trade(trade))}],
    )
    d = _json(_text(msg))
    return {
        "ai_setup": int(d.get("setup")) if d.get("setup") is not None else None,
        "ai_exec": int(d.get("execution")) if d.get("execution") is not None else None,
        "ai_psych": int(d.get("psych")) if d.get("psych") is not None else None,
        "ai_weakness": d.get("weakness"),
        "ai_tip": d.get("tip"),
    }


# --- 3) Review ueber einen Zeitraum --------------------------------------
REVIEW_SYSTEM = SCORE_SYSTEM
REVIEW_PROMPT = """Hier meine letzten Trades:

{trades}

Gib eine kompakte Auswertung mit genau diesen Abschnitten:
1. Gesamteinschaetzung (2-3 Saetze)
2. Bestes & schwaechstes Setup (mit Zahlen)
3. Wiederkehrende Fehler/Muster, die mich Geld kosten
4. Auffaelliges bei Wochentag/Emotion, falls erkennbar
5. Drei konkrete Dinge fuer naechste Woche
6. Drei kurze Reflexionsfragen
Halte dich an die Daten."""


def review(trades: list) -> str:
    msg = _client().messages.create(
        model=MODEL, max_tokens=1500, system=REVIEW_SYSTEM,
        messages=[{"role": "user", "content": REVIEW_PROMPT.format(trades=_fmt_trades(trades))}],
    )
    return _text(msg)


# --- 4) Frag dein Journal ------------------------------------------------
def ask_journal(question: str, trades: list) -> str:
    msg = _client().messages.create(
        model=MODEL, max_tokens=900, system=REVIEW_SYSTEM,
        messages=[{"role": "user", "content":
                   f"Meine Trades:\n\n{_fmt_trades(trades)}\n\nFrage: {question}\n\n"
                   "Antworte konkret auf Basis der Daten. Wenn die Daten nicht reichen, sag das."}],
    )
    return _text(msg)


# --- 5) Coach-Profil aktualisieren ---------------------------------------
def refine_coach_profile(old_profile: str, trades: list) -> str:
    msg = _client().messages.create(
        model=MODEL, max_tokens=600, system=REVIEW_SYSTEM,
        messages=[{"role": "user", "content":
                   f"Bisheriges Coach-Profil des Traders:\n{old_profile or '(noch leer)'}\n\n"
                   f"Neue Trades:\n{_fmt_trades(trades)}\n\n"
                   "Aktualisiere das Profil knapp: wiederkehrende Staerken, wiederkehrende "
                   "Schwaechen, ein Fokus. Max 6 Zeilen, Stichpunkte."}],
    )
    return _text(msg)


# --- Hilfsformatierung ---------------------------------------------------
def _fmt_trade(t: dict) -> str:
    keys = ["symbol", "direction", "setup", "entry_price", "exit_price", "stop_price",
            "pnl", "pnl_r", "emotion", "rating", "rules_followed", "mistakes",
            "reason_entry", "reason_exit", "management", "notes"]
    return "\n".join(f"{k}: {t.get(k)}" for k in keys if t.get(k) not in (None, "", []))


def _fmt_trades(trades: list) -> str:
    out = []
    for t in trades:
        date = (t.get("closed_at") or "")[:10]
        out.append(
            f"- {date} {t.get('symbol')} {t.get('direction')} | Setup {t.get('setup')} | "
            f"P/L {t.get('pnl')} ({t.get('pnl_r')}R) | Emotion {t.get('emotion')} | "
            f"Fehler {t.get('mistakes')} | warum rein: {t.get('reason_entry')} | "
            f"warum raus: {t.get('reason_exit')}"
        )
    return "\n".join(out)
