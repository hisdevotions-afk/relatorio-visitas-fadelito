#!/usr/bin/env python3
"""Extrai TODOS os atendimentos do SDR Roberto na Tallos e decifra as conversas.

Gera uma base de conhecimento (RAG) com o histórico real de atendimento do Roberto,
no maior intervalo de datas possível.

Fluxo (resumível — pode rodar de novo que retoma de onde parou):
  Fase 1  /v4/reports?employee=<Roberto>  → atendimentos.jsonl  (metadados)
  Fase 2  /v2/messages/history?customer_id=<cid>  → conversas/<cid>.json (decifrado)
  Fase 3  monta roberto_rag.jsonl + roberto_transcripts.txt (prontos p/ RAG)

Saídas em tallos_export/.
"""
import datetime as dt
import json
import os
import sys
import time

import requests
from jwcrypto import jwe, jwk

# ---------------------------------------------------------------- config
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbXBsb3llZSI6IjY0OWIzNWZlZDA5ZTZmMDAxMWM3NGZjMSIsImNvbXBhbnkiOiI2NDdlMTBlMTVjMTc3NTc2ZmY1ODUxYTQiLCJpYXQiOjE3Nzg2MDk4ODR9.5KNul4mde4jkhIjUpR9rFjnAftcLYqLuvalyGQzXaKE"
ROBERTO_ID = "649b35fed09e6f0011c74fc1"
JWK_PATH = "/home/usuario/Downloads/fadelito-crm/backend/.keys/rd_messages_oC5C2OBT.jwk"
BASE = "https://api.tallos.com.br"

DATE_START = dt.date(2023, 4, 1)    # primeiro atendimento do Roberto ~jun/2023
DATE_END = dt.date.today()
WINDOW_DAYS = 89                    # API limita intervalo a 90 dias
PAGE_LIMIT = 50                     # máximo aceito por página
SLEEP = 0.15                        # gentileza entre chamadas

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tallos_export")
DIR_CONV = os.path.join(OUT, "conversas")
F_ATEND = os.path.join(OUT, "atendimentos.jsonl")
F_RAG = os.path.join(OUT, "roberto_rag.jsonl")
F_TXT = os.path.join(OUT, "roberto_transcripts.txt")
F_LOG = os.path.join(OUT, "extracao.log")

HEADERS = {"Authorization": f"Bearer {TOKEN}"}
SESS = requests.Session()
SESS.headers.update(HEADERS)
ROLE = {"customer": "LEAD", "operator": "SDR", "bot": "BOT"}


def log(msg: str) -> None:
    line = f"{dt.datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    with open(F_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get(url: str, params: dict, tries: int = 6) -> dict:
    for i in range(tries):
        try:
            r = SESS.get(url, params=params, timeout=60)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                wait = min(2 ** i, 30)
                log(f"  HTTP {r.status_code}, retry em {wait}s ({url})")
                time.sleep(wait)
                continue
            log(f"  HTTP {r.status_code} inesperado: {r.text[:160]}")
            return {}
        except requests.RequestException as e:
            wait = min(2 ** i, 30)
            log(f"  erro de rede ({e}), retry em {wait}s")
            time.sleep(wait)
    return {}


# ---------------------------------------------------------------- fase 1
def windows():
    s = DATE_START
    while s <= DATE_END:
        e = min(s + dt.timedelta(days=WINDOW_DAYS), DATE_END)
        yield s, e
        s = e + dt.timedelta(days=1)


