# CLAUDE.md — relatorio_visitas

Projeto de automação da Fadelito (rede de escolas infantis) para recuperação de leads que faltaram ou cancelaram visitas presenciais.

## Visão geral

Dois componentes independentes que se complementam:

1. **`relatorio_visitas.py`** — script diário que gera a planilha de visitas
2. **`agente_reagendamento/`** — agente WhatsApp que contata os leads e gerencia o reagendamento

---

## Componente 1: relatorio_visitas.py

Roda diariamente (cron na VPS, 12h Brasília) e cria uma aba no Google Sheets com as visitas do último dia útil.

**Fluxo:**
1. Busca agendamentos na API Gendo (`/agendamentos?Inicio=&Fim=`)
2. Filtra: apenas `servico == "Visita"` e `status_agendamento` em `{1,2,3,7,9}`
3. Enriquece com telefone via `/agendamento-dados/{id}` (com sleep 0.3s entre chamadas)
4. Cria aba no Sheets no formato `dd/mm/yyyy` com formatação (cabeçalho negrito, linhas pendentes em amarelo)

**Colunas geradas (A–K):**
`ID | Data/Hora | Nome | Unidade | Serviço | Status | Telefone | status_agente | tentativas | ultima_tentativa | nova_data`

**Status do Gendo:**
- `1` = Agendado, `2` = Confirmado, `3` = Realizado, `7` = Cancelado, `9` = Faltou

**Configuração (`.env` raiz):**
```
API_BASE_URL=https://mora877.adm.gendo.app/api
API_TOKEN=...
GOOGLE_CREDENTIALS_FILE=.../google_credentials.json
GOOGLE_SHEETS_ID=1hdQPqo3gjxckY-8O-R2IZZMIh9IU60x1tMSBjW2XFmw
```

**Como rodar:**
```bash
python relatorio_visitas.py
# Período customizado:
DATA_INICIO=2026-05-20 DATA_FIM=2026-05-22 python relatorio_visitas.py
```

---

## Componente 2: agente_reagendamento/

Agente conversacional via WhatsApp que contata leads com status `Cancelado` ou `Faltou` e tenta reagendar a visita.

### Stack

| Camada | Tecnologia |
|---|---|
| LLM | NVIDIA NIM (`nemotron-3-ultra-550b`) primário + Groq (`llama-3.3-70b`) backup, failover bidirecional automático (`llm.py`) |
| WhatsApp template (tentativa 1) | Gupshup WABA — endpoint dedicado `/wa/api/v1/template/msg` (UUID do template) |
| WhatsApp sessão (tentativas 2/3 e respostas) | Gupshup WABA — `/wa/api/v1/msg` |
| Agendamento | API Gendo |
| Persistência | Google Sheets (colunas A–L) |
| Webhook server | FastAPI + Uvicorn |

### Módulos

| Arquivo | Responsabilidade |
|---|---|
| `main.py` | Orquestrador — proativo (`processar_leads`) e reativo (`processar_resposta_webhook`) |
| `agente.py` | Cérebro: classificação (determinística p/ "1"/"2"/horário; LLM p/ o resto), histórico por lead, fallback handoff |
| `llm.py` | Camada de LLM com 2 provedores (NVIDIA NIM + Groq) e failover bidirecional automático + cooldown |
| `sheets.py` | Leitura e escrita no Google Sheets (colunas A–L); `listar_abas()` p/ busca de lead |
| `whatsapp.py` | Envio via Gupshup, parse do webhook, retry com backoff |
| `server.py` | FastAPI — `POST /webhook` (Gupshup) e `GET /health` |
| `disponibilidade.py` | Calcula slots livres nos próximos dias úteis via API Gendo |
| `gendo.py` | Cliente da API Gendo (get, criar, atualizar status) |
| `rag.py` | Base de conhecimento Fadelito (RAG v2.0) + links Google Maps por unidade |
| `prompts.py` | Templates de mensagem e prompts do LLM |
| `config.py` | Variáveis de ambiente centralizadas + flag DRY_RUN |
| `logger.py` | Logger stdout/stderr + `logs/conversas.log` |

