"""Envio de mensagens via Gupshup WhatsApp Business API."""
import json
import time
import requests

import config
import logger

_RETRYABLE = frozenset({429}) | frozenset(range(500, 600))
_GUPSHUP_URL = "https://api.gupshup.io/wa/api/v1/msg"
_GUPSHUP_TEMPLATE_URL = "https://api.gupshup.io/wa/api/v1/template/msg"


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
    """Envia mensagem de texto via Gupshup. Respeita dry-run e modo teste."""
    numero = _destino(para)

    if config.DRY_RUN:
        logger.info(f"[DRY-RUN] Seria enviado para {numero}:\n{texto}")
        return {}

    headers = {
        "apikey": config.WHATSAPP_API_TOKEN,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "channel": "whatsapp",
        "source": config.WHATSAPP_SOURCE_NUMBER,
        "destination": numero,
        "message": json.dumps({"type": "text", "text": texto}),
        "src.name": config.WHATSAPP_APP_NAME,
    }

    last_err: Exception | None = None
    for attempt in range(3):
        if attempt:
            time.sleep(2 ** (attempt - 1))
        try:
            resp = requests.post(_GUPSHUP_URL, headers=headers, data=data, timeout=30)
        except requests.exceptions.RequestException as exc:
            last_err = exc
            logger.aviso(f"Gupshup erro de rede, tentativa {attempt + 1}/3: {exc}")
            continue

        if resp.status_code in _RETRYABLE:
            last_err = requests.exceptions.HTTPError(
                f"HTTP {resp.status_code}", response=resp
            )
            logger.aviso(f"Gupshup status {resp.status_code}, tentativa {attempt + 1}/3")
            continue

        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            logger.erro(f"Gupshup erro {resp.status_code}: {exc}\n{resp.text}")
            raise

        data_resp = resp.json()
        message_id = data_resp.get("messageId", "")
        print(f"[INFO] Gupshup: mensagem enviada para {numero} | ID: {message_id}")
        return data_resp

    logger.erro(f"Gupshup: 3 tentativas esgotadas para {numero}")
    raise last_err or RuntimeError("Gupshup: falha desconhecida")


def send_template(para: str, primeiro_nome: str) -> dict:
    """Envia template aprovado via endpoint dedicado de templates do Gupshup.

    O endpoint /wa/api/v1/msg NÃO processa templates (entrega o JSON como texto
    literal); o /wa/api/v1/template/msg recebe o UUID do template aprovado.
    """
    numero = _destino(para)

    if config.DRY_RUN:
        logger.info(f"[DRY-RUN] Seria enviado template para {numero} | nome={primeiro_nome}")
        return {}

    headers = {
        "apikey": config.WHATSAPP_API_TOKEN,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "channel": "whatsapp",
        "source": config.WHATSAPP_SOURCE_NUMBER,
        "destination": numero,
        "template": json.dumps({
            "id": config.WHATSAPP_TEMPLATE_ID,
            "params": [primeiro_nome],
        }),
        "src.name": config.WHATSAPP_APP_NAME,
    }

    last_err: Exception | None = None
    for attempt in range(3):
        if attempt:
            time.sleep(2 ** (attempt - 1))
        try:
            resp = requests.post(_GUPSHUP_TEMPLATE_URL, headers=headers, data=data, timeout=30)
        except requests.exceptions.RequestException as exc:
            last_err = exc
            logger.aviso(f"Gupshup template erro de rede, tentativa {attempt + 1}/3: {exc}")
            continue

        if resp.status_code in _RETRYABLE:
            last_err = requests.exceptions.HTTPError(
                f"HTTP {resp.status_code}", response=resp
            )
            logger.aviso(f"Gupshup template status {resp.status_code}, tentativa {attempt + 1}/3")
            continue

        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            logger.erro(f"Gupshup template erro {resp.status_code}: {exc}\n{resp.text}")
            raise

        data_resp = resp.json()
        message_id = data_resp.get("messageId", "")
        print(f"[INFO] Gupshup: template enviado para {numero} | ID: {message_id}")
        return data_resp

    logger.erro(f"Gupshup template: 3 tentativas esgotadas para {numero}")
    raise last_err or RuntimeError("Gupshup template: falha desconhecida")


def notify_sdr(mensagem: str) -> None:
    """Envia notificação para o número do SDR."""
    if not config.SDR_NUMBER:
        return
    try:
        send_message(config.SDR_NUMBER, mensagem)
    except Exception as exc:
        logger.aviso(f"Falha ao notificar SDR: {exc}")


def parse_webhook(payload: dict) -> list[dict]:
    """Extrai mensagens do payload do webhook Gupshup.

    Suporta dois formatos:
    - Meta WhatsApp Cloud API: {"entry": [{"changes": [{"value": {"messages": [...]}}]}]}
    - Gupshup legado (simulação local): {"type": "message", "payload": {...}}
    """
    # Formato Meta Cloud API (enviado pelo Gupshup WABA)
    if "entry" in payload:
        mensagens = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "messages":
                    continue
                for msg in change.get("value", {}).get("messages", []):
                    if msg.get("type") != "text":
                        continue
                    text = msg.get("text", {}).get("body", "")
                    if not text:
                        continue
                    mensagens.append({
                        "from": msg.get("from", ""),
                        "text": text,
                        "timestamp": str(msg.get("timestamp", "")),
                        "message_id": msg.get("id", ""),
                    })
        return mensagens

    # Formato Gupshup legado (usado em _simular_webhook.py)
    if payload.get("type") != "message":
        return []
    inner = payload.get("payload", {})
    if inner.get("type") != "text":
        return []
    text = inner.get("payload", {}).get("text", "")
    if not text:
        return []
    return [{
        "from": inner.get("source", ""),
        "text": text,
        "timestamp": str(payload.get("timestamp", "")),
        "message_id": inner.get("id", ""),
    }]
