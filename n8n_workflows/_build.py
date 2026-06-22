#!/usr/bin/env python3
"""Gera os JSON dos workflows n8n do agente de reagendamento Fadelito.

Saídas (na mesma pasta):
  - tool_confirmar_agendamento.json   (sub-workflow usado como tool pelo agente)
  - agente_reativo.json               (workflow principal: webhook -> agente -> WhatsApp)
  - credentials.json                  (credenciais p/ `n8n import:credentials`)

Os tipos/versões de nós foram extraídos da instalação local do n8n 2.26.8.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AG = os.path.join(ROOT, "agente_reagendamento")

# ── lê config do .env do agente ───────────────────────────────────────────────
def env(path):
    d = {}
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            d[k.strip()] = v.strip()
    return d

E = env(os.path.join(AG, ".env"))
GENDO_BASE = E["API_BASE_URL"]
SHEET_ID = E["GOOGLE_SHEETS_ID"]
SRC_NUM = E["WHATSAPP_SOURCE_NUMBER"]
APP_NAME = E["WHATSAPP_APP_NAME"]
SDR_NUM = E["WHATSAPP_SDR_NUMBER"]
TESTE_NUM = E.get("WHATSAPP_TESTE_NUMBER", "")
DATA_OVERRIDE = E.get("DATA_OVERRIDE", "")

# IDs determinísticos das credenciais (idem credentials.json)
CRED = {
    "nvidia":  {"id": "fadelitoNvidiaApi", "name": "Fadelito NVIDIA NIM"},
    "groq":    {"id": "fadelitoGroqApi",   "name": "Fadelito Groq"},
    "gupshup": {"id": "fadelitoGupshup",   "name": "Fadelito Gupshup (apikey)"},
    "gendo":   {"id": "fadelitoGendo",     "name": "Fadelito Gendo (Bearer)"},
    "google":  {"id": "fadelitoGoogle",    "name": "Fadelito Google Service Account"},
}
SUBWF_ID = "fadelitoToolConfirmar"       # sub-workflow tool: confirmar_agendamento
SUBWF_HORARIOS_ID = "fadelitoToolHorarios"  # sub-workflow tool: consultar_horarios

# ── RAG: importa a base COMPLETA do agente Python (rag.py) ─────────────────────
# Em vez de uma versão condensada à mão, usamos exatamente o KNOWLEDGE_BASE do
# rag.py (regras, endereços de TODAS as unidades, Maps, turmas, financeiro,
# modelos de resposta, handoff) e os exemplos reais do Roberto.
import sys as _sys
_sys.path.insert(0, AG)
import rag as _rag  # noqa: E402

PERSONA = (
    "Você é o agente de reagendamento de visitas da rede de escolas infantis Fadelito. "
    "Responda SEMPRE em português brasileiro informal, estilo WhatsApp: frases curtas, "
    "humano, empático, sem pressão. Emojis: evite no corpo; em saudação/despedida até 2 são ok.\n\n"
)

# Instruções operacionais específicas do agente em n8n (tools, slots, fluxo)
OPERACAO = """
=== COMO AGIR (n8n) ===
- Os ÚNICOS horários que você pode oferecer são os de "HORÁRIOS DISPONÍVEIS REAIS" abaixo. NUNCA invente outros.
- Cada slot vem rotulado com [data=YYYY-MM-DD horario=HH:MM]. Ao confirmar, use ESSES valores exatos.
- Quando o lead escolher um horário (por número, "o primeiro", ou dizendo data/hora), chame a tool
  confirmar_agendamento(lead_id, data, horario). Só dê a visita como confirmada DEPOIS que a tool retornar sucesso.
- Se o lead pedir OUTRA unidade: descubra qual e chame a tool consultar_horarios(unidade) para obter os
  horários REAIS daquela unidade; então ofereça-os e siga o mesmo fluxo de confirmação. Use o endereço da
  unidade conforme a lista de endereços da base (nunca invente endereço).
