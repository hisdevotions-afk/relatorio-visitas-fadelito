#!/usr/bin/env python3
"""Provisiona credenciais + workflows na n8n de PRODUÇÃO via REST API pública.

A API pública gera IDs próprios (não respeita os IDs fixos do import por CLI), então:
1) cria as credenciais e captura os IDs gerados (por nome);
2) cria os sub-workflows (tools) e captura seus IDs;
3) injeta os IDs de credencial e de sub-workflow nos nós do workflow principal;
4) cria o workflow principal.

Uso: API_KEY=... python3 _provision_api.py
"""
import json
import os
import sys
import urllib.request
import urllib.error

BASE = "https://n8n.fadelito.com.br/api/v1"
KEY = os.environ["API_KEY"]
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AG = os.path.join(ROOT, "agente_reagendamento")


def env(path):
    d = {}
    for ln in open(path):
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            d[k.strip()] = v.strip()
    return d


E = env(os.path.join(AG, ".env"))
GC = json.load(open(os.path.join(ROOT, "google_credentials.json")))


def api(method, path, payload=None):
    url = BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-N8N-API-KEY", KEY)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    # Cloudflare bane o UA padrão do urllib (erro 1010) — usar UA de navegador.
    req.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                 "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


# ── 1) credenciais ────────────────────────────────────────────────────────────
CRED_DEFS = [
    ("Fadelito NVIDIA NIM", "nvidiaApi",
     {"url": "https://integrate.api.nvidia.com/v1", "apiKey": E["NVIDIA_API_KEY"]}),
    ("Fadelito Groq", "groqApi", {"apiKey": E["GROQ_API_KEY"]}),
    ("Fadelito Gupshup (apikey)", "httpHeaderAuth",
     {"name": "apikey", "value": E["WHATSAPP_API_TOKEN"]}),
    ("Fadelito Gendo (Bearer)", "httpHeaderAuth",
     {"name": "Authorization", "value": "Bearer " + E["API_TOKEN"]}),
    ("Fadelito Google Service Account", "googleApi",
     {"region": "", "email": GC["client_email"], "privateKey": GC["private_key"],
      "inpersonate": False, "delegatedEmail": ""}),
]

cred_id_by_name = {}   # nome -> id novo
print("== Credenciais ==")
for name, ctype, data in CRED_DEFS:
    st, resp = api("POST", "/credentials", {"name": name, "type": ctype, "data": data})
    if st in (200, 201) and resp.get("id"):
        cred_id_by_name[name] = resp["id"]
        print(f"  ok  {name} -> {resp['id']}")
    else:
        print(f"  ERRO {name}: HTTP {st} {resp}")
        sys.exit(1)


def fix_creds(nodes):
    """Troca os IDs de credencial (que vieram por nome fixo) pelos IDs reais."""
    for n in nodes:
        for ct, cv in (n.get("credentials") or {}).items():
            nm = cv.get("name")
            if nm in cred_id_by_name:
                cv["id"] = cred_id_by_name[nm]


def clean_payload(wf):
    """Mantém só os campos aceitos pelo POST /workflows."""
    return {
        "name": wf["name"],
        "nodes": wf["nodes"],
        "connections": wf["connections"],
        "settings": wf.get("settings", {"executionOrder": "v1"}),
    }


def create_workflow(filename):
    wf = json.load(open(os.path.join(HERE, filename)))
    fix_creds(wf["nodes"])
    st, resp = api("POST", "/workflows", clean_payload(wf))
    if st in (200, 201) and resp.get("id"):
        print(f"  ok  {wf['name']} -> {resp['id']}")
        return resp["id"]
    print(f"  ERRO {wf['name']}: HTTP {st} {json.dumps(resp)[:300]}")
    sys.exit(1)


# ── 2) sub-workflows (tools) ──────────────────────────────────────────────────
print("== Sub-workflows (tools) ==")
id_confirmar = create_workflow("tool_confirmar_agendamento.json")
id_consultar = create_workflow("tool_consultar_horarios.json")

# ── 3) workflow principal (com RAG) — injeta IDs de tool + credenciais ────────
print("== Workflow principal ==")
main = json.load(open(os.path.join(HERE, "agente_reativo.withrag.json")))
fix_creds(main["nodes"])
for n in main["nodes"]:
    if n.get("type", "").endswith("toolWorkflow"):
        wid = n["parameters"].get("workflowId", {})
        if n["name"] == "confirmar_agendamento":
            wid["value"] = id_confirmar
        elif n["name"] == "consultar_horarios":
            wid["value"] = id_consultar
st, resp = api("POST", "/workflows", clean_payload(main))
if st in (200, 201) and resp.get("id"):
    print(f"  ok  {main['name']} -> {resp['id']}")
else:
    print(f"  ERRO principal: HTTP {st} {json.dumps(resp)[:400]}")
    sys.exit(1)

print("\nConcluído. Workflows criados INATIVOS em https://n8n.fadelito.com.br")