def fase1_reports() -> None:
    seen = set()
    if os.path.exists(F_ATEND):
        with open(F_ATEND, encoding="utf-8") as f:
            for ln in f:
                try:
                    seen.add(json.loads(ln)["id"])
                except Exception:
                    pass
        log(f"FASE 1: retomando — {len(seen)} atendimentos já salvos")

    fout = open(F_ATEND, "a", encoding="utf-8")
    for ws, we in windows():
        page, pages = 1, 1
        win_new = 0
        while page <= pages:
            d = get(f"{BASE}/v4/reports", {
                "start_date": ws.isoformat(), "end_date": we.isoformat(),
                "employee": ROBERTO_ID, "limit": PAGE_LIMIT, "page": page,
            })
            if not d:
                break
            pages = d.get("pages", 1)
            for doc in d.get("docs", []):
                if doc.get("id") in seen:
                    continue
                seen.add(doc["id"])
                fout.write(json.dumps(doc, ensure_ascii=False) + "\n")
                win_new += 1
            fout.flush()
            page += 1
            time.sleep(SLEEP)
        log(f"FASE 1: {ws}..{we} -> +{win_new} (total {len(seen)})")
    fout.close()
    log(f"FASE 1 concluída: {len(seen)} atendimentos do Roberto")


# ---------------------------------------------------------------- fase 2
def load_key() -> jwk.JWK:
    return jwk.JWK.from_json(open(JWK_PATH, encoding="utf-8").read())


def decrypt(token: str, key: jwk.JWK) -> list:
    t = jwe.JWE()
    t.deserialize(token, key=key)
    raw = t.payload
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    data = json.loads(text, strict=False)
    return data if isinstance(data, list) else []


def fetch_history(cid: str, key: jwk.JWK) -> list:
    """Busca o histórico COMPLETO de um contato via paginação.

    A API trunca silenciosamente com limit alto (limit=2000 devolve só 15!), então
    paginamos com limit=100 até a última página. Deduplica por (created_at, content).
    """
    PAGE = 100
    vistos = set()
    todas: list = []
    page = 1
    while page <= 80:  # teto de segurança: 8000 msgs
        d = get(f"{BASE}/v2/messages/history", {
            "customer_id": cid, "limit": PAGE, "page": page, "channel": ["whatsapp"],
            "sent_by": ["customer", "operator", "bot"], "type": ["text"],
        })
        token = (d or {}).get("messages", "")
        if not token:
            break
        try:
            msgs = decrypt(token, key)
        except Exception as e:
            log(f"  decrypt falhou cid={cid} page={page}: {e}")
            break
        novos = 0
        for m in msgs:
            k = (m.get("created_at"), m.get("content"))
            if k in vistos:
                continue
            vistos.add(k)
            todas.append(m)
            novos += 1
        if len(msgs) < PAGE or novos == 0:
            break
        page += 1
        time.sleep(SLEEP)
    return todas


def fase2_conversas() -> None:
    os.makedirs(DIR_CONV, exist_ok=True)
    key = load_key()

    # mapa customer_id -> (dados do contato, data do atendimento mais recente)
    # A Tallos só retém o texto das conversas por ~1 mês, então processamos os
    # contatos do mais RECENTE para o mais antigo: o conteúdo útil é capturado já
    # no começo, e as conversas antigas (quase todas vazias) ficam por último.
    contatos: dict[str, dict] = {}
    ultima: dict[str, str] = {}
    with open(F_ATEND, encoding="utf-8") as f:
        for ln in f:
            doc = json.loads(ln)
            cid = (doc.get("customer") or {}).get("id")
            if not cid:
                continue
            contatos[cid] = doc.get("customer") or {}
            d = doc.get("started_at", "") or ""
            if d > ultima.get(cid, ""):
                ultima[cid] = d
    ordem = sorted(contatos, key=lambda c: ultima.get(c, ""), reverse=True)
    log(f"FASE 2: {len(contatos)} contatos únicos a decifrar (mais recentes primeiro)")

    done = {fn[:-5] for fn in os.listdir(DIR_CONV) if fn.endswith(".json")}
    log(f"FASE 2: {len(done)} conversas já decifradas")

    n = 0
    for cid in ordem:
        n += 1
        if cid in done:
            continue
        msgs = fetch_history(cid, key)
        msgs.sort(key=lambda m: m.get("created_at") or "")
        with open(os.path.join(DIR_CONV, f"{cid}.json"), "w", encoding="utf-8") as fo:
            json.dump({"customer_id": cid, "customer": contatos[cid], "messages": msgs},
                      fo, ensure_ascii=False)
        if n % 50 == 0:
            log(f"FASE 2: {n}/{len(contatos)} (cid atual {len(msgs)} msgs)")
        time.sleep(SLEEP)
    log("FASE 2 concluída")