- Mantenha o foco em reagendar. Respostas curtas, no máximo ~4 linhas.
"""

KB_BASE = PERSONA + _rag.KNOWLEDGE_BASE + OPERACAO
EXEMPLOS_ROBERTO = _rag.get_exemplos_roberto(seed=42)  # PII — só na versão .withrag

# ── JS: parse do webhook Gupshup/Meta ─────────────────────────────────────────
JS_PARSE = r"""
// Parseia o webhook do Gupshup (formato Meta Cloud API) e o legado de simulação.
const raw = $input.first().json;
const payload = raw.body ?? raw;

function norm(t) {
  let d = String(t || '').replace(/\D/g, '');
  if (d && !d.startsWith('55')) d = '55' + d;
  return d;
}

const out = [];
if (payload.entry) {
  for (const e of payload.entry || []) {
    for (const c of e.changes || []) {
      if (c.field !== 'messages') continue;
      for (const m of (c.value && c.value.messages) || []) {
        if (m.type !== 'text') continue;
        const text = (m.text && m.text.body) || '';
        if (!text) continue;
        out.push({ from: norm(m.from), text, message_id: m.id || '' });
      }
    }
  }
} else if (payload.type === 'message') {
  const inner = payload.payload || {};
  if (inner.type === 'text') {
    const text = (inner.payload && inner.payload.text) || '';
    if (text) out.push({ from: norm(inner.source), text, message_id: inner.id || '' });
  }
}
// Sem mensagem de texto (ex.: evento de status) => não segue o fluxo.
return out.map((o) => ({ json: o }));
"""

# ── JS: localizar o lead na aba lida do Sheets (normalizando telefone) ─────────
JS_BUSCAR = r"""
// Encontra a linha do lead pelo telefone (normalizado dos dois lados), como no Python.
const msg = $('Parse Gupshup').item.json;
function norm(t) {
  let d = String(t || '').replace(/\D/g, '');
  if (d && !d.startsWith('55')) d = '55' + d;
  return d;
}
const alvo = norm(msg.from);
const linhas = $input.all().map((i) => i.json);
const lead = linhas.find((l) => norm(l['Telefone']) === alvo);
if (!lead) {
  // número desconhecido: encerra sem responder
  return [];
}
return [{
  json: {
    from: msg.from,
    text: msg.text,
    message_id: msg.message_id,
    row_number: lead.row_number,
    id: lead['ID'] || '',
    nome: lead['Nome'] || '',
    unidade: (lead['unidade_alvo'] || lead['Unidade'] || '').trim(),
    unidade_original: lead['Unidade'] || '',
    data_hora: lead['Data/Hora'] || '',
    status: lead['Status'] || '',
    status_agente: lead['status_agente'] || '',
  },
}];
"""

# ── JS: janela de dias úteis (porta de disponibilidade.py) ────────────────────
JS_JANELA = r"""
// Próximos 5 dias úteis (sem fim de semana e feriados nacionais) + grade de horários.
// Espelha disponibilidade.py (_proximos_dias_uteis, _gerar_slots_do_dia, feriados).
const SLOT_INICIO = '__SLOT_INI__';
const SLOT_FIM = '__SLOT_FIM__';
const DURACAO = __DURACAO__;

