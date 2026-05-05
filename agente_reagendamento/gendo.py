"""Cliente da API Gendo com retry e backoff exponencial."""
import time

import requests

import config
import logger

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.API_TOKEN}",
        "Accept": "application/json",
    }


def _request(method: str, path: str, **kwargs) -> dict | list:
    """Executa requisição HTTP com retry e backoff exponencial."""
    url = f"{config.API_BASE_URL}{path}"
    ultimo_erro = None

    for tentativa in range(_MAX_RETRIES):
        try:
            resp = requests.request(
                method, url, headers=_headers(), timeout=config.API_TIMEOUT, **kwargs
            )
            if resp.status_code in _RETRY_STATUSES and tentativa < _MAX_RETRIES - 1:
                espera = 2 ** tentativa
                logger.aviso(f"HTTP {resp.status_code} em {path}. Aguardando {espera}s...")
                time.sleep(espera)
                continue
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, dict) and "data" in payload:
                return payload["data"]
            return payload
        except requests.exceptions.Timeout as exc:
            ultimo_erro = exc
            if tentativa < _MAX_RETRIES - 1:
                time.sleep(2 ** tentativa)
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Erro na API Gendo [{path}]: {exc}") from exc

    raise RuntimeError(f"Timeout após {_MAX_RETRIES} tentativas em {path}") from ultimo_erro


def get_agendamentos(inicio: str, fim: str) -> list[dict]:
    """GET /agendamentos?Inicio=YYYY-MM-DD&Fim=YYYY-MM-DD"""
    resultado = _request("GET", "/agendamentos", params={"Inicio": inicio, "Fim": fim})
    return resultado if isinstance(resultado, list) else []


def get_agendamento_dados(agendamento_id: int | str) -> dict:
    """GET /agendamento-dados/{id} — retorna dados completos do agendamento."""
    resultado = _request("GET", f"/agendamento-dados/{agendamento_id}")
    return resultado if isinstance(resultado, dict) else {}


def criar_agendamento(
    id_paciente,
    id_responsavel,
    id_servico,
    data: str,
    horario: str,
    tempo: str = None,
    status: str = "1",
) -> dict:
    """POST /agendamento — cria novo agendamento via multipart/form-data."""
    if tempo is None:
        tempo = str(config.VISITA_DURACAO)

    resultado = _request(
        "POST",
        "/agendamento",
        data={
            "id_paciente": id_paciente,
            "id_responsavel": id_responsavel,
            "id_servico": id_servico,
            "data": data,
            "horario": horario,
            "tempo": tempo,
            "status": status,
        },
    )
    return resultado if isinstance(resultado, dict) else {}


def atualizar_status(agendamento_id: int | str, status: str) -> dict:
    """POST /agendamento-status — atualiza status do agendamento original."""
    resultado = _request(
        "POST",
        "/agendamento-status",
        data={"id": agendamento_id, "status": status},
    )
    return resultado if isinstance(resultado, dict) else {}
