# Agente de Reagendamento Fadelito — versão n8n

Migração do agente conversacional (`agente_reagendamento/`) para n8n, focada no
**fluxo reativo** (lead responde no WhatsApp → agente conversa e reagenda).

Já está **importado e pronto** na instância n8n local (2.26.8, `http://localhost:5678`).
Os workflows entram **inativos** — é só abrir, conferir e ativar quando for testar.

## O que foi criado

| Item | Tipo | ID no n8n |
|---|---|---|
| **Fadelito · Agente Reagendamento (Reativo)** | Workflow principal | `fadelitoAgenteReativo` |
| **Fadelito · Tool · Confirmar Agendamento** | Sub-workflow (tool do agente) | `fadelitoToolConfirmar` |
| **Fadelito · Tool · Consultar Horários** | Sub-workflow (tool do agente) | `fadelitoToolHorarios` |
| Fadelito NVIDIA NIM | Credencial (`nvidiaApi`) | `fadelitoNvidiaApi` |
| Fadelito Groq | Credencial (`groqApi`) | `fadelitoGroqApi` |
| Fadelito Gupshup (apikey) | Credencial (`httpHeaderAuth`) | `fadelitoGupshup` |
| Fadelito Gendo (Bearer) | Credencial (`httpHeaderAuth`) | `fadelitoGendo` |
| Fadelito Google Service Account | Credencial (`googleApi`) | `fadelitoGoogle` |

As credenciais foram preenchidas a partir do `agente_reagendamento/.env` e do
`google_credentials.json` — não há nada a digitar à mão.

## Arquitetura do workflow principal

```
Webhook Gupshup (POST /webhook/reagendamento, responde 200 na hora)
  → Parse Gupshup        (Code: extrai telefone/texto/message_id, normaliza)
  → Ler Aba do Dia       (Google Sheets: lê a aba dd/mm/yyyy de hoje)
  → Buscar Lead          (Code: acha a linha pelo telefone normalizado)
  → Janela Dias Uteis    (Code: próximos 5 dias úteis, sem feriados, grade 09–16h30)
  → Gendo Agendamentos   (HTTP GET /agendamentos?Inicio&Fim)
  → Calcular Slots       (Code: cruza grade × ocupados da unidade → até 6 slots REAIS)
  → AI Agent             ┌─ NVIDIA NIM            (modelo)
                         ├─ Memória por Telefone  (histórico por sessionKey = telefone)
                         ├─ confirmar_agendamento (tool → cria visita no Gendo)
                         └─ consultar_horarios    (tool → slots reais de OUTRA unidade)
  → Enviar WhatsApp      (HTTP POST Gupshup /wa/api/v1/msg)
  → Atualizar Lead       (Google Sheets: status_agente + ultima_tentativa)
```

### RAG / base de conhecimento

O system prompt do AI Agent usa o **`KNOWLEDGE_BASE` completo do `rag.py`** (regras
anti-alucinação, endereços de todas as unidades, links de Maps, turmas, financeiro,
modelos de resposta, handoff) — não é mais a versão condensada inicial.

Os **exemplos reais do Roberto** (`tallos_export/roberto_rag.jsonl`, conversas de
clientes = PII) entram só na versão **`agente_reativo.withrag.json`**, que é a importada
no n8n mas fica **fora do git** (`.gitignore`). O `agente_reativo.json` versionado tem o
KB completo, porém **sem** os exemplos. `_build.py` lê os exemplos via
`rag.get_exemplos_roberto(seed=42)` (determinístico).

### Troca de unidade (tool `consultar_horarios`)

Quando o lead pede para visitar **outra** unidade, o agente chama
`consultar_horarios(unidade)` → o sub-workflow consulta o Gendo e devolve os slots
**reais daquela unidade** (mesma lógica de dias úteis/feriados/ocupação). O agente então
oferece esses horários, cita o endereço (que está no KB) e confirma via
`confirmar_agendamento`. Os slots da unidade original já vêm pré-calculados no prompt.

### Como os 3 bugs do teste antigo foram resolvidos aqui

1. **Slots "hardcoded"** → o nó *Calcular Slots* consulta o Gendo a cada mensagem e
   filtra pelos agendamentos **reais da unidade do lead** (match de nome normalizado:
   sem acento, sem "Fadelito", `V.`→`Vila`). Validado contra a agenda ao vivo: unidades
   diferentes retornam horários diferentes.