# ---------------------------------------------------------------- fase 3
def unidade_de_tags(tags: list) -> str:
    nomes = [t.get("name", "") for t in (tags or [])]
    return ", ".join(nomes)


def fase3_rag() -> None:
    # carrega atendimentos agrupados por customer_id
    atend_por_cid: dict[str, list] = {}
    with open(F_ATEND, encoding="utf-8") as f:
        for ln in f:
            doc = json.loads(ln)
            cid = (doc.get("customer") or {}).get("id")
            if cid:
                atend_por_cid.setdefault(cid, []).append(doc)

    n_rag = 0
    n_msgs = 0
    with open(F_RAG, "w", encoding="utf-8") as frag, open(F_TXT, "w", encoding="utf-8") as ftxt:
        for fn in sorted(os.listdir(DIR_CONV)):
            if not fn.endswith(".json"):
                continue
            conv = json.load(open(os.path.join(DIR_CONV, fn), encoding="utf-8"))
            cid = conv["customer_id"]
            msgs = conv.get("messages", [])
            if not msgs:
                continue
            cust = conv.get("customer", {})
            atends = atend_por_cid.get(cid, [])
            # protocolos/datas/unidades de TODOS os atendimentos do Roberto c/ esse contato
            protocolos = [a.get("protocol") for a in atends]
            unidades = sorted({unidade_de_tags(a.get("customer", {}).get("tags", [])) for a in atends})
            datas = sorted(a.get("started_at", "") for a in atends if a.get("started_at"))

            # só inclui conversas onde o Roberto (operator) realmente participou
            tem_sdr = any(m.get("sent_by") == "operator" for m in msgs)
            if not tem_sdr:
                continue

            linhas = []
            for m in msgs:
                content = (m.get("content") or "").strip()
                if not content:
                    continue
                role = ROLE.get(m.get("sent_by", ""), (m.get("sent_by") or "?").upper())
                # limpa lixo de encoding (caracteres de controle e substitution)
                content = content.replace("\r", " ").replace("\n", " ")
                content = "".join(c if c >= " " or c == "\t" else " " for c in content)
                content = content.strip()
                if not content:
                    continue
                linhas.append(f"[{role}] {content}")
            if not linhas:
                continue
            transcript = "\n".join(linhas)
            n_msgs += len(linhas)

            rec = {
                "customer_id": cid,
                "lead_nome": cust.get("full_name"),
                "telefone": cust.get("cel_phone"),
                "unidades_tags": unidades,
                "qtd_atendimentos": len(atends),
                "protocolos": protocolos,
                "primeira_data": datas[0] if datas else None,
                "ultima_data": datas[-1] if datas else None,
                "qtd_mensagens": len(linhas),
                "transcript": transcript,
            }
            frag.write(json.dumps(rec, ensure_ascii=False) + "\n")

            ftxt.write("=" * 80 + "\n")
            ftxt.write(f"Lead: {cust.get('full_name')} | Unidade/tags: {', '.join(unidades)}\n")
            ftxt.write(f"Protocolos: {', '.join(str(p) for p in protocolos)} | "
                       f"Período: {rec['primeira_data']} .. {rec['ultima_data']}\n")
            ftxt.write("-" * 80 + "\n")
            ftxt.write(transcript + "\n\n")
            n_rag += 1

    log(f"FASE 3 concluída: {n_rag} conversas, {n_msgs} mensagens -> {F_RAG}")


# ---------------------------------------------------------------- main
if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    phases = sys.argv[1:] or ["1", "2", "3"]
    log(f"=== INÍCIO extração (fases {phases}) ===")
    if "1" in phases:
        fase1_reports()
    if "2" in phases:
        fase2_conversas()
    if "3" in phases:
        fase3_rag()
    log("=== FIM ===")
