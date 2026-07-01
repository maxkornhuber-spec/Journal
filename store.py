"""
store.py — Datenschicht: spricht mit Supabase (Datenbank + Bilderspeicher).

Die App spricht NUR mit dieser Datei. Wer das Backend wechseln will,
ändert nur hier etwas — der Rest der App bleibt unberührt.

Zugriff erfolgt server-seitig mit dem Service-Key (liegt sicher in den
Streamlit-Secrets, niemals im Browser).
"""
import os
import time

import streamlit as st
from supabase import create_client

BUCKET = "screenshots"

DEFAULT_SETUPS = ["Breakout", "Pullback", "Reversal", "Trend-Following",
                  "Range", "Scalp", "News", "Sonstiges"]
DEFAULT_MISTAKES = ["FOMO", "Revenge-Trade", "Kein Plan", "Stop verschoben",
                    "Zu frueh raus", "Zu spaet raus", "Position zu gross",
                    "Plan nicht eingehalten", "Uebertrading"]
DEFAULT_RULES = ["Auf Bestaetigung gewartet", "Stop vor Einstieg gesetzt",
                 "Risiko <= 1%", "Stop nicht verschoben", "Im Plan geblieben"]
EMOTIONS = ["Ruhig", "Gierig", "Aengstlich", "Frustriert", "Selbstsicher", "Ungeduldig"]


def _secret(name):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


@st.cache_resource
def client():
    url = _secret("SUPABASE_URL")
    key = _secret("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("Supabase-Zugang fehlt: SUPABASE_URL / SUPABASE_SERVICE_KEY in den Secrets setzen.")
    return create_client(url, key)


# --- Konten --------------------------------------------------------------
def list_accounts():
    return client().table("accounts").select("*").order("id").execute().data or []


def add_account(name, currency="EUR", start_balance=0):
    client().table("accounts").insert({
        "name": name.strip(),
        "currency": (currency or "EUR").strip(),
        "start_balance": start_balance or 0,
    }).execute()


def update_account(account_id, data: dict):
    client().table("accounts").update(data).eq("id", account_id).execute()


def delete_account(account_id):
    client().table("accounts").delete().eq("id", account_id).execute()


# --- Trades --------------------------------------------------------------
def list_trades(account_id):
    return (client().table("trades").select("*")
            .eq("account_id", account_id).order("id", desc=True).execute().data or [])


def get_trade(trade_id):
    r = client().table("trades").select("*").eq("id", trade_id).limit(1).execute()
    return (r.data or [None])[0]


def add_trade(data: dict):
    clean = {k: v for k, v in data.items() if v is not None}
    r = client().table("trades").insert(clean).execute()
    return r.data[0]["id"] if r.data else None


def update_trade(trade_id, data: dict):
    client().table("trades").update(data).eq("id", trade_id).execute()


def delete_trade(trade_id):
    client().table("trades").delete().eq("id", trade_id).execute()


# --- Eigene Listen -------------------------------------------------------
def get_list(name):
    r = client().table("app_lists").select("items").eq("name", name).limit(1).execute()
    return r.data[0]["items"] if r.data else None


def set_list(name, items):
    client().table("app_lists").upsert({"name": name, "items": items}).execute()


def add_to_list(name, item):
    item = (item or "").strip()
    if not item:
        return
    items = get_list(name) or []
    if item not in items:
        items.append(item)
        set_list(name, items)


def remove_from_list(name, item):
    items = get_list(name) or []
    if item in items:
        items.remove(item)
        set_list(name, items)


def seed_defaults():
    if get_list("setups") is None:
        set_list("setups", DEFAULT_SETUPS)
    if get_list("mistakes") is None:
        set_list("mistakes", DEFAULT_MISTAKES)
    if get_list("rules") is None:
        set_list("rules", DEFAULT_RULES)
    if not list_accounts():
        add_account("Hauptkonto", "EUR")


# --- Coach-Profil --------------------------------------------------------
def get_coach_profile():
    r = client().table("coach_profile").select("content").eq("id", 1).limit(1).execute()
    return r.data[0]["content"] if r.data else ""


def set_coach_profile(text):
    client().table("coach_profile").upsert({"id": 1, "content": text}).execute()


# --- Bilder (Storage) ----------------------------------------------------
def upload_image(data: bytes, filename: str) -> str:
    path = f"{int(time.time()*1000)}_{filename}"
    client().storage.from_(BUCKET).upload(
        path, data, {"content-type": "image/png", "upsert": "true"}
    )
    return path


def image_url(path: str, expires: int = 3600):
    if not path:
        return None
    try:
        res = client().storage.from_(BUCKET).create_signed_url(path, expires)
        return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
    except Exception:
        return None