function pascoa(ano) {
  const a = ano % 19, b = Math.floor(ano / 100), c = ano % 100;
  const d = Math.floor(b / 4), e = b % 4, f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4), k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7;
  const m = Math.floor((a + 11 * h + 22 * l) / 451);
  const mes = Math.floor((h + l - 7 * m + 114) / 31);
  const dia = ((h + l - 7 * m + 114) % 31) + 1;
  return new Date(Date.UTC(ano, mes - 1, dia));
}
function feriados(ano) {
  const fix = [[1,1],[21,4],[1,5],[7,9],[12,10],[2,11],[15,11],[25,12]];
  const s = new Set(fix.map(([d, m]) => `${ano}-${m}-${d}`));
  const p = pascoa(ano);
  const add = (off) => { const x = new Date(p); x.setUTCDate(x.getUTCDate() + off);
    s.add(`${x.getUTCFullYear()}-${x.getUTCMonth() + 1}-${x.getUTCDate()}`); };
  [-48, -47, -2, 60].forEach(add);
  return s;
}
function isFeriado(dt) {
  return feriados(dt.getUTCFullYear()).has(`${dt.getUTCFullYear()}-${dt.getUTCMonth() + 1}-${dt.getUTCDate()}`);
}
function slotsDoDia() {
  const [hi, mi] = SLOT_INICIO.split(':').map(Number);
  const [hf, mf] = SLOT_FIM.split(':').map(Number);
  let a = hi * 60 + mi; const fim = hf * 60 + mf; const r = [];
  while (a <= fim) { r.push(`${String(Math.floor(a / 60)).padStart(2,'0')}:${String(a % 60).padStart(2,'0')}`); a += DURACAO; }
  return r;
}
const DIAS_PT = ['domingo','segunda-feira','terça-feira','quarta-feira','quinta-feira','sexta-feira','sábado'];
const dias = [];
let d = new Date(); d.setUTCHours(0,0,0,0); d.setUTCDate(d.getUTCDate() + 1);
while (dias.length < 5) {
  const wd = d.getUTCDay();
  if (wd >= 1 && wd <= 5 && !isFeriado(d)) {
    const iso = `${d.getUTCFullYear()}-${String(d.getUTCMonth()+1).padStart(2,'0')}-${String(d.getUTCDate()).padStart(2,'0')}`;
    dias.push({ iso, dia_semana: DIAS_PT[wd], dd: String(d.getUTCDate()).padStart(2,'0'), mm: String(d.getUTCMonth()+1).padStart(2,'0') });
  }
  d.setUTCDate(d.getUTCDate() + 1);
}
return [{ json: {
  inicio: dias[0].iso,
  fim: dias[dias.length - 1].iso,
  dias,
  slot_times: slotsDoDia(),
  unidade: __UNIDADE_EXPR__,
} }];
""".replace("__SLOT_INI__", E.get("SLOT_INICIO", "09:00")) \
   .replace("__SLOT_FIM__", E.get("SLOT_FIM", "16:30")) \
   .replace("__DURACAO__", str(int(E.get("VISITA_DURACAO_MINUTOS", "60"))))

def js_janela(unidade_expr):
    """JS_JANELA com a origem da unidade parametrizada (lead vs. input da tool)."""
    return JS_JANELA.replace("__UNIDADE_EXPR__", unidade_expr)

# ── JS: calcula slots livres (porta de _horarios_ocupados/get_slots_disponiveis) ─
JS_SLOTS = r"""
// Cruza a grade de horários com os agendamentos reais do Gendo p/ a unidade.
// Espelha disponibilidade.py (filtro de unidade bidirecional + status ocupados).
const janela = $('Janela Dias Uteis').item.json;
const resp = $input.first().json;
const agendamentos = Array.isArray(resp) ? resp : (resp.data || resp.body?.data || []);

const STATUS_OCUPADOS = new Set(['0', '1', '2', '6']); // 0 = bloqueado/indisponível
function normU(s) {
  return String(s || '')
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase().replace(/fadelito/g, '').replace(/v\./g, 'vila').trim()
    .replace(/\s+/g, ' ');
}
const alvo = normU(janela.unidade);

function ocupadosDoDia(iso) {
  const occ = new Set();
  for (const a of agendamentos) {
    const start = a.start || '';
    if (!start.startsWith(iso)) continue;
    if (alvo) {
      const at = normU(a.atendente);
      if (!at) continue;
      if (!at.includes(alvo) && !alvo.includes(at)) continue;
    }
    const hora = start.slice(11, 16);
    if (!hora) continue;
    const st = String(a.status_agendamento ?? '');
    const serv = a.servico;
    if (STATUS_OCUPADOS.has(st) || serv === null || serv === undefined || serv === '') occ.add(hora);
  }
  return occ;
}

