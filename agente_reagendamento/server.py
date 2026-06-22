"""Servidor HTTP para receber webhooks do Gupshup (respostas dos clientes via WhatsApp)."""
import re as _re
import sys
from datetime import datetime as _dt
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, BackgroundTasks

import config
import disponibilidade
import logger
import main
import sheets as _sheets

app = FastAPI()


def _checar_api_key(x_api_key: str = Header(default="")) -> None:
    """Rejeita requisições sem a chave correta quando INTERNAL_API_KEY está definida."""
    if config.INTERNAL_API_KEY and x_api_key != config.INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="API key inválida ou ausente")


def _processar_em_background(mensagens: list[dict]) -> None:
    """Roda o processamento pesado fora do caminho da resposta HTTP."""
    try:
        main.processar_mensagens(mensagens)
    except Exception as exc:
        import traceback
        logger.erro(f"Erro ao processar webhook (background): {exc}\n{traceback.format_exc()}")
        try:
            import whatsapp as wa
            wa.notify_sdr(f"⚠️ Erro no agente ao processar um webhook: {exc}")
        except Exception:
            pass


@app.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalido")
    logger.info(f"[WEBHOOK RAW] {payload}")

    # Deduplica de forma síncrona e devolve 200 imediatamente; o trabalho pesado
    # (Gendo + LLM + Sheets) roda em background. Assim o Gupshup não estoura o
    # timeout e não reentrega a mesma mensagem.
    try:
        novas = main.filtrar_mensagens_novas(payload)
    except Exception as exc:
        import traceback
        logger.erro(f"Erro ao parsear webhook: {exc}\n{traceback.format_exc()}")
        novas = []

    if novas:
        background_tasks.add_task(_processar_em_background, novas)
    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/disponibilidade")
async def get_disponibilidade(
    unidade: str = Query(default=""),
    n_opcoes: int = Query(default=3),
    _: None = Depends(_checar_api_key),
):
    """Slots livres via lógica Python testada — chamado pelo workflow n8n."""
    try:
        slots = disponibilidade.get_slots_disponiveis(n_opcoes, unidade)
    except Exception as exc:
        logger.erro(f"Erro em /disponibilidade: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
    slots_texto = (
        "\n".join(
            f"{i+1}) {s['label']}  [data={s['data']} horario={s['horario']}]"
            for i, s in enumerate(slots)
        )
        if slots
        else "(sem horários livres nos próximos dias úteis)"
    )
    return {"slots": slots, "slots_texto": slots_texto, "total": len(slots)}


@app.get("/buscar-lead")
async def buscar_lead(
    telefone: str = Query(...),
    n_abas: int = Query(default=7),
    _: None = Depends(_checar_api_key),
):
    """Busca lead pelo telefone nas últimas n_abas abas — multi-tab, chamado pelo n8n."""
    def _norm(t: str) -> str:
        d = _re.sub(r"\D", "", str(t or ""))
        if d and not d.startswith("55"):
            d = "55" + d
        return d

    alvo = _norm(telefone)
    if not alvo:
        raise HTTPException(status_code=400, detail="telefone obrigatório")

    try:
        abas = _sheets.listar_abas()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao listar abas: {exc}")

    abas_datas = []
    for aba in abas:
        try:
            abas_datas.append((_dt.strptime(aba, "%d/%m/%Y"), aba))
        except ValueError:
            pass
    abas_datas.sort(reverse=True)

    for _, aba in abas_datas[:n_abas]:
        try:
            leads = _sheets.get_leads(aba)
        except Exception:
            continue
        for lead in leads:
            if _norm(lead.get("telefone", "")) == alvo:
                return {"encontrado": True, "lead": lead, "aba": aba}

    return {"encontrado": False, "lead": None, "aba": None}
