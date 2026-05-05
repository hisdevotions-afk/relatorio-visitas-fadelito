"""Envio de mensagens via Z-API (WhatsApp)."""
import time
import requests

import config
import logger

_RETRYABLE = frozenset({429}) | frozenset(range(500, 600))


def _normalizar_telefone(tel: str) -> str:
    digits = "".join(c for c in (tel or "") if c.isdigit())
    if digits and not digits.startswith("55"):
        digits = "55" + digits
    return digits


def _destino(para: str) -> str:
    """Redireciona para número de teste quando MODO_TESTE=true."""
    if config.MODO_TESTE and config.WHATSAPP_TESTE_NUMBER:
        return _normalizar_telefone(config.WHATSAPP_TESTE_NUMBER)
    return _normalizar_telefone(para)


def send_message(para: str, texto: str) -> dict:
    """Envia mensagem de texto via Z-API. Respeita dry-run e modo teste."""
    numero = _destino(para)

    if config.DRY_RUN:
        logger.info(f"[DRY-RUN] Seria enviado para {numero}:\n{texto}")
        return {}

    url = (
        f"https://api.z-api.io/instances/{config.ZAPI_INSTANCE_ID}"
        f"/token/{config.ZAPI_TOKEN}/send-text"
    )
    headers = {
        "Client-Token": config.ZAPI_CLIENT_TOKEN,
        "Content-Type": "application/json",
    }
    payload = {"phone": numero, "message": texto}

    last_err: Exception | None = None
    for attempt in range(3):
        if attempt:
            time.sleep(2 ** (attempt - 1))  # 1s após 1ª falha, 2s após 2ª
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
        except requests.exceptions.RequestException as exc:
            last_err = exc
            logger.aviso(f"Z-API erro de rede, tentativa {attempt + 1}/3: {exc}")
            continue

        if resp.status_code in _RETRYABLE:
            last_err = requests.exceptions.HTTPError(
                f"HTTP {resp.status_code}", response=resp
            )
            logger.aviso(f"Z-API status {resp.status_code}, tentativa {attempt + 1}/3")
            continue

        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            logger.erro(f"Z-API erro {resp.status_code}: {exc}\n{resp.text}")
            raise

        data = resp.json()
        message_id = data.get("messageId") or data.get("zaapId") or data.get("id", "")
        print(f"[INFO] Z-API: mensagem enviada para {numero} | ID: {message_id}")
        return data

    logger.erro(f"Z-API: 3 tentativas esgotadas para {numero}")
    raise last_err or RuntimeError("Z-API: falha desconhecida")


def notify_sdr(mensagem: str) -> None:
    """Envia notificação para o número do SDR."""
    if not config.SDR_NUMBER:
        return
    try:
        send_message(config.SDR_NUMBER, mensagem)
    except Exception as exc:
        logger.aviso(f"Falha ao notificar SDR: {exc}")


def parse_webhook(payload: dict) -> list[dict]:
    """Extrai mensagens do payload do webhook Z-API.

    Retorna lista de {"from": "...", "text": "...", "timestamp": "...", "message_id": "..."}
    """
    if payload.get("fromMe") or payload.get("isGroup"):
        return []
    text_obj = payload.get("text", {})
    body = text_obj.get("message", "") if isinstance(text_obj, dict) else ""
    if not body:
        return []
    return [{
        "from": payload.get("phone", ""),
        "text": body,
        "timestamp": str(payload.get("momment", "")),
        "message_id": payload.get("messageId", ""),
    }]
