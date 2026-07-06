"""
app.py — Trading-Journal (online, nur fuer dich, ein Passwort).
Lokal testen:  streamlit run app.py   (mit .streamlit/secrets.toml)
"""
from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st

import store
import ai
import mt5_import

st.set_page_config(page_title="Trading Journal", page_icon="📈", layout="wide")

st.markdown("""<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
  html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] { font-family:'Inter', sans-serif; }
  /* Material-Symbole (z.B. Seitenleisten-Pfeil) NICHT mit Inter ueberschreiben */
  [data-testid="stIconMaterial"], .material-icons, .material-symbols-rounded, .material-symbols-outlined,
  span[class*="material-symbols"] { font-family:'Material Symbols Rounded','Material Symbols Outlined','Material Icons' !important; }

  /* Streamlit-Chrome ausblenden -> wirkt wie echte App */
  #MainMenu, header[data-testid="stHeader"], footer, [data-testid="stDecoration"] { display:none !important; }

  .block-container{padding-top:1.6rem;padding-bottom:3rem;max-width:1180px}
  h1{font-size:1.9rem;font-weight:800;letter-spacing:-.03em;margin-bottom:.2rem}
  h2,h3{font-weight:700;letter-spacing:-.02em}
  .stApp{background:#0E1620}
  hr{margin:1.1rem 0;border-color:#1D2733}

  /* Seitenleiste */
  section[data-testid="stSidebar"]{background:#0C131C;border-right:1px solid #1D2733}
  section[data-testid="stSidebar"] div[role="radiogroup"]{gap:4px;margin-top:.3rem}
  section[data-testid="stSidebar"] div[role="radiogroup"] > label{
    display:flex;align-items:center;width:100%;padding:9px 12px;border-radius:10px;
    color:#AEB9C4;font-weight:600;font-size:.95rem;transition:all .12s ease;cursor:pointer}
  section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover{background:#141E29;color:#E7ECF1}
  section[data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child{display:none}
  section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked){
    background:linear-gradient(90deg, rgba(231,174,92,.18), rgba(231,174,92,.03));
    color:#E7AE5C;box-shadow:inset 2px 0 0 #E7AE5C}

  /* Kennzahl-Karten */
  .kpi{background:linear-gradient(180deg,#18222E,#141C27);border:1px solid #253140;
       border-radius:16px;padding:16px 18px;min-height:96px}
  .kpi-l{color:#8494A2;font-size:.72rem;font-weight:700;text-transform:uppercase;
         letter-spacing:.06em;margin-bottom:8px}
  .kpi-v{font-size:1.75rem;font-weight:800;line-height:1.05}
  .kpi-s{font-size:.8rem;color:#8494A2;margin-top:4px}

  /* offene Trades (dezent) */
  .openbar{background:rgba(231,174,92,.10);border:1px solid rgba(231,174,92,.28);
    color:#EAD6B4;border-radius:10px;padding:8px 12px;font-size:.9rem;margin:.1rem 0 1rem}

  /* Standard-Metriken (Detailseiten) */
  [data-testid="stMetric"]{background:#161F2B;border:1px solid #253140;border-radius:14px;padding:14px 16px 12px}
  [data-testid="stMetricValue"]{font-size:1.4rem;font-weight:800}
  [data-testid="stMetricLabel"]{color:#8494A2}

  /* Buttons */
  .stButton>button{border-radius:10px;border:1px solid #3A3320;background:#E7AE5C;color:#1a1408;
    font-weight:700;padding:.5rem 1rem;transition:all .12s ease}
  .stButton>button:hover{background:#F1C079;border-color:#E7AE5C;transform:translateY(-1px)}
  [data-testid="stFileUploaderDropzone"]{border:1.6px dashed #33465A;border-radius:14px;background:#111A24}
</style>""", unsafe_allow_html=True)


def kpi(col, label, value, tone="neutral", sub=None):
    color = {"pos": "#2FB67A", "neg": "#E0635C", "neutral": "#E7ECF1", "gold": "#E7AE5C"}[tone]
    sub_html = f'<div class="kpi-s">{sub}</div>' if sub else ""
    col.markdown(
        f'<div class="kpi"><div class="kpi-l">{label}</div>'
        f'<div class="kpi-v" style="color:{color}">{value}</div>{sub_html}</div>',
        unsafe_allow_html=True)


# ======================================================================
#  Login (ein Passwort)
# ======================================================================
def _secret(name):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    import os
    return os.environ.get(name)


def require_login():
    if st.session_state.get("auth"):
        return
    st.title("🔒 Trading Journal")
    pw = st.text_input("Passwort", type="password")
    if st.button("Einloggen"):
        if pw and pw == _secret("APP_PASSWORD"):
            st.session_state["auth"] = True
            st.rerun()
        else:
            st.error("Passwort falsch.")
    st.stop()


require_login()
# Grunddaten nur EINMAL pro Sitzung anlegen (nicht bei jedem Klick — Tempo!)
if not st.session_state.get("seeded"):
    store.seed_defaults()
    st.session_state["seeded"] = True


# ======================================================================
#  Helfer
# ======================================================================
def compute_pnl(direction, entry, exit_, qty):
    if None in (entry, exit_, qty):
        return None
    return round((entry - exit_) * qty, 2) if direction == "Short" else round((exit_ - entry) * qty, 2)


def compute_r(pnl, entry, stop, qty):
    if None in (pnl, entry, stop, qty):
        return None
    risk = abs(entry - stop) * qty
    return round(pnl / risk, 2) if risk > 0 else None


def compute_pips(symbol, direction, entry, exit_):
    """Best-effort Pips fuer FX-aehnliche Paare."""
    if None in (entry, exit_) or not symbol:
        return None
    s = symbol.upper().replace("/", "")
    if len(s) < 6:           # nur fuer Waehrungspaare
        return None
    pip = 0.01 if "JPY" in s else 0.0001
    diff = (exit_ - entry) if direction != "Short" else (entry - exit_)
    return round(diff / pip, 1)


