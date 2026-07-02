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

st.set_page_config(page_title="Trading Journal", page_icon="📈", layout="wide")

st.markdown("""<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
  html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] * { font-family:'Inter', sans-serif !important; }

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
store.seed_defaults()


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
    df["dt"] = pd.to_datetime(df.get("closed_at"), errors="coerce")
    if "created_at" in df:
        df["dt"] = df["dt"].fillna(pd.to_datetime(df["created_at"], errors="coerce"))
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

        c8, c9 = st.columns(2)
        pnl_manual = c8.number_input("Gewinn / Verlust in € (Minus = Verlust)",
                                     value=float(pv("pnl", 0.0)), format="%.2f", step=1.0, key=f"pn{prefix}",
                                     help="Trag hier einfach dein Ergebnis ein. Lässt du 0 stehen und füllst Entry/Exit/Lots aus, wird es automatisch berechnet.")
        closed_d = c9.date_input("Datum", value=date.today(), key=f"cd{prefix}")

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
            "pnl_r": None if is_open else compute_r(pnl, e, sp, q),
            "pips": None if is_open else compute_pips(sym, direction, e, x),
            "status": "offen" if is_open else "zu",
            "closed_at": closed_d.isoformat(), "setup": setup,
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
                d = str(o.get("closed_at") or "")[:10]
                parts.append(f"{o.get('symbol') or '—'}" + (f" (seit {d})" if d else ""))
            st.markdown(f'<div class="openbar">🟡 <b>{len(od)} offen:</b> ' + " · ".join(parts) + '</div>',
                        unsafe_allow_html=True)

    closed = df.dropna(subset=["pnl"]).copy() if not df.empty else pd.DataFrame()

    if closed.empty:
        # Übersicht auch ohne Trades anzeigen
        r = st.columns(4)
        kpi(r[0], "Kontostand", f"{start_bal:,.2f} {cur}", "gold")
        kpi(r[1], "Netto P/L", f"0.00 {cur}", "neutral")
        kpi(r[2], "Trefferquote", "0 %", "neutral")
        kpi(r[3], "Trades", "0", "neutral")
        st.info("Noch keine Trades mit Ergebnis. Zieh oben einen Screenshot rein oder geh auf **➕ Neuer Trade**.")
        return

    s = stats(closed)
    balance = start_bal + s["net"]
    net_tone = "pos" if s["net"] >= 0 else "neg"
    r0 = st.columns(4)
    kpi(r0[0], "Kontostand", f"{balance:,.2f} {cur}", "gold",
        sub=f"{'▲' if s['net'] >= 0 else '▼'} {s['net']:,.2f} {cur}")
    kpi(r0[1], "Netto P/L", f"{s['net']:,.2f} {cur}", net_tone)
    kpi(r0[2], "Trefferquote", f"{s['win_rate']:.0f} %", "neutral")
    kpi(r0[3], "Trades", f"{s['n']}", "neutral")
    r2 = st.columns(4)
    kpi(r2[0], "Gewinner / Verlierer", f"{s['wins']} / {s['losses']}", "neutral")
    kpi(r2[1], "Profit-Faktor", "∞" if s["pf"] == float("inf") else f"{s['pf']:.2f}", "neutral")
    kpi(r2[2], "Ø R", "—" if s["avg_r"] is None or pd.isna(s["avg_r"]) else f"{s['avg_r']:.2f} R", "neutral")
    kpi(r2[3], "Max. Drawdown", f"{s['max_dd']:,.2f} {cur}", "neg" if s["max_dd"] < 0 else "neutral")

    st.divider()
    col_eq, col_donut = st.columns([2, 1])
    with col_eq:
        st.subheader("Verlauf (Equity-Kurve)")
        eq = closed.sort_values("dt").reset_index(drop=True).copy()
        eq["kumuliert"] = eq["pnl"].cumsum()
        eq["Trade"] = range(1, len(eq) + 1)
        up = eq["kumuliert"].iloc[-1] >= 0
        col = "#2FB67A" if up else "#E0635C"
        base = alt.Chart(eq).encode(
            x=alt.X("Trade:Q", title=None),
            y=alt.Y("kumuliert:Q", title=None))
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

    def signed_bars(data, label_col, title):
        d = data.reset_index()
        d.columns = [label_col, "pnl"]
        d["farbe"] = d["pnl"].apply(lambda v: "Gewinn" if v >= 0 else "Verlust")
        ch = alt.Chart(d).mark_bar().encode(
            x=alt.X(f"{label_col}:N", title=None, sort=None),
            y=alt.Y("pnl:Q", title=None),
            color=alt.Color("farbe:N",
                            scale=alt.Scale(domain=["Gewinn", "Verlust"], range=["#2FB67A", "#E0635C"]),
                            legend=None)).properties(height=260)
        st.altair_chart(ch, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("P/L nach Setup")
        bs = closed.groupby("setup")["pnl"].sum().sort_values(ascending=False)
        if not bs.empty: signed_bars(bs, "Setup", "Setup")
    with c2:
        st.subheader("P/L nach Wochentag")
        names = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
        t = closed.dropna(subset=["dt"]).copy()
        if not t.empty:
            t["wd"] = t["dt"].dt.weekday.map(lambda i: names[i])
            wk = t.groupby("wd")["pnl"].sum().reindex(names).dropna()
            if not wk.empty: signed_bars(wk, "Wochentag", "Wochentag")

    st.subheader("Häufigste Fehler")
    allm = [m for lst in closed["mistakes"] if isinstance(lst, list) for m in lst]
    if allm:
        st.bar_chart(pd.Series(allm).value_counts())
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


def page_trades():
    st.title("📋 Alle Trades")
    rows = store.list_trades(acct_id())
    if not rows:
        st.info("Noch keine Trades."); return
    df = pd.DataFrame(rows)
    if "status" in df:
        df["Status"] = df["status"].map(lambda s: "🟡 läuft" if s == "offen" else "✅ zu")
    else:
        df["Status"] = "✅ zu"
    cols = [c for c in ["id", "closed_at", "symbol", "direction", "setup", "Status", "pnl", "pips", "pnl_r", "rating"] if c in df]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)
    st.divider()
    sel = st.selectbox("Trade öffnen", [r["id"] for r in rows], format_func=lambda i: f"#{i}")
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
        st.write(f"**{t.get('symbol')}** · {t.get('direction')} · {t.get('setup')} · {badge}  \n"
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
                    "pnl": None if will_open else new_pnl,
                    "pnl_r": None if will_open else compute_r(new_pnl, ce or None, cstop or None, cq or None),
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
        n = st.slider("Letzte … Trades", 3, max(3, len(rows)), min(20, len(rows)))
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