### Fluxo de tentativas (proativo)

```
Tentativa 1  → imediata       → mensagem fixa (template aprovado Gupshup/Meta)
Tentativa 2  → após 2 dias    → gerada pelo LLM
Tentativa 3  → após 5 dias    → gerada pelo LLM (tom de despedida)
Encerrar     → 2 dias após T3 → marca como "perdido", notifica SDR
```

### Fluxo de resposta do lead (reativo)

```
Lead responde "1" (quer reagendar) → agente envia os 3 slots disponíveis
Lead escolhe horário               → cria agendamento no Gendo, cancela o antigo (status 7)
Lead responde "2" / recusa         → marca como "perdido", notifica SDR
Lead quer ligar                    → notifica SDR para ligar
Lead negocia horário               → LLM oferece alternativas
Resposta indefinida                → LLM responde mantendo foco no reagendamento
```

### Colunas do Sheets (A–L)

```
A=ID  B=Data/Hora  C=Nome  D=Unidade  E=Serviço  F=Status  G=Telefone
H=status_agente  I=tentativas  J=ultima_tentativa  K=nova_data  L=log_conversa
```

A coluna **L** (`log_conversa`) armazena o histórico de cada conversa serializado em JSON — permite reconstituir o contexto entre sessões.

**status_agente possíveis:** `pendente | tentativa_1 | tentativa_2 | tentativa_3 | reagendado | perdido`

### Configuração (`.env` em `agente_reagendamento/`)

```
# API Gendo
API_BASE_URL=https://mora877.adm.gendo.app/api
API_TOKEN=...
API_TIMEOUT=30

# Google Sheets
GOOGLE_CREDENTIALS_FILE=../google_credentials.json
GOOGLE_SHEETS_ID=1hdQPqo3gjxckY-8O-R2IZZMIh9IU60x1tMSBjW2XFmw

# WhatsApp — Gupshup
WHATSAPP_API_TOKEN=sk_...
WHATSAPP_WABA_ID=4337182089852926
WHATSAPP_SOURCE_NUMBER=5511966328404
WHATSAPP_APP_NAME=Number02
WHATSAPP_SDR_NUMBER=5511989171391
WHATSAPP_TEMPLATE_NAME=teste_agente_ia
WHATSAPP_TEMPLATE_ID=f9b285ee-c2c4-4aee-9efb-72667d13d281

# LLM (failover bidirecional: primário atende, backup assume se esgotar a cota)
LLM_PRIMARY=nvidia
NVIDIA_API_KEY=nvapi-...
GROQ_API_KEY=gsk_...

# Visitas
VISITA_DURACAO_MINUTOS=60
SLOT_INICIO=09:00
SLOT_FIM=16:30

# Modo teste — só processa o lead com WHATSAPP_TESTE_NUMBER
MODO_TESTE=true
WHATSAPP_TESTE_NUMBER=11989171391

# Forçar aba específica (dd/mm/yyyy) — útil para testes
# DATA_OVERRIDE=22/05/2026
```

### Como rodar

```bash
cd agente_reagendamento

# Processar leads do último dia útil
python main.py --processar

# Forçar aba específica
python main.py --processar --tab 22/05/2026

# Dry-run (sem enviar WhatsApp, sem gravar Sheets, sem criar no Gendo)
python main.py --dry-run --processar

# Demo com leads fictícios (não exige credenciais reais)
python main.py --demo

# Teste de regressão das conversas (dry-run, slots mockados, LLM real)
python teste_conversa.py

# Subir servidor de webhook
uvicorn server:app --host 0.0.0.0 --port 8000
```

### Lead de teste

