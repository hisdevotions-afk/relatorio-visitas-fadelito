"""Servidor HTTP para receber webhooks do Gupshup (respostas dos clientes via WhatsApp)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Request, HTTPException

import logger
import main

app = FastAPI()


@app.post("/webhook")
async def receive_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalido")
    try:
        main.processar_resposta_webhook(payload)
    except Exception as exc:
        logger.erro(f"Erro ao processar webhook: {exc}")
    return {"ok": True}


@app.get("/health")
async def health():
    return {"status": "ok"}
