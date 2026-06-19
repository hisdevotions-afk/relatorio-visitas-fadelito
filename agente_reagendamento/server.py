"""Servidor HTTP para receber webhooks do Gupshup (respostas dos clientes via WhatsApp)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException

import logger
import main

app = FastAPI()


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