const livres = [];
for (const dia of janela.dias) {
  const occ = ocupadosDoDia(dia.iso);
  for (const h of janela.slot_times) {
    if (!occ.has(h)) {
      livres.push({ data: dia.iso, horario: h, label: `${dia.dia_semana}, ${dia.dd}/${dia.mm} às ${h.slice(0,2)}h` });
    }
  }
}
const slots = livres.slice(0, 6);
const texto = slots.length
  ? slots.map((s, i) => `${i + 1}) ${s.label}  [data=${s.data} horario=${s.horario}]`).join('\n')
  : '(sem horários livres nos próximos dias úteis)';
return [{ json: { slots, slots_texto: texto, total: slots.length } }];
"""

# ── helpers de construção de nós ──────────────────────────────────────────────
def node(name, ntype, ver, pos, params, **extra):
    n = {
        "parameters": params,
        "id": name.lower().replace(" ", "-"),
        "name": name,
        "type": ntype,
        "typeVersion": ver,
        "position": pos,
    }
    n.update(extra)
    return n

def cred(key):
    return {CRED[key]["name"].split()[0].lower(): {"id": CRED[key]["id"], "name": CRED[key]["name"]}}

def cred_named(credtype, key):
    return {credtype: {"id": CRED[key]["id"], "name": CRED[key]["name"]}}

# =============================================================================
# SUB-WORKFLOW (tool): confirmar_agendamento
# =============================================================================
sub_nodes = [
    node("Quando Executado pelo Agente", "n8n-nodes-base.executeWorkflowTrigger", 1.1, [0, 0], {
        "inputSource": "workflowInputs",
        "workflowInputs": {"values": [
            {"name": "lead_id", "type": "string"},
            {"name": "data", "type": "string"},
            {"name": "horario", "type": "string"},
        ]},
    }),
    node("Dados do Agendamento", "n8n-nodes-base.httpRequest", 4.4, [240, 0], {
        "method": "GET",
        "url": f"={GENDO_BASE}/agendamento-dados/{{{{ $json.lead_id }}}}",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "options": {},
    }, credentials=cred_named("httpHeaderAuth", "gendo")),
    node("Criar Agendamento", "n8n-nodes-base.httpRequest", 4.4, [480, 0], {
        "method": "POST",
        "url": f"{GENDO_BASE}/agendamento",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "contentType": "multipart-form-data",
        "bodyParameters": {"parameters": [
            {"name": "id_paciente", "value": "={{ $json.data?.id_paciente ?? $json.data?.paciente_id ?? $json.id_paciente ?? $json.paciente_id }}"},
            {"name": "id_responsavel", "value": "={{ $json.data?.id_responsavel ?? $json.data?.responsavel_id ?? $json.id_responsavel ?? $json.responsavel_id }}"},
            {"name": "id_servico", "value": "={{ $json.data?.id_servico ?? $json.data?.servico_id ?? $json.id_servico ?? $json.servico_id }}"},
            {"name": "data", "value": "={{ $('Quando Executado pelo Agente').item.json.data }}"},
            {"name": "horario", "value": "={{ $('Quando Executado pelo Agente').item.json.horario }}"},
            {"name": "tempo", "value": str(int(E.get('VISITA_DURACAO_MINUTOS','60')))},
            {"name": "status", "value": "1"},
        ]},
        "options": {},
    }, credentials=cred_named("httpHeaderAuth", "gendo")),
    node("Cancelar Antigo", "n8n-nodes-base.httpRequest", 4.4, [720, 0], {
        "method": "POST",
        "url": f"{GENDO_BASE}/agendamento-status",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "contentType": "multipart-form-data",
        "bodyParameters": {"parameters": [
            {"name": "id", "value": "={{ $('Quando Executado pelo Agente').item.json.lead_id }}"},
            {"name": "status", "value": "7"},
        ]},
        "options": {},
    }, credentials=cred_named("httpHeaderAuth", "gendo")),
    node("Resultado", "n8n-nodes-base.set", 3.4, [960, 0], {
        "assignments": {"assignments": [
            {"id": "r1", "name": "sucesso", "value": True, "type": "boolean"},
            {"id": "r2", "name": "mensagem",
             "value": "={{ 'Agendamento confirmado no Gendo para ' + $('Quando Executado pelo Agente').item.json.data + ' às ' + $('Quando Executado pelo Agente').item.json.horario }}",
             "type": "string"},
        ]},
        "options": {},
    }),
]
sub_conn = {
    "Quando Executado pelo Agente": {"main": [[{"node": "Dados do Agendamento", "type": "main", "index": 0}]]},
    "Dados do Agendamento": {"main": [[{"node": "Criar Agendamento", "type": "main", "index": 0}]]},
    "Criar Agendamento": {"main": [[{"node": "Cancelar Antigo", "type": "main", "index": 0}]]},
    "Cancelar Antigo": {"main": [[{"node": "Resultado", "type": "main", "index": 0}]]},
}
sub_wf = {
    "id": SUBWF_ID,
    "name": "Fadelito · Tool · Confirmar Agendamento",
    "nodes": sub_nodes,
    "connections": sub_conn,
    "active": False,
    "settings": {"executionOrder": "v1"},
}

# =============================================================================
# SUB-WORKFLOW (tool): consultar_horarios — slots reais de OUTRA unidade
# =============================================================================
horarios_nodes = [
    node("Quando o Agente Pede Horários", "n8n-nodes-base.executeWorkflowTrigger", 1.1, [0, 0], {
        "inputSource": "workflowInputs",
        "workflowInputs": {"values": [
            {"name": "unidade", "type": "string"},
        ]},
    }),
    node("Janela Dias Uteis", "n8n-nodes-base.code", 2, [240, 0], {
        # unidade vem do input da tool (não do lead)
        "jsCode": js_janela("$json.unidade"),
    }),
    node("Gendo Agendamentos", "n8n-nodes-base.httpRequest", 4.4, [480, 0], {
        "method": "GET",
        "url": f"{GENDO_BASE}/agendamentos",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendQuery": True,
        "queryParameters": {"parameters": [
            {"name": "Inicio", "value": "={{ $json.inicio }}"},
            {"name": "Fim", "value": "={{ $json.fim }}"},
        ]},
        "options": {},
    }, credentials=cred_named("httpHeaderAuth", "gendo")),
    node("Calcular Slots", "n8n-nodes-base.code", 2, [720, 0], {
        "jsCode": JS_SLOTS,
    }),
]
horarios_conn = {
    "Quando o Agente Pede Horários": {"main": [[{"node": "Janela Dias Uteis", "type": "main", "index": 0}]]},
    "Janela Dias Uteis": {"main": [[{"node": "Gendo Agendamentos", "type": "main", "index": 0}]]},
    "Gendo Agendamentos": {"main": [[{"node": "Calcular Slots", "type": "main", "index": 0}]]},
}
horarios_wf = {
    "id": SUBWF_HORARIOS_ID,
    "name": "Fadelito · Tool · Consultar Horários",
    "nodes": horarios_nodes,
    "connections": horarios_conn,
    "active": False,
    "settings": {"executionOrder": "v1"},
}

# =============================================================================
# WORKFLOW PRINCIPAL (reativo)
# =============================================================================
tab_expr = (f'"{DATA_OVERRIDE}"' if DATA_OVERRIDE
            else "$now.format('dd/MM/yyyy')")

# Bloco dinâmico (dados do lead + slots reais) anexado ao fim do system prompt.
LEAD_E_SLOTS = (
    "\n\n=== DADOS DO LEAD (esta conversa) ===\n"
    "Nome: {{ $('Buscar Lead').item.json.nome }}\n"
    "Primeiro nome: {{ $('Buscar Lead').item.json.nome.split(' ')[0] }}\n"
    "Unidade: Fadelito {{ $('Buscar Lead').item.json.unidade }}\n"
    "ID do agendamento (lead_id p/ a tool confirmar_agendamento): {{ $('Buscar Lead').item.json.id }}\n"
    "Visita original: {{ $('Buscar Lead').item.json.data_hora }}\n\n"
    "=== HORÁRIOS DISPONÍVEIS REAIS — unidade do lead (use SOMENTE estes) ===\n"
    "{{ $('Calcular Slots').item.json.slots_texto }}\n"
)

def system_message(com_exemplos: bool) -> str:
    """System prompt: persona + KB completo (+exemplos PII se com_exemplos) + lead/slots."""
    base = KB_BASE + (EXEMPLOS_ROBERTO if com_exemplos else "")
    return "=" + base + LEAD_E_SLOTS


def build_main_nodes(system_msg: str) -> list:
    return [
    node("Webhook Gupshup", "n8n-nodes-base.webhook", 2.1, [0, 0], {
        "httpMethod": "POST",
        "path": "reagendamento",
        "responseMode": "onReceived",
        "responseData": "allEntries",
        "options": {},
    }, webhookId="fadelito-reagendamento"),
    node("Parse Gupshup", "n8n-nodes-base.code", 2, [220, 0], {
        "jsCode": JS_PARSE,
    }),
    node("Ler Aba do Dia", "n8n-nodes-base.googleSheets", 4.7, [440, 0], {
        "authentication": "serviceAccount",
        "documentId": {"__rl": True, "mode": "id", "value": SHEET_ID},
        "sheetName": {"__rl": True, "mode": "name", "value": "=" + tab_expr},
        "options": {},
    }, credentials=cred_named("googleApi", "google")),
    node("Buscar Lead", "n8n-nodes-base.code", 2, [660, 0], {
        "jsCode": JS_BUSCAR,
    }),
    node("Janela Dias Uteis", "n8n-nodes-base.code", 2, [880, 0], {
        "jsCode": js_janela("$('Buscar Lead').item.json.unidade"),
    }),
    node("Gendo Agendamentos", "n8n-nodes-base.httpRequest", 4.4, [1100, 0], {
        "method": "GET",
        "url": f"{GENDO_BASE}/agendamentos",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendQuery": True,
        "queryParameters": {"parameters": [
            {"name": "Inicio", "value": "={{ $json.inicio }}"},
            {"name": "Fim", "value": "={{ $json.fim }}"},
        ]},
        "options": {},
    }, credentials=cred_named("httpHeaderAuth", "gendo")),
    node("Calcular Slots", "n8n-nodes-base.code", 2, [1320, 0], {
        "jsCode": JS_SLOTS,
    }),
    # ── AI Agent + sub-nós ──
    node("AI Agent", "@n8n/n8n-nodes-langchain.agent", 3.1, [1560, 0], {
        "promptType": "define",
        "text": "={{ $('Buscar Lead').item.json.text }}",
        "options": {"systemMessage": system_msg},
    }),
    node("NVIDIA NIM", "@n8n/n8n-nodes-langchain.lmChatNvidia", 1, [1480, 220], {
        "model": E.get("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"),
        "options": {"temperature": 0.5},
    }, credentials=cred_named("nvidiaApi", "nvidia")),
    node("Memória por Telefone", "@n8n/n8n-nodes-langchain.memoryBufferWindow", 1.4, [1620, 220], {
        "sessionIdType": "customKey",
        "sessionKey": "={{ $('Buscar Lead').item.json.from }}",
        "contextWindowLength": 20,
    }),
    node("confirmar_agendamento", "@n8n/n8n-nodes-langchain.toolWorkflow", 2.2, [1760, 220], {
        "name": "confirmar_agendamento",
        "description": "Cria o agendamento da visita no Gendo quando o lead escolhe um horário REAL da lista oferecida. Use EXATAMENTE o data (YYYY-MM-DD) e horario (HH:MM) do slot escolhido, e o lead_id dos dados do lead.",
        "workflowId": {"__rl": True, "mode": "id", "value": SUBWF_ID},
        "workflowInputs": {
            "mappingMode": "defineBelow",
            "value": {
                "lead_id": "={{ $fromAI('lead_id', 'ID do agendamento original do lead', 'string') }}",
                "data": "={{ $fromAI('data', 'Data escolhida no formato YYYY-MM-DD', 'string') }}",
                "horario": "={{ $fromAI('horario', 'Horário escolhido no formato HH:MM', 'string') }}",
            },
            "matchingColumns": [],
            "schema": [
                {"id": "lead_id", "displayName": "lead_id", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True, "removed": False},
                {"id": "data", "displayName": "data", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True, "removed": False},
                {"id": "horario", "displayName": "horario", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True, "removed": False},
            ],
            "attemptToConvertTypes": False,
            "convertFieldsToString": True,
        },
    }),
    node("consultar_horarios", "@n8n/n8n-nodes-langchain.toolWorkflow", 2.2, [1900, 220], {
        "name": "consultar_horarios",
        "description": "Consulta os horários REAIS disponíveis de uma unidade Fadelito específica (nos próximos dias úteis). Use quando o lead pedir para visitar OUTRA unidade diferente da agendada. Passe o nome da unidade (ex.: 'Moema', 'Vila Madalena'). Retorna a lista de slots com [data=YYYY-MM-DD horario=HH:MM] para você oferecer.",
        "workflowId": {"__rl": True, "mode": "id", "value": SUBWF_HORARIOS_ID},
        "workflowInputs": {
            "mappingMode": "defineBelow",
            "value": {
                "unidade": "={{ $fromAI('unidade', 'Nome da unidade Fadelito que o lead quer visitar', 'string') }}",
            },
            "matchingColumns": [],
            "schema": [
                {"id": "unidade", "displayName": "unidade", "required": False, "defaultMatch": False, "display": True, "type": "string", "canBeUsedToMatch": True, "removed": False},
            ],
            "attemptToConvertTypes": False,
            "convertFieldsToString": True,
        },
    }),
    # ── pós-agente: enviar WhatsApp + atualizar Sheets ──
    node("Enviar WhatsApp", "n8n-nodes-base.httpRequest", 4.4, [1820, 0], {
        "method": "POST",
        "url": "https://api.gupshup.io/wa/api/v1/msg",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "contentType": "form-urlencoded",
        "bodyParameters": {"parameters": [
            {"name": "channel", "value": "whatsapp"},
            {"name": "source", "value": SRC_NUM},
            {"name": "destination", "value": "={{ $('Buscar Lead').item.json.from }}"},
            {"name": "message", "value": "={{ JSON.stringify({ type: 'text', text: $('AI Agent').item.json.output }) }}"},
            {"name": "src.name", "value": APP_NAME},
        ]},
        "options": {},
    }, credentials=cred_named("httpHeaderAuth", "gupshup")),
    node("Atualizar Lead", "n8n-nodes-base.googleSheets", 4.7, [2040, 0], {
        "authentication": "serviceAccount",
        "operation": "update",
        "documentId": {"__rl": True, "mode": "id", "value": SHEET_ID},
        "sheetName": {"__rl": True, "mode": "name", "value": "=" + tab_expr},
        "columns": {
            "mappingMode": "defineBelow",
            "matchingColumns": ["row_number"],
            "value": {
                "row_number": "={{ $('Buscar Lead').item.json.row_number }}",
                "status_agente": "em_conversa",
                "ultima_tentativa": "={{ $now.toISO() }}",
            },
        },
        "options": {},
    }, credentials=cred_named("googleApi", "google")),
    ]

main_conn = {
    "Webhook Gupshup": {"main": [[{"node": "Parse Gupshup", "type": "main", "index": 0}]]},
    "Parse Gupshup": {"main": [[{"node": "Ler Aba do Dia", "type": "main", "index": 0}]]},
    "Ler Aba do Dia": {"main": [[{"node": "Buscar Lead", "type": "main", "index": 0}]]},
    "Buscar Lead": {"main": [[{"node": "Janela Dias Uteis", "type": "main", "index": 0}]]},
    "Janela Dias Uteis": {"main": [[{"node": "Gendo Agendamentos", "type": "main", "index": 0}]]},
    "Gendo Agendamentos": {"main": [[{"node": "Calcular Slots", "type": "main", "index": 0}]]},
    "Calcular Slots": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
    "AI Agent": {"main": [[{"node": "Enviar WhatsApp", "type": "main", "index": 0}]]},
    "Enviar WhatsApp": {"main": [[{"node": "Atualizar Lead", "type": "main", "index": 0}]]},
    # sub-nós de IA
    "NVIDIA NIM": {"ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]]},
    "Memória por Telefone": {"ai_memory": [[{"node": "AI Agent", "type": "ai_memory", "index": 0}]]},
    "confirmar_agendamento": {"ai_tool": [[{"node": "AI Agent", "type": "ai_tool", "index": 0}]]},
    "consultar_horarios": {"ai_tool": [[{"node": "AI Agent", "type": "ai_tool", "index": 0}]]},
}

def build_main(com_exemplos: bool) -> dict:
    return {
        "id": "fadelitoAgenteReativo",
        "name": "Fadelito · Agente Reagendamento (Reativo)",
        "nodes": build_main_nodes(system_message(com_exemplos)),
        "connections": main_conn,
        "active": False,
        "settings": {"executionOrder": "v1"},
    }

main_wf = build_main(com_exemplos=False)        # versionável (sem PII)
main_wf_rag = build_main(com_exemplos=True)     # importado no n8n (com exemplos do Roberto)

# =============================================================================
# CREDENCIAIS
# =============================================================================
gcreds = json.load(open(os.path.join(ROOT, "google_credentials.json")))
credentials = [
    {"id": CRED["nvidia"]["id"], "name": CRED["nvidia"]["name"], "type": "nvidiaApi",
     "data": {"url": "https://integrate.api.nvidia.com/v1", "apiKey": E["NVIDIA_API_KEY"]}},
    {"id": CRED["groq"]["id"], "name": CRED["groq"]["name"], "type": "groqApi",
     "data": {"apiKey": E["GROQ_API_KEY"]}},
    {"id": CRED["gupshup"]["id"], "name": CRED["gupshup"]["name"], "type": "httpHeaderAuth",
     "data": {"name": "apikey", "value": E["WHATSAPP_API_TOKEN"]}},
    {"id": CRED["gendo"]["id"], "name": CRED["gendo"]["name"], "type": "httpHeaderAuth",
     "data": {"name": "Authorization", "value": "Bearer " + E["API_TOKEN"]}},
    {"id": CRED["google"]["id"], "name": CRED["google"]["name"], "type": "googleApi",
     "data": {"region": "", "email": gcreds["client_email"], "privateKey": gcreds["private_key"],
              "inpersonate": False, "delegatedEmail": ""}},
]

# ── grava ─────────────────────────────────────────────────────────────────────
def dump(obj, name):
    with open(os.path.join(HERE, name), "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    print("ok:", name)

dump(sub_wf, "tool_confirmar_agendamento.json")
dump(horarios_wf, "tool_consultar_horarios.json")
dump(main_wf, "agente_reativo.json")             # commit (KB completo, sem PII)
dump(main_wf_rag, "agente_reativo.withrag.json")  # gitignored (com exemplos do Roberto)
dump(credentials, "credentials.json")
print("done")
print(f"system prompt: {len(system_message(False))} chars (sem exemplos) | "
      f"{len(system_message(True))} chars (com exemplos do Roberto)")