- **Nome:** Roberto (TESTE) | **ID:** 99999 | **Tel:** 11989171391
- Precisa existir como linha na aba que será processada
- Com `MODO_TESTE=true`, todos os leads reais são ignorados e só ele é processado
- Na VPS, rodar proativo: `cd /opt/relatorio-visitas/agente_reagendamento && ../.venv/bin/python main.py --processar --tab 18/06/2026`

### Deploy / Execução

- **Fluxo proativo** (envio diário): GitHub Actions (`agente_reagendamento.yml`, cron 13h30 UTC) roda `main.py --processar`
- **Fluxo reativo** (webhook): servidor **ativo** em `https://agente.fadelito.com.br` (VPS `76.13.236.111`, systemd `reagendamento`, porta 8000 atrás de Cloudflare). Gupshup faz callback em `POST /webhook`. Health: `GET /health` → `{"status":"ok"}`. Workaround local sem servidor: `_simular_webhook.py`
- **Não há CI/CD de deploy** — após `git push`, atualizar a VPS:
  ```bash
  cd /opt/relatorio-visitas
  git stash          # se houver alterações locais (reagendamento.service, setup_vps.sh)
  git pull
  /opt/relatorio-visitas/.venv/bin/pip install <pacote>   # quando deps mudarem
  systemctl restart reagendamento
  ```
  ⚠️ Usar sempre `/opt/relatorio-visitas/.venv/bin/pip` — o pip do sistema retorna "externally-managed-environment". Deps novas adicionadas: `openai` (LLM failover).
- **Porta real na VPS:** `8002` (apesar de o `.service` ter `--port 8000` — o Nginx/Cloudflare roteia para 8002). Verificar com `journalctl -u reagendamento | grep "Uvicorn running"`.

### Gupshup — pontos importantes

- Endpoint de sessão: `https://api.gupshup.io/wa/api/v1/msg` (WABA — **não** usar `sm/api/v1`)
- Endpoint de template: `https://api.gupshup.io/wa/api/v1/template/msg`
- Header: `apikey: sk_...` (não é Bearer)
- Corpo (sessão): `form-encoded` com `channel`, `source`, `destination`, `message` (JSON string), `src.name`
- Corpo (template): `form-encoded` com `channel`, `source`, `destination`, `src.name` e `template` = JSON string `{"id": "<UUID do template>", "params": ["<nome>"]}` — usa o **UUID**, não o nome
- Mensagens de sessão **funcionam apenas dentro da janela de 24h** (após o lead ter respondido)
- O endpoint `/msg` **NÃO processa templates** — JSON com `"type":"template"` no campo `message` é entregue como texto literal (confirmado 26/05/2026). Templates funcionam **somente** pelo endpoint `/template/msg` (validado 10/06/2026, entrega confirmada). A integração direta com a Meta Cloud API, antes planejada, tornou-se desnecessária.

### Template aprovado (tentativa 1)

- **Nome:** `teste_agente_ia`
- **UUID Gupshup:** `f9b285ee-c2c4-4aee-9efb-72667d13d281`
- **Status:** Approved / not rated
- **Variável:** `{{1}}` = primeiro nome do lead

```
Olá, {{1}}. Vocês fizeram falta na nossa visita! 💙💛
Desejo que esteja tudo bem com a sua família.
A rotina com os pequenos pode mudar a qualquer momento, e entendemos isso com empatia.
Será um prazer recebê-los e mostrar cada detalhe da nossa unidade.

1 - Quero reagendar
2 - Optei por outra escola
```

---

## Arquivos relevantes fora do agente

| Arquivo | Descrição |
|---|---|
| `relatorio_visitas.py` | Script de geração do relatório diário |
| `google_credentials.json` | Credenciais da service account Google (não commitado) |
| `.env` | Variáveis do relatorio_visitas.py (raiz) |
| `executar_relatorio.bat` | Script local Windows para rodar o relatório |
| `relatorios/` | Backups locais em `.xlsx` |