2. **Conversa não flui / repete** → o nó *Memória por Telefone* mantém o histórico
   real entre mensagens (chave = telefone), então o AI Agent tem contexto e não recomeça.
3. **Não entendeu o horário** → o AI Agent (tool-calling) interpreta linguagem natural
   ("o primeiro", "terça às 14h") e chama `confirmar_agendamento` com `data`/`horario`
   exatos do slot. Os slots reais entram no system prompt já rotulados com
   `[data=YYYY-MM-DD horario=HH:MM]` para o agente copiar sem ambiguidade.

## Para testar

1. Abra **Fadelito · Agente Reagendamento (Reativo)** no n8n e confira se as 4
   credenciais aparecem resolvidas (verde) nos nós Google Sheets, Gendo, NVIDIA e Gupshup.
2. A aba lida é a de **hoje** (`{{ $now.format('dd/MM/yyyy') }}`). Para forçar outra,
   defina `DATA_OVERRIDE=dd/mm/yyyy` no `.env` e rode `python3 _build.py` + reimporte,
   **ou** edite o valor do campo *sheetName* nos 2 nós Google Sheets.
3. Garanta que o lead de teste (Roberto, tel `11989171391`) existe na aba.
4. **Ative** o workflow. A URL de produção do webhook fica em
   `https://<host>/webhook/reagendamento` — aponte o callback do Gupshup para lá
   (ou use o botão *Test workflow* + a URL de teste para um disparo manual).
5. Mande uma mensagem do número de teste e acompanhe a execução nó a nó.

## Limitações conhecidas / próximos passos

- **Sem failover NVIDIA↔Groq.** O AI Agent usa só a NVIDIA. A credencial Groq já está
  criada: para alternar, troque o nó de modelo por um *Groq Chat Model* apontando para
  `fadelitoGroqApi`. Failover automático exigiria um ramo de erro (a fazer).
- **Busca de lead em 1 aba só** (a de hoje). O Python varre as últimas 7 abas; aqui,
  para o teste, lê a aba do dia. Dá para expandir com um loop depois.
- **status_agente** é gravado como `em_conversa`. O mapeamento fino
  (`reagendado`/`perdido`/`transferido_sdr`) ainda não é derivado da conversa — a tool
  `confirmar_agendamento` já cancela o antigo (status 7), mas a coluna do Sheets não
  recebe `reagendado` automaticamente. A fazer.
- **Troca de unidade**: o agente consulta slots reais da nova unidade (tool
  `consultar_horarios`) e confirma lá, mas a `unidade_alvo` (coluna M) ainda não é
  persistida no Sheets como no Python — a memória da conversa cobre isso na sessão.
- O **fluxo proativo** (envio diário das tentativas 1/2/3) não foi migrado — segue no
  Python (`main.py --processar` via GitHub Actions). Esta migração cobre só o reativo.

## Regenerar / versionar

`_build.py` gera os JSON a partir do `.env`, do `google_credentials.json` e do
`rag.py` (+ `tallos_export/roberto_rag.jsonl` para os exemplos).

```bash
cd n8n_workflows
python3 _build.py                                      # gera os JSON (inclui .withrag e credentials)
n8n import:credentials --input=credentials.json        # cria/atualiza as 5 credenciais
n8n import:workflow   --input=tool_confirmar_agendamento.json
n8n import:workflow   --input=tool_consultar_horarios.json
n8n import:workflow   --input=agente_reativo.withrag.json   # versão com RAG completo (importar ESTA)
```

Arquivos gerados:
- `agente_reativo.json` — versionável, KB completo **sem** exemplos PII.
- `agente_reativo.withrag.json` — **gitignored**, KB completo **+** exemplos do Roberto (é a que se importa no n8n).
- `tool_confirmar_agendamento.json`, `tool_consultar_horarios.json` — sub-workflows (sem PII).
- `credentials.json` — **gitignored**, segredos em texto puro só p/ o import.

> ⚠️ Apague `credentials.json` depois de importar (os segredos ficam cifrados no n8n).
> Os `*.json` dos workflows **não** contêm segredos (só referências por ID de credencial).
