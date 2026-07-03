"""
mt5_import.py — liest MetaTrader-5-Berichte (HTML oder CSV) und liefert
Trades als Liste von Dicts, passend fuer store.add_trade.

Doppel-Schutz (zweistufig, exakt statt geraten):
1) MT5-Ticketnummer: bereits importierte Tickets werden sicher uebersprungen.
2) Fuer Trades ohne Ticket (von Hand eingetragen): Kandidaten mit gleichem
   Symbol + gleichem Datum + P/L-Differenz <= 0.01 werden als "unsicher"
   markiert und dem Nutzer VOR dem Import angezeigt.
"""
import io
import re

import pandas as pd


def _num(x):
    """MT5 schreibt Zahlen mal mit Leerzeichen/Komma: '1 234,56' -> 1234.56"""
    if x is None:
        return None
    s = str(x).strip().replace("\xa0", "").replace(" ", "")
    if not s or s in {"-", "—"}:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _norm_symbol(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = str(s).strip().upper()
    return None if not s or s in {"NAN", "NONE"} else s


def _parse_frame(df):
    """Nimmt eine Tabelle mit MT5-Spalten und mappt sie auf unsere Felder."""
    cols = {str(c).strip().lower(): c for c in df.columns}

    def col(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None

    c_ticket = col("position", "ticket", "order", "deal")
    c_open = col("time", "open time", "opening time", "zeit", "eröffnungszeit")
    c_close = col("close time", "closing time", "time.1", "schlusszeit")
    c_sym = col("symbol", "symbol.1")
    c_type = col("type", "typ")
    c_lots = col("volume", "lots", "size", "volumen")
    c_entry = col("price", "open price", "eröffnungspreis")
    c_exit = col("price.1", "close price", "schlusskurs")
    c_sl = col("s/l", "sl", "stop loss")
    c_profit = col("profit", "gewinn")

    out = []
    for _, r in df.iterrows():
        sym = _norm_symbol(r.get(c_sym)) if c_sym else None
        profit = _num(r.get(c_profit)) if c_profit else None
        if not sym or profit is None:
            continue  # Kopf-/Summenzeilen ueberspringen
        typ = str(r.get(c_type) or "").strip().lower()
        if typ and typ not in {"buy", "sell", "kauf", "verkauf"}:
            continue  # balance/credit-Zeilen etc.
        direction = "Long" if typ in {"buy", "kauf"} else ("Short" if typ in {"sell", "verkauf"} else None)

        def _date_of(v):
            try:
                return pd.to_datetime(str(v), errors="coerce").date().isoformat()
            except Exception:
                return None

        opened = _date_of(r.get(c_open)) if c_open else None
        closed = _date_of(r.get(c_close)) if c_close else opened
        ticket = None
        if c_ticket is not None:
            tv = str(r.get(c_ticket) or "").strip()
            if tv.endswith(".0"):
                tv = tv[:-2]
            ticket = tv if tv and tv.lower() not in {"nan", "none"} else None

        out.append({
            "ticket": ticket,
            "symbol": sym,
            "direction": direction or "Long",
            "quantity": _num(r.get(c_lots)) if c_lots else None,
            "entry_price": _num(r.get(c_entry)) if c_entry else None,
            "exit_price": _num(r.get(c_exit)) if c_exit else None,
            "stop_price": _num(r.get(c_sl)) if c_sl else None,
            "pnl": profit,
            "opened_at": opened,
            "closed_at": closed,
        })
    return out


def parse_mt5(data: bytes, filename: str):
    """Liest MT5-Bericht (HTML/HTM oder CSV). Gibt Liste von Trade-Dicts zurueck."""
    name = (filename or "").lower()
    trades = []
    if name.endswith((".htm", ".html", ".xls")):  # MT5-"Excel"-Report ist oft HTML
        # thousands=None: Zahlen als Roh-Text lassen (sonst wird '236,70' zu 23670!)
        tables = pd.read_html(io.BytesIO(data), thousands=None)
        for t in tables:
            # flache Spaltennamen erzwingen
            t.columns = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
            got = _parse_frame(t)
            if got:
                trades.extend(got)
    elif name.endswith((".csv", ".txt")):
        for sep in (";", ",", "\t"):
            try:
                t = pd.read_csv(io.BytesIO(data), sep=sep)
                if len(t.columns) >= 5:
                    trades = _parse_frame(t)
                    if trades:
                        break
            except Exception:
                continue
    else:
        raise ValueError("Bitte einen MT5-Bericht als HTML/HTM oder CSV hochladen.")

    # Innerhalb der Datei selbst deduplizieren (gleiches Ticket doppelt)
    seen, unique = set(), []
    for t in trades:
        key = t.get("ticket") or f"{t['symbol']}|{t.get('closed_at')}|{t.get('pnl')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    return unique


def dedupe(new_trades, existing):
    """Teilt neue Trades in: frisch / sicher-doppelt / unsicher (Bestaetigung noetig)."""
    ex_tickets = {str(e.get("ticket")) for e in existing if e.get("ticket")}
    # Index fuer Fuzzy-Vergleich: (symbol, closed_at) -> [pnl, ...]
    ex_loose = {}
    for e in existing:
        k = (_norm_symbol(e.get("symbol")), str(e.get("closed_at") or "")[:10])
        ex_loose.setdefault(k, []).append(e.get("pnl"))

    fresh, dupes, unsure = [], [], []
    for t in new_trades:
        if t.get("ticket") and str(t["ticket"]) in ex_tickets:
            dupes.append(t)
            continue
        k = (t["symbol"], str(t.get("closed_at") or "")[:10])
        cand = ex_loose.get(k, [])
        close_match = any(p is not None and t.get("pnl") is not None and abs(float(p) - float(t["pnl"])) <= 0.01
                          for p in cand)
        (unsure if close_match else fresh).append(t)
    return fresh, dupes, unsure