def trades_df(account_id):
    rows = store.list_trades(account_id)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for c in ("pnl", "pnl_r", "pips", "entry_price", "exit_price", "stop_price", "quantity"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["dt"] = pd.to_datetime(df.get("closed_at"), errors="coerce")
    if "created_at" in df:
        # Supabase liefert created_at MIT Zeitzone -> nach MEZ umrechnen und
        # Zeitzonen-Info entfernen, sonst wird die Spalte unbrauchbar (Crash).
        ca = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
        try:
            ca = ca.dt.tz_convert("Europe/Berlin").dt.tz_localize(None).dt.normalize()
        except Exception:
            ca = ca.dt.tz_localize(None)
        df["dt"] = df["dt"].fillna(ca)
    df["dt"] = pd.to_datetime(df["dt"], errors="coerce")   # garantiert datetime-Typ
    df["opened_dt"] = pd.to_datetime(df.get("opened_at"), errors="coerce") if "opened_at" in df else pd.NaT
    # Haltedauer in Tagen (Ausstieg - Einstieg); bei offenen Trades: heute - Einstieg
    exit_for_dur = pd.to_datetime(df.get("closed_at"), errors="coerce")
    today = pd.Timestamp(date.today())
    end = exit_for_dur.fillna(today)
    df["haltetage"] = (end - df["opened_dt"]).dt.days
    return df


def stats(closed):
    s = {}
    wins = closed[closed["pnl"] > 0]; losses = closed[closed["pnl"] < 0]
    s["n"] = len(closed); s["net"] = closed["pnl"].sum()
    s["win_rate"] = len(wins)/len(closed)*100 if len(closed) else 0
    s["avg_win"] = wins["pnl"].mean() if len(wins) else 0
    s["avg_loss"] = losses["pnl"].mean() if len(losses) else 0
    ls = losses["pnl"].sum()
    s["pf"] = (wins["pnl"].sum()/abs(ls)) if ls != 0 else float("inf")
    s["exp"] = closed["pnl"].mean() if len(closed) else 0
    s["avg_r"] = closed["pnl_r"].dropna().mean() if "pnl_r" in closed else None
    s["wins"], s["losses"] = len(wins), len(losses)
    chron = closed.sort_values("dt"); eq = chron["pnl"].cumsum()
    s["max_dd"] = (eq.cummax()-eq).max() if len(eq) else 0
    bw = bl = cur = last = 0
    for p in chron["pnl"]:
        sign = 1 if p > 0 else (-1 if p < 0 else 0)
        cur = cur+sign if sign == last else sign; last = sign
        bw = max(bw, cur); bl = min(bl, cur)
    s["sw"], s["sl"] = bw, abs(bl)
    return s


def acct_id():
    return st.session_state.get("acct_id")


# Gängige Symbole zum Auswählen (kein Tippen nötig)
PAIRS = [
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "USD/CAD", "AUD/USD", "NZD/USD",
    "EUR/GBP", "EUR/JPY", "EUR/CHF", "EUR/AUD", "EUR/CAD", "GBP/JPY", "GBP/CHF",
    "AUD/JPY", "CAD/JPY", "CHF/JPY", "NZD/JPY", "AUD/NZD", "GBP/AUD", "GBP/CAD",
    "XAU/USD", "XAG/USD", "WTI/USD", "US30", "US100", "US500", "GER40", "UK100",
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD",
]


def symbol_field(prefix, prefill_symbol):
    """Symbol per Auswahl (KI-Vorschlag vorausgewählt) ODER manuell im zweiten Feld."""
    norm = (prefill_symbol or "").upper().replace("/", "").replace(" ", "")
    match = next((p for p in PAIRS if p.replace("/", "") == norm), None)
    opts = ["— auswählen —"] + PAIRS
    idx = opts.index(match) if match else 0
    sel = st.selectbox("Symbol", opts, index=idx, key=f"symsel{prefix}")
    manual = st.text_input("… oder manuell eingeben", value=("" if match else (prefill_symbol or "")),
                           key=f"symman{prefix}", placeholder="z.B. EURUSD")
    if manual.strip():
        return manual.strip().upper()
    return None if sel == "— auswählen —" else sel


# ======================================================================
#  Trade-Formular (Einzel + Stapel)
# ======================================================================
def trade_form(prefix, prefill, setups, mistakes, rules, account_id, image_bytes=None, image_name=None):
    def pv(k, d=None):
        v = prefill.get(k); return v if v not in (None, "") else d

    with st.form(f"f_{prefix}"):
        c1, c2, c3 = st.columns(3)
        with c1:
            symbol = symbol_field(prefix, pv("symbol", ""))
        direction = c2.selectbox("Richtung", ["Long", "Short"],
                                 index=0 if str(pv("direction", "Long")).lower().startswith("l") else 1, key=f"di{prefix}")
        setup = c3.selectbox("Setup", setups or ["Sonstiges"], key=f"se{prefix}")

        status = st.radio("Status", ["Abgeschlossen", "Läuft noch (offen)"], horizontal=True, key=f"stt{prefix}",
                          help="„Läuft noch“ = Trade ist offen. Er erscheint in der History, zählt aber erst in die Statistik, sobald du ihn abschließt.")
        is_open_ui = status.startswith("Läuft")

        cD1, cD2 = st.columns(2)
        opened_d = cD1.date_input("Einstiegsdatum", value=date.today(), key=f"od{prefix}")
        closed_d = cD2.date_input("Ausstiegsdatum", value=date.today(), key=f"cd{prefix}",
                                  disabled=is_open_ui,
                                  help="Bei offenen Trades leer lassen — wird beim Abschließen eingetragen.")

        pnl_manual = st.number_input("Gewinn / Verlust in € (Minus = Verlust)",
                                     value=float(pv("pnl", 0.0)), format="%.2f", step=1.0, key=f"pn{prefix}",
                                     help="Trag hier einfach dein Ergebnis ein. Lässt du 0 stehen und füllst Entry/Exit/Lots aus, wird es automatisch berechnet.")

        # R-Multiple: aus 1R des Setups automatisch, aber vom Nutzer überschreibbar
        risk_1r = store.risk_for(setup)
        auto_r = (pnl_manual / risk_1r) if (risk_1r and pnl_manual) else float(pv("pnl_r", 0.0) or 0.0)
        cR1, cR2 = st.columns([2, 3])
        r_manual = cR1.number_input(
            "R-Multiple", value=round(auto_r, 2), step=0.1, format="%.2f", key=f"rm_r{prefix}",
            help="Vielfaches deines Risikos. Wird automatisch aus 1 R des Setups berechnet — hier änderbar.")
        if risk_1r:
            cR2.caption(f"1 R für **{setup}** = {risk_1r:,.2f} €  ·  automatisch: {auto_r:+.2f} R")
        else:
            cR2.caption("Für dieses Setup ist noch **kein 1 R** hinterlegt. "
                        "→ Einstellungen › 🎯 Risiko pro Setup")

        st.caption("Optional: Kurse für automatische Berechnung von P/L, R und Pips")
        c4, c5, c6, c7 = st.columns(4)
        entry = c4.number_input("Entry", value=float(pv("entry_price", 0.0)), format="%.6f", key=f"en{prefix}")
        exit_ = c5.number_input("Exit", value=float(pv("exit_price", 0.0)), format="%.6f", key=f"ex{prefix}")
        stop = c6.number_input("Stop", value=float(pv("stop_price", 0.0)), format="%.6f", key=f"st{prefix}")
        qty = c7.number_input("Lots / Groesse", value=float(pv("quantity", 0.0)), format="%.4f", key=f"qt{prefix}")

        c10, c11 = st.columns(2)
        emo = c10.selectbox("Emotion", ["—"] + store.EMOTIONS, key=f"em{prefix}")
        rating = c11.slider("Ausfuehrung 1–5", 1, 5, 3, key=f"ra{prefix}")

        sel_m = st.multiselect("Fehler-Tags", mistakes, key=f"mi{prefix}")
        sel_rules = st.multiselect("Eingehaltene Regeln", rules, default=rules, key=f"ru{prefix}")

        st.caption("Reflexion — Tipp: ins Feld klicken und die Mac-/Chrome-Diktierfunktion nutzen 🎙")
        r_in = st.text_area("Warum bin ich eingestiegen?", height=70, key=f"ri{prefix}")
        r_out = st.text_area("Warum / wie habe ich geschlossen?", height=70, key=f"ro{prefix}")
        r_mng = st.text_area("Wie habe ich den Trade gemanaged?", height=70, key=f"rm{prefix}")
        notes = st.text_area("Freie Notiz", value=pv("notes", ""), height=70, key=f"no{prefix}")

        submitted = st.form_submit_button("💾 Trade speichern")

    if submitted:
        is_open = status.startswith("Läuft")
        e, x, sp, q = entry or None, exit_ or None, stop or None, qty or None
        pnl = None if is_open else (pnl_manual if pnl_manual != 0 else compute_pnl(direction, e, x, q))
        sym = (symbol or "").strip().upper() or None
        rec = {
            "account_id": account_id, "symbol": sym, "direction": direction,
            "entry_price": e, "exit_price": x, "stop_price": sp, "quantity": q,
            "pnl": pnl,
            "pnl_r": None if is_open else (r_manual if r_manual != 0 else compute_r(pnl, e, sp, q)),
            "pips": None if is_open else compute_pips(sym, direction, e, x),
            "status": "offen" if is_open else "zu",
            "opened_at": opened_d.isoformat(),
            "closed_at": None if is_open else closed_d.isoformat(),
            "setup": setup,
            "mistakes": sel_m, "rules_followed": sel_rules,
            "emotion": None if emo == "—" else emo, "rating": rating,
            "reason_entry": r_in.strip() or None, "reason_exit": r_out.strip() or None,
            "management": r_mng.strip() or None, "notes": notes.strip() or None,
        }
        if image_bytes is not None:
            try:
                rec["image_path"] = store.upload_image(image_bytes, image_name or "trade.png")
            except Exception:
                st.warning("Hinweis: Das Bild konnte nicht gespeichert werden – der Trade wird ohne Bild gesichert. "
                           "(Lege in Supabase unter Storage einen Bucket namens 'screenshots' an, dann werden Bilder mitgespeichert.)")
        store.add_trade(rec)
        return True
    return False


# ======================================================================
#  Seiten
# ======================================================================
def page_start():
    st.title("🏠 Meine Konten")
    cols = st.columns(3)
    for i, a in enumerate(store.list_accounts()):
        df = trades_df(a["id"]); closed = df.dropna(subset=["pnl"]) if not df.empty else pd.DataFrame()
        net = closed["pnl"].sum() if not closed.empty else 0
        wr = len(closed[closed["pnl"] > 0])/len(closed)*100 if len(closed) else 0
        with cols[i % 3]:
            cur = a.get("currency") or ""
            bal = (a.get("start_balance") or 0) + net
            st.subheader(a["name"])
            st.metric("Kontostand", f"{bal:,.2f} {cur}", delta=f"{net:,.2f} {cur}")
            st.caption(f"Trefferquote {wr:.0f} % · {len(closed)} Trades")
            if st.button("Öffnen", key=f"op{a['id']}"):
                st.session_state["pending_acct"] = a["id"]
                st.session_state["go_dashboard"] = True
                st.rerun()


def dashboard_dropzone():
    nonce = st.session_state.get("dropnonce", 0)
    drop = st.file_uploader("📥 Trade-Screenshot hier reinziehen — bringt dich direkt zur Eingabe",
                            type=["png", "jpg", "jpeg", "webp"], key=f"dashdrop{nonce}")
    if drop is not None:
        drop.seek(0)
        st.session_state["incoming_img"] = {"name": drop.name, "bytes": drop.read()}
        st.session_state["dropnonce"] = nonce + 1
        st.session_state["go_new"] = True
        st.rerun()


def page_dashboard():
    a = next((x for x in store.list_accounts() if x["id"] == acct_id()), None)
    st.title(f"📊 Dashboard — {a['name'] if a else ''}")
    cur = (a.get("currency") if a else "") or ""
    start_bal = (a.get("start_balance") if a else 0) or 0

    dashboard_dropzone()

    df = trades_df(acct_id())

    # Offene Trades kompakt anzeigen (Swing-Erinnerung)
    if not df.empty and "status" in df.columns:
        od = df[df["status"] == "offen"]
        if not od.empty:
            parts = []
            for _, o in od.head(6).iterrows():
                d = str(o.get("opened_at") or o.get("closed_at") or "")[:10]
                tage = o.get("haltetage")
                seit = f" (seit {d}" + (f", {int(tage)} T" if pd.notna(tage) else "") + ")" if d else ""
                parts.append(f"{o.get('symbol') or '—'}{seit}")
            st.markdown(f'<div class="openbar">🟡 <b>{len(od)} offen:</b> ' + " · ".join(parts) + '</div>',
                        unsafe_allow_html=True)

    # Kapital (Ein-/Auszahlungen) des aktiven Kontos
    cfs = store.list_cashflows(acct_id())
    deposits_net = sum(float(c.get("amount") or 0) for c in cfs)

    closed_all = df.dropna(subset=["pnl"]).copy() if not df.empty else pd.DataFrame()
    total_pnl_all = closed_all["pnl"].sum() if not closed_all.empty else 0
    balance = start_bal + deposits_net + total_pnl_all   # echter Kontostand (inkl. Einzahlungen)

    # --- Zeitraum-Filter ---
    period = st.selectbox("Zeitraum", ["Alles", "Diese Woche", "Dieser Monat", "Letzte 30 Tage", "Benutzerdefiniert"],
                          key="dashperiod")
    today = pd.Timestamp(date.today()).normalize()
    start_p, end_p = None, today
    if period == "Diese Woche":
        start_p = today - pd.Timedelta(days=today.weekday())
    elif period == "Dieser Monat":
        start_p = today.replace(day=1)
    elif period == "Letzte 30 Tage":
        start_p = today - pd.Timedelta(days=30)
    elif period == "Benutzerdefiniert":
        cc1, cc2 = st.columns(2)
        d_from = cc1.date_input("Von", value=date.today().replace(day=1), key="pf_from")
        d_to = cc2.date_input("Bis", value=date.today(), key="pf_to")
        start_p = pd.Timestamp(d_from).normalize(); end_p = pd.Timestamp(d_to).normalize()

    # Kontostand-Karte immer gesamt (inkl. Einzahlungen)
    r0 = st.columns(4)
    kpi(r0[0], "Kontostand", f"{balance:,.2f} {cur}", "gold",
        sub=(f"inkl. {deposits_net:,.2f} {cur} Ein-/Auszahlungen" if deposits_net else None))

    if closed_all.empty:
        kpi(r0[1], "Netto P/L", f"0.00 {cur}", "neutral")
        kpi(r0[2], "Trefferquote", "0 %", "neutral")
        kpi(r0[3], "Trades", "0", "neutral")
        st.info("Noch keine Trades mit Ergebnis. Zieh oben einen Screenshot rein oder geh auf **➕ Neuer Trade**.")
        return

    # Zeitraum auf abgeschlossene Trades anwenden
    if start_p is not None:
        end_incl = end_p + pd.Timedelta(days=1)
        m = (closed_all["dt"] >= start_p) & (closed_all["dt"] < end_incl)
        closed = closed_all[m].copy()
        pre = closed_all[closed_all["dt"] < start_p]
        suffix = " (Zeitraum)"
    else:
        closed = closed_all.copy()
        pre = closed_all.iloc[0:0]
        suffix = ""

    pre_pnl = pre["pnl"].sum() if not pre.empty else 0
    base_curve = start_bal + pre_pnl   # Startpunkt der Kurve: nur Trades, OHNE Ein-/Auszahlungen

    if closed.empty:
        kpi(r0[1], "Netto P/L" + suffix, f"0.00 {cur}", "neutral")
        kpi(r0[2], "Trefferquote", "0 %", "neutral")
        kpi(r0[3], "Trades", "0", "neutral")
        st.info("Keine abgeschlossenen Trades in diesem Zeitraum.")
        return

    s = stats(closed)
    net_tone = "pos" if s["net"] >= 0 else "neg"
    # Summe R (nur numerische, echte Werte)
    r_sum = float(pd.to_numeric(closed.get("pnl_r"), errors="coerce").sum()) if "pnl_r" in closed else 0.0
    r_tone = "pos" if r_sum >= 0 else "neg"
    kpi(r0[1], "Netto P/L" + suffix, f"{s['net']:,.2f} {cur}", net_tone)
    kpi(r0[2], "Trefferquote", f"{s['win_rate']:.0f} %", "neutral")
    kpi(r0[3], "Trades", f"{s['n']}", "neutral")
    r2 = st.columns(4)
    kpi(r2[0], "Gewinner / Verlierer", f"{s['wins']} / {s['losses']}", "neutral")
    kpi(r2[1], "Profit-Faktor", "∞" if s["pf"] == float("inf") else f"{s['pf']:.2f}", "neutral")
    kpi(r2[2], "Ø R", "—" if s["avg_r"] is None or pd.isna(s["avg_r"]) else f"{s['avg_r']:.2f} R", "neutral")
    kpi(r2[3], "Summe R", f"{r_sum:+.2f} R", r_tone)
    r3 = st.columns(4)
    kpi(r3[0], "Max. Drawdown", ("0.00 " + cur) if s["max_dd"] <= 0 else f"-{s['max_dd']:,.2f} {cur}",
        "neg" if s["max_dd"] > 0 else "neutral")

    st.divider()
    col_eq, col_donut = st.columns([2, 1])
    with col_eq:
        st.subheader("Performance-Kurve")
        st.caption("Kontostand nur aus Trades — Ein-/Auszahlungen sind hier bewusst nicht enthalten.")
        eq = closed.sort_values("dt").reset_index(drop=True).copy()
        eq["balance"] = base_curve + eq["pnl"].cumsum()
        eq["Trade"] = range(1, len(eq) + 1)
        start_row = pd.DataFrame({"Trade": [0], "balance": [base_curve]})
        eqp = pd.concat([start_row, eq[["Trade", "balance"]]], ignore_index=True)
        col = "#2FB67A" if eqp["balance"].iloc[-1] >= base_curve else "#E0635C"
        ymin, ymax = float(eqp["balance"].min()), float(eqp["balance"].max())
        pad = max((ymax - ymin) * 0.15, abs(ymax) * 0.02, 1.0)
        base = alt.Chart(eqp).encode(
            x=alt.X("Trade:Q", title=None, axis=alt.Axis(tickMinStep=1, format="d")),
            y=alt.Y("balance:Q", title=cur, scale=alt.Scale(domain=[ymin - pad, ymax + pad], nice=False)))
        area = base.mark_area(opacity=0.14, color=col)
        line = base.mark_line(color=col, strokeWidth=2.5)
        st.altair_chart((area + line).properties(height=300), use_container_width=True)
    with col_donut:
        st.subheader("Gewinner / Verlierer")
        dd = pd.DataFrame({"Ergebnis": ["Gewinner", "Verlierer"], "Anzahl": [s["wins"], s["losses"]]})
        ring = alt.Chart(dd).mark_arc(innerRadius=62, outerRadius=95).encode(
            theta="Anzahl:Q",
            color=alt.Color("Ergebnis:N",
                            scale=alt.Scale(domain=["Gewinner", "Verlierer"], range=["#2FB67A", "#E0635C"]),
                            legend=alt.Legend(title=None, orient="bottom")))
        mid = alt.Chart(pd.DataFrame({"t": [f"{s['win_rate']:.0f}%"]})).mark_text(
            size=30, fontWeight="bold", color="#E7ECF1").encode(text="t:N")
        st.altair_chart((ring + mid).properties(height=300), use_container_width=True)

    # Disziplin: Win-Rate mit vs. ohne alle Regeln
    rules = store.get_list("rules") or []
    if rules and "rules_followed" in closed:
        def all_rules(x): return isinstance(x, list) and all(r in x for r in rules)
        disc = closed[closed["rules_followed"].apply(all_rules)]
        indisc = closed[~closed["rules_followed"].apply(all_rules)]
        wr_d = len(disc[disc["pnl"] > 0])/len(disc)*100 if len(disc) else 0
        wr_i = len(indisc[indisc["pnl"] > 0])/len(indisc)*100 if len(indisc) else 0
        st.caption(f"🧭 Disziplin — Trefferquote **mit** allen Regeln: {wr_d:.0f} % ({len(disc)}) · **ohne**: {wr_i:.0f} % ({len(indisc)})")

    # --- Zeit-Übersicht: Tage / Wochen / Monate (kompakt, einklappbar) ---
    with st.expander("📅 Zeit-Übersicht — Tage · Wochen · Monate", expanded=False):
        tt = closed.copy()
        tt["dt"] = pd.to_datetime(tt["dt"], errors="coerce")
        tt = tt.dropna(subset=["dt"])
        if tt.empty:
            st.caption("Keine datierten Trades im Zeitraum.")
        else:
            def _period_table(df_p, label):
                has_r = "pnl_r" in df_p.columns
                if has_r:
                    df_p = df_p.copy()
                    df_p["pnl_r"] = pd.to_numeric(df_p["pnl_r"], errors="coerce")
                    g = df_p.groupby("periode").agg(
                        pnl=("pnl", "sum"), trades=("pnl", "size"),
                        wins=("pnl", lambda x: int((x > 0).sum())),
                        r=("pnl_r", "sum"))
                else:
                    g = df_p.groupby("periode").agg(
                        pnl=("pnl", "sum"), trades=("pnl", "size"),
                        wins=("pnl", lambda x: int((x > 0).sum())))
                    g["r"] = 0.0
                g["quote"] = (g["wins"] / g["trades"] * 100).round(0)
                g = g.sort_index(ascending=False)
                for idx, row in g.iterrows():
                    p1, p2, p3, p4, p5 = st.columns([3, 2, 2, 2, 2])
                    p1.markdown(f"**{idx}**")
                    farbe = "#2FB67A" if row["pnl"] >= 0 else "#E0635C"
                    p2.markdown(f"<span style='color:{farbe};font-weight:700'>{row['pnl']:+,.2f} {cur}</span>",
                                unsafe_allow_html=True)
                    r_val = float(row["r"]) if pd.notna(row["r"]) else 0.0
                    r_col = "#2FB67A" if r_val >= 0 else "#E0635C"
                    p3.markdown(f"<span style='color:{r_col};font-weight:700'>{r_val:+.2f} R</span>",
                                unsafe_allow_html=True)
                    p4.write(f"{int(row['trades'])} Trades")
                    p5.write(f"{row['quote']:.0f} %")

            tab_d, tab_w, tab_m = st.tabs(["Tage", "Wochen", "Monate"])
            with tab_d:
                d = tt.copy(); d["periode"] = d["dt"].dt.strftime("%d.%m.%Y")
                d = d.sort_values("dt")
                _period_table(d, "Tag")
            with tab_w:
                w = tt.copy()
                iso = w["dt"].dt.isocalendar()
                w["periode"] = "KW " + iso.week.astype(str).str.zfill(2) + " / " + iso.year.astype(str)
                _period_table(w, "Woche")
            with tab_m:
                m_ = tt.copy(); m_["periode"] = m_["dt"].dt.strftime("%m/%Y")
                _period_table(m_, "Monat")

    def hbars(d, label_col):
        """Schlanke horizontale Balken mit Wert-Beschriftung — edler & lesbarer."""
        d = d.reset_index(); d.columns = [label_col, "pnl"]
        d["farbe"] = d["pnl"].apply(lambda v: "Gewinn" if v >= 0 else "Verlust")
        h = max(46 * len(d) + 30, 120)
        base = alt.Chart(d).encode(
            y=alt.Y(f"{label_col}:N", title=None, sort=None,
                    axis=alt.Axis(grid=False, ticks=False, domain=False, labelColor="#AEB9C4")),
            x=alt.X("pnl:Q", title=None,
                    axis=alt.Axis(grid=False, ticks=False, domain=False, labels=False)))
        bars = base.mark_bar(cornerRadiusEnd=5, height=20).encode(
            color=alt.Color("farbe:N", scale=alt.Scale(domain=["Gewinn", "Verlust"],
                            range=["#2FB67A", "#E0635C"]), legend=None))
        txt = base.mark_text(align="left", dx=6, fontWeight="bold", color="#E7ECF1").encode(
            text=alt.Text("pnl:Q", format="+,.0f"))
        st.altair_chart((bars + txt).properties(height=h), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("P/L nach Setup")
        bs = closed.groupby("setup")["pnl"].sum().sort_values(ascending=False)
        if not bs.empty: hbars(bs, "Setup")
    with c2:
        st.subheader("P/L nach Wochentag")
        names = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        t = closed.dropna(subset=["dt"]).copy()
        if not t.empty:
            t["wd"] = t["dt"].dt.weekday.map(lambda i: names[i])
            wk = t.groupby("wd")["pnl"].sum().reindex(names).dropna()
            if not wk.empty: hbars(wk, "Wochentag")

    # --- Trading-Kalender: Monatsraster mit Tages-P/L (gruen/rot) ---
    st.subheader("📅 Trading-Kalender")
    cal_src = closed_all.copy()
    cal_src["dt"] = pd.to_datetime(cal_src["dt"], errors="coerce")
    cal_src = cal_src.dropna(subset=["dt"])
    if cal_src.empty:
        st.caption("Noch keine datierten Trades.")
    else:
        months = sorted(cal_src["dt"].dt.strftime("%Y-%m").unique(), reverse=True)
        cur_month = pd.Timestamp(date.today()).strftime("%Y-%m")
        if cur_month not in months:
            months = [cur_month] + months
        sel_m = st.selectbox("Monat", months, index=0, key="calmonth",
                             format_func=lambda m: f"{m[5:]}/{m[:4]}")
        y, mo = int(sel_m[:4]), int(sel_m[5:])
        mdf = cal_src[(cal_src["dt"].dt.year == y) & (cal_src["dt"].dt.month == mo)].copy()
        if "pnl_r" in mdf.columns:
            mdf["pnl_r"] = pd.to_numeric(mdf["pnl_r"], errors="coerce")
            g = mdf.groupby(mdf["dt"].dt.day).agg(
                pnl=("pnl", "sum"), n=("pnl", "size"),
                wins=("pnl", lambda x: int((x > 0).sum())),
                r=("pnl_r", "sum"))
        else:
            g = mdf.groupby(mdf["dt"].dt.day).agg(
                pnl=("pnl", "sum"), n=("pnl", "size"),
                wins=("pnl", lambda x: int((x > 0).sum())))
            g["r"] = 0.0
        m_pnl = float(mdf["pnl"].sum()) if not mdf.empty else 0.0
        m_r = float(pd.to_numeric(mdf.get("pnl_r"), errors="coerce").sum()) if not mdf.empty else 0.0
        m_col = "#2FB67A" if m_pnl >= 0 else "#E0635C"
        r_col_m = "#2FB67A" if m_r >= 0 else "#E0635C"
        st.markdown(
            f"<div style='margin:.2rem 0 .6rem'>Monats-P/L: "
            f"<b style='color:{m_col}'>{m_pnl:+,.2f} {cur}</b> · "
            f"<b style='color:{r_col_m}'>{m_r:+.2f} R</b> · "
            f"{len(mdf)} Trades</div>",
            unsafe_allow_html=True)

        import calendar as _cal
        weeks = _cal.Calendar(firstweekday=0).monthdayscalendar(y, mo)  # Montag zuerst (MEZ/DE)
        head = "".join(f"<div class='calh'>{w}</div>" for w in ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"])
        cells = []
        for week in weeks:
            for d in week:
                if d == 0:
                    cells.append("<div class='calc calc-empty'></div>")
                    continue
                if d in g.index:
                    row = g.loc[d]
                    pnl, n, wins = float(row["pnl"]), int(row["n"]), int(row["wins"])
                    r_day = float(row["r"]) if pd.notna(row["r"]) else 0.0
                    wr = wins / n * 100 if n else 0
                    cls = "calc-pos" if pnl > 0 else ("calc-neg" if pnl < 0 else "calc-zero")
                    cells.append(
                        f"<div class='calc {cls}'><div class='cald'>{d}</div>"
                        f"<div class='calp'>{pnl:+,.0f}</div>"
                        f"<div class='calr'>{r_day:+.2f} R</div>"
                        f"<div class='calm'>{n} T · {wr:.0f}%</div></div>")
                else:
                    cells.append(f"<div class='calc'><div class='cald'>{d}</div></div>")
        st.markdown("""<style>
          .calgrid{display:grid;grid-template-columns:repeat(7,1fr);gap:6px;margin-top:.3rem}
          .calh{color:#8494A2;font-size:.72rem;font-weight:700;text-transform:uppercase;
                letter-spacing:.05em;text-align:center;padding:2px 0}
          .calc{background:#141C27;border:1px solid #232F3D;border-radius:10px;
                min-height:64px;padding:6px 8px}
          .calc-empty{background:transparent;border:none}
          .calc-pos{background:rgba(47,182,122,.14);border-color:rgba(47,182,122,.45)}
          .calc-neg{background:rgba(224,99,92,.14);border-color:rgba(224,99,92,.45)}
          .calc-zero{border-color:#33465A}
          .cald{color:#8494A2;font-size:.72rem;font-weight:600}
          .calp{font-weight:800;font-size:.95rem;margin-top:2px;color:#E7ECF1}
          .calc-pos .calp{color:#2FB67A}.calc-neg .calp{color:#E0635C}
          .calr{font-size:.72rem;font-weight:700;color:#AEB9C4;margin-top:1px}
          .calc-pos .calr{color:#2FB67A}.calc-neg .calr{color:#E0635C}
          .calm{color:#8494A2;font-size:.7rem;margin-top:1px}
        </style>""", unsafe_allow_html=True)
        st.markdown(f"<div class='calgrid'>{head}{''.join(cells)}</div>", unsafe_allow_html=True)

    st.subheader("Häufigste Fehler")
    allm = [m for lst in closed["mistakes"] if isinstance(lst, list) for m in lst]
    if allm:
        vc = pd.Series(allm).value_counts().reset_index()
        vc.columns = ["Fehler", "Anzahl"]
        h = max(40 * len(vc) + 30, 110)
        ch = alt.Chart(vc).mark_bar(cornerRadiusEnd=5, height=18, color="#E7AE5C").encode(
            y=alt.Y("Fehler:N", title=None, sort="-x",
                    axis=alt.Axis(grid=False, ticks=False, domain=False, labelColor="#AEB9C4")),
            x=alt.X("Anzahl:Q", title=None,
                    axis=alt.Axis(grid=False, ticks=False, domain=False, labels=False)))
        tx = alt.Chart(vc).mark_text(align="left", dx=6, color="#E7ECF1", fontWeight="bold").encode(
            y=alt.Y("Fehler:N", sort="-x"), x="Anzahl:Q", text="Anzahl:Q")
        st.altair_chart((ch + tx).properties(height=h), use_container_width=True)
    else:
        st.caption("Noch keine Fehler-Tags.")


def page_new():
    st.title("➕ Neuer Trade")
    setups = store.get_list("setups") or []; mistakes = store.get_list("mistakes") or []; rules = store.get_list("rules") or []

    # Quellen sammeln: vom Dashboard reingezogenes Bild + hochgeladene Dateien
    sources = []
    inc = st.session_state.get("incoming_img")
    if inc:
        sources.append((inc["name"], inc["bytes"]))
    files = st.file_uploader("📎 Screenshot(s) hierher ziehen oder auswählen",
                             type=["png", "jpg", "jpeg", "webp"], accept_multiple_files=True)
    for f in files or []:
        f.seek(0); sources.append((f.name, f.read()))

    if not sources:
        st.caption("Kein Bild? Du kannst alles manuell eintragen.")
        if trade_form("manual", {}, setups, mistakes, rules, acct_id()):
            st.success("Gespeichert ✔")
        return

    saved = st.session_state.setdefault("saved", set())
    for name, data in sources:
        with st.expander(f"🖼 {name}", expanded=(len(sources) == 1)):
            if name in saved:
                st.success("Bereits gespeichert ✔"); continue
            st.image(data, width=380)
            pk = f"pf_{name}"
            ver = st.session_state.get(f"ver_{name}", 0)
            if st.button("🤖 Mit KI auslesen", key=f"ai_{name}"):
                with st.spinner("KI liest…"):
                    try:
                        st.session_state[pk] = ai.extract_trade_from_image(data, name)
                        st.session_state[f"ver_{name}"] = ver + 1   # frische Felder -> Prefill greift
                        st.toast("KI-Werte übernommen ✔ — bitte prüfen")
                        st.rerun()
                    except Exception as e:
                        st.error(f"KI fehlgeschlagen: {e}")
            if trade_form(f"{name}~{ver}", st.session_state.get(pk, {}), setups, mistakes, rules, acct_id(),
                          image_bytes=data, image_name=name):
                saved.add(name)
                if inc and name == inc["name"]:
                    st.session_state.pop("incoming_img", None)
                st.success("Gespeichert ✔"); st.rerun()

    st.divider()
    with st.expander("📥 MetaTrader-5-Import (optional)", expanded=False):
        st.caption("In MT5: Verlauf → Rechtsklick → **Bericht** als HTML speichern (oder CSV) → hier reinziehen. "
                   "Doppelte Trades werden automatisch erkannt und übersprungen.")
        up = st.file_uploader("MT5-Bericht (HTML/CSV)", type=["html", "htm", "xls", "csv", "txt"], key="mt5file")
        if up is not None:
            try:
                up.seek(0)
                parsed = mt5_import.parse_mt5(up.read(), up.name)
            except Exception as e:
                st.error(f"Datei konnte nicht gelesen werden: {e}")
                parsed = []
            if parsed:
                existing = store.list_trades(acct_id())
                fresh, dupes, unsure = mt5_import.dedupe(parsed, existing)
                st.markdown(f"**Vorschau:** 🟢 {len(fresh)} neu · ⚪ {len(dupes)} übersprungen (schon vorhanden) "
                            f"· 🟠 {len(unsure)} unsicher")
                if unsure:
                    st.warning("Unsichere Kandidaten (gleiches Symbol, Datum und P/L wie ein vorhandener Trade). "
                               "Nur ankreuzen, was wirklich NEU ist:")
                    take = []
                    for i, u in enumerate(unsure):
                        lbl = f"{u['symbol']} · {u.get('closed_at') or '—'} · {u.get('pnl'):+.2f}"
                        if st.checkbox(lbl, value=False, key=f"unsure{i}"):
                            take.append(u)
                else:
                    take = []
                if fresh or take:
                    if st.button(f"✅ {len(fresh) + len(take)} Trades importieren"):
                        n = 0
                        for t in fresh + take:
                            rec = {k: v for k, v in t.items() if v is not None}
                            rec["account_id"] = acct_id()
                            rec["status"] = "zu"
                            rec.setdefault("setup", "Sonstiges")
                            store.add_trade(rec)
                            n += 1
                        st.success(f"{n} Trades importiert ✔")
                        st.rerun()
                elif not unsure:
                    st.info("Nichts zu importieren — alles schon vorhanden.")


def page_trades():
    st.title("📋 Alle Trades")
    rows = store.list_trades(acct_id())
    if not rows:
        st.info("Noch keine Trades."); return
    df = trades_df(acct_id())
    # Fortlaufende Nummer pro Konto — ohne Luecken, aeltester = #1.
    # Wird live berechnet: nach dem Loeschen rutschen die Nummern automatisch nach.
    order = df.sort_values("id", ascending=True)["id"].tolist()
    id_to_nr = {tid: i + 1 for i, tid in enumerate(order)}
    df["Nr"] = df["id"].map(id_to_nr)
    if "status" in df:
        df["Status"] = df["status"].map(lambda s: "🟡 läuft" if s == "offen" else "✅ zu")
    else:
        df["Status"] = "✅ zu"
    df["Einstieg"] = df.get("opened_at")
    df["Ausstieg"] = df.get("closed_at")
    df["Haltetage"] = df.get("haltetage")
    cols = [c for c in ["Nr", "Einstieg", "Ausstieg", "Haltetage", "symbol", "direction",
                        "setup", "Status", "pnl", "pips", "pnl_r", "rating"] if c in df]
    show = df.sort_values("Nr", ascending=False)[cols]      # neueste zuerst anzeigen
    st.dataframe(show, use_container_width=True, hide_index=True)
    st.divider()
    sel = st.selectbox("Trade öffnen", [r["id"] for r in rows],
                       format_func=lambda i: f"#{id_to_nr.get(i, '?')} — {store.get_trade(i).get('symbol') or ''}"
                                             if False else f"#{id_to_nr.get(i, '?')}")
    t = store.get_trade(sel)
    if not t: return
    left, right = st.columns(2)
    with left:
        url = store.image_url(t.get("image_path"))
        if url:
            st.image(url, use_container_width=True)
        else:
            st.caption("Kein Screenshot.")
        badge = "🟡 läuft noch" if t.get("status") == "offen" else "✅ abgeschlossen"
        dauer = ""
        if t.get("opened_at"):
            end = t.get("closed_at") or date.today().isoformat()
            try:
                tage = (pd.to_datetime(end) - pd.to_datetime(t["opened_at"])).days
                dauer = f" · Haltedauer {tage} Tage"
            except Exception:
                pass
        st.write(f"**Nr {id_to_nr.get(sel, '?')}** · **{t.get('symbol')}** · {t.get('direction')} · {t.get('setup')} · {badge}  \n"
                 f"Einstieg {t.get('opened_at') or '—'} → Ausstieg {t.get('closed_at') or '—'}{dauer}  \n"
                 f"Entry {t.get('entry_price')} → Exit {t.get('exit_price')} · Stop {t.get('stop_price')}  \n"
                 f"P/L **{t.get('pnl')}** · {t.get('pnl_r')} R · {t.get('pips')} Pips")
        if t.get("ai_setup") is not None:
            st.markdown(f"**KI-Urteil:** Setup {t['ai_setup']} · Ausführung {t.get('ai_exec')} · Psyche {t.get('ai_psych')}")
            if t.get("ai_weakness"): st.caption(f"Schwäche: {t['ai_weakness']}")
            if t.get("ai_tip"): st.caption(f"Tipp: {t['ai_tip']}")
        if st.button("🤖 KI-Urteil erstellen"):
            with st.spinner("KI bewertet…"):
                try:
                    store.update_trade(sel, ai.score_trade(t)); st.success("Bewertet ✔ — neu laden."); 
                except Exception as e:
                    st.error(f"Fehlgeschlagen: {e}")
    with right:
        setups = store.get_list("setups") or []; mistakes = store.get_list("mistakes") or []
        is_open_now = (t.get("status") == "offen")
        with st.form("edit"):
            st.markdown("**Trade bearbeiten**")
            if is_open_now:
                st.info("Dieser Trade läuft noch. Trag unten das Ergebnis ein und stell auf „Abgeschlossen“, um ihn in die Statistik zu übernehmen.")
            new_status = st.radio("Status", ["Abgeschlossen", "Läuft noch (offen)"],
                                  index=1 if is_open_now else 0, horizontal=True)

            def _parse_d(s):
                try:
                    return datetime.fromisoformat(str(s)[:10]).date()
                except Exception:
                    return date.today()
            d1, d2 = st.columns(2)
            c_open = d1.date_input("Einstiegsdatum", value=_parse_d(t.get("opened_at")))
            c_close = d2.date_input("Ausstiegsdatum", value=_parse_d(t.get("closed_at")),
                                    disabled=new_status.startswith("Läuft"))
            e1, e2 = st.columns(2)
            csym = e1.text_input("Symbol", value=t.get("symbol") or "")
            cdir = e2.selectbox("Richtung", ["Long", "Short"],
                                index=0 if str(t.get("direction", "Long")).lower().startswith("l") else 1)
            e3, e4 = st.columns(2)
            ce = e3.number_input("Entry", value=float(t.get("entry_price") or 0.0), format="%.6f")
            cx = e4.number_input("Exit", value=float(t.get("exit_price") or 0.0), format="%.6f")
            e5, e6 = st.columns(2)
            cstop = e5.number_input("Stop", value=float(t.get("stop_price") or 0.0), format="%.6f")
            cq = e6.number_input("Lots / Größe", value=float(t.get("quantity") or 0.0), format="%.4f")
            new_pnl = st.number_input("Gewinn / Verlust in € (Minus = Verlust)",
                                      value=float(t.get("pnl") or 0.0), format="%.2f", step=1.0)
            setup = st.selectbox("Setup", setups, index=setups.index(t["setup"]) if t.get("setup") in setups else 0)
            # R fuer diesen Trade: Vorschlag aus 1R des Setups, aber ueberschreibbar
            risk_1r = store.risk_for(setup)
            suggested_r = (new_pnl / risk_1r) if (risk_1r and new_pnl) else float(t.get("pnl_r") or 0.0)
            rr1, rr2 = st.columns([2, 3])
            new_r = rr1.number_input("R-Multiple", value=round(suggested_r, 2), step=0.1, format="%.2f")
            if risk_1r:
                rr2.caption(f"1 R für **{setup}** = {risk_1r:,.2f} €  ·  Vorschlag: {suggested_r:+.2f} R")
            else:
                rr2.caption("Für dieses Setup ist noch **kein 1 R** hinterlegt (Einstellungen › 🎯 Risiko pro Setup).")
            sel_m = st.multiselect("Fehler-Tags", mistakes, default=t.get("mistakes") or [])
            r_in = st.text_area("Warum eingestiegen?", value=t.get("reason_entry") or "", height=70)
            r_out = st.text_area("Warum/wie geschlossen?", value=t.get("reason_exit") or "", height=70)
            r_mng = st.text_area("Management?", value=t.get("management") or "", height=70)
            notes = st.text_area("Notiz", value=t.get("notes") or "", height=80)
            if st.form_submit_button("💾 Speichern"):
                will_open = new_status.startswith("Läuft")
                sym = (csym or "").strip().upper() or None
                store.update_trade(sel, {
                    "symbol": sym, "direction": cdir,
                    "entry_price": ce or None, "exit_price": cx or None,
                    "stop_price": cstop or None, "quantity": cq or None,
                    "setup": setup, "mistakes": sel_m,
                    "status": "offen" if will_open else "zu",
                    "opened_at": c_open.isoformat(),
                    "closed_at": None if will_open else c_close.isoformat(),
                    "pnl": None if will_open else new_pnl,
                    "pnl_r": None if will_open else (new_r if new_r != 0
                                                    else compute_r(new_pnl, ce or None, cstop or None, cq or None)),
                    "pips": None if will_open else compute_pips(sym, cdir, ce or None, cx or None),
                    "reason_entry": r_in.strip() or None, "reason_exit": r_out.strip() or None,
                    "management": r_mng.strip() or None, "notes": notes.strip() or None})
                st.success("Aktualisiert ✔ — neu laden.")
        if st.button("🗑 Löschen"):
            store.delete_trade(sel); st.warning("Gelöscht — neu laden.")


def page_coach():
    st.title("🧠 KI-Coach")
    rows = store.list_trades(acct_id())
    if not rows:
        st.info("Noch keine Trades."); return
    st.subheader("Frag dein Journal")
    q = st.text_input("z.B. Wie ist meine Trefferquote bei EURUSD vormittags?")
    if st.button("Fragen") and q:
        with st.spinner("KI denkt…"):
            try: st.markdown(ai.ask_journal(q, rows))
            except Exception as e: st.error(f"Fehlgeschlagen: {e}")
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Review")
        total = len(rows)
        if total <= 3:
            n = total
            st.caption(f"Es werden alle {total} Trades ausgewertet.")
        else:
            n = st.slider("Letzte … Trades", 3, total, min(20, total))
        if st.button("Auswertung starten"):
            with st.spinner("KI analysiert…"):
                try: st.markdown(ai.review(rows[:n]))
                except Exception as e: st.error(f"Fehlgeschlagen: {e}")
    with c2:
        st.subheader("Coach-Profil")
        st.markdown(store.get_coach_profile() or "_Noch leer._")
        if st.button("Profil aktualisieren"):
            with st.spinner("KI aktualisiert…"):
                try:
                    new = ai.refine_coach_profile(store.get_coach_profile(), rows[:30])
                    store.set_coach_profile(new); st.success("Aktualisiert ✔ — neu laden.")
                except Exception as e: st.error(f"Fehlgeschlagen: {e}")


def page_settings():
    st.title("⚙️ Einstellungen")
    st.subheader("Konten")
    for a in store.list_accounts():
        c1, c2, c3 = st.columns([3, 2, 1])
        c1.write(f"**{a['name']}** ({a.get('currency') or 'EUR'})")
        new_bal = c2.number_input("Startguthaben", value=float(a.get("start_balance") or 0),
                                  format="%.2f", step=100.0, key=f"bal{a['id']}")
        if new_bal != float(a.get("start_balance") or 0):
            store.update_account(a["id"], {"start_balance": new_bal})
        if c3.button("Löschen", key=f"da{a['id']}"):
            store.delete_account(a["id"]); st.rerun()
    with st.form("aacc"):
        c1, c2, c3 = st.columns([2, 1, 1])
        nm = c1.text_input("Neues Konto")
        cu = c2.text_input("Währung", value="EUR")
        sb = c3.number_input("Startguthaben", value=0.0, format="%.2f", step=100.0)
        if st.form_submit_button("➕ Konto anlegen") and nm.strip():
            store.add_account(nm, cu, sb); st.rerun()

    st.divider()
    st.subheader("🎯 Risiko pro Setup (1 R)")
    st.caption("Trag pro Setup ein, was **1 R** in Euro bedeutet (z. B. Swing 500, News 200). "
               "Beim Trade wird das R-Multiple automatisch daraus berechnet, du kannst es pro Trade aber "
               "jederzeit ändern.")
    setups_all = store.get_list("setups") or []
    risk_map = store.get_risk_map()
    if not setups_all:
        st.info("Zuerst Setups anlegen — siehe Bereich weiter unten.")
    else:
        with st.form("risk_setup_form"):
            new_map = {}
            for s in setups_all:
                cA, cB = st.columns([2, 3])
                cA.markdown(f"**{s}**")
                v = cB.number_input(f"1 R für {s} (€)", value=float(risk_map.get(s, 0) or 0),
                                    step=50.0, format="%.2f", key=f"risk_{s}",
                                    label_visibility="collapsed")
                if v > 0:
                    new_map[s] = v
            if st.form_submit_button("💾 Risiko-Werte speichern"):
                store.set_risk_map(new_map)
                st.success("Gespeichert ✔")
                st.rerun()

    st.divider()
    st.subheader("💰 Ein-/Auszahlungen (aktives Konto)")
    st.caption("Beeinflusst den Kontostand, aber NICHT die Performance-Kurve. "
               "Einzahlung = positiver Betrag, Auszahlung = negativer Betrag (z. B. -500).")
    aid = acct_id()
    if aid:
        cfs = store.list_cashflows(aid)
        if cfs:
            for c in cfs:
                cc1, cc2, cc3, cc4 = st.columns([2, 2, 3, 1])
                cc1.write(str(c.get("dt") or "")[:10])
                amt = float(c.get("amount") or 0)
                cc2.markdown(f"<span style='color:{'#2FB67A' if amt >= 0 else '#E0635C'}'>{amt:,.2f}</span>",
                             unsafe_allow_html=True)
                cc3.write(c.get("note") or "")
                if cc4.button("🗑", key=f"cf{c['id']}"):
                    store.delete_cashflow(c["id"]); st.rerun()
        else:
            st.write("—")
        with st.form("acf"):
            f1, f2, f3 = st.columns([2, 2, 3])
            cf_dt = f1.date_input("Datum", value=date.today())
            cf_amt = f2.number_input("Betrag (+/−)", value=0.0, format="%.2f", step=100.0)
            cf_note = f3.text_input("Notiz (optional)")
            if st.form_submit_button("➕ Buchung hinzufügen") and cf_amt != 0:
                store.add_cashflow(aid, cf_dt.isoformat(), cf_amt, cf_note.strip() or None)
                st.rerun()

    st.divider()
    for label, key in [("Setups", "setups"), ("Fehler-Tags", "mistakes"), ("Regeln", "rules")]:
        st.subheader(label); items = store.get_list(key) or []
        st.write(" · ".join(items) if items else "—")
        c1, c2 = st.columns(2)
        nw = c1.text_input(f"Neu ({label})", key=f"n{key}")
        if c1.button("➕", key=f"a{key}") and nw.strip(): store.add_to_list(key, nw); st.rerun()
        rm = c2.selectbox(f"Entfernen ({label})", ["—"] + items, key=f"r{key}")
        if c2.button("➖", key=f"rb{key}") and rm != "—": store.remove_from_list(key, rm); st.rerun()
        st.divider()


# ======================================================================
#  Navigation
# ======================================================================
accts = store.list_accounts()

# WICHTIG: Merker eines vorherigen Klicks anwenden, BEVOR die Bedienelemente
# (Konto-Auswahl + Navigation) gebaut werden. Nur so laesst Streamlit die
# Aenderung von aktivem Konto / Seite zu.
if "pending_acct" in st.session_state:
    st.session_state["acct_id"] = st.session_state.pop("pending_acct")
if st.session_state.pop("go_dashboard", False):
    st.session_state["nav"] = "📊 Dashboard"
if st.session_state.pop("go_new", False):
    st.session_state["nav"] = "➕ Neuer Trade"

if "acct_id" not in st.session_state and accts:
    st.session_state["acct_id"] = accts[0]["id"]
if "nav" not in st.session_state:
    st.session_state["nav"] = "📊 Dashboard"

PAGES = {"📊 Dashboard": page_dashboard, "➕ Neuer Trade": page_new,
         "📋 Alle Trades": page_trades, "🧠 KI-Coach": page_coach, "⚙️ Einstellungen": page_settings}

# Falls noch ein alter Zustand (z.B. "Start") gespeichert ist: auf Dashboard zuruecksetzen
if st.session_state.get("nav") not in PAGES:
    st.session_state["nav"] = "📊 Dashboard"

st.sidebar.title("📈 Trading Journal")
if accts:
    ids = [a["id"] for a in accts]; names = {a["id"]: a["name"] for a in accts}
    st.sidebar.selectbox("Aktives Konto", ids, format_func=lambda i: names[i], key="acct_id")

st.sidebar.radio("Navigation", list(PAGES.keys()), key="nav")
st.sidebar.divider()
st.sidebar.caption("Daten in der EU · nur für dich")
if st.sidebar.button("Abmelden"):
    st.session_state.clear(); st.rerun()

_ = PAGES[st.session_state["nav"]]()
