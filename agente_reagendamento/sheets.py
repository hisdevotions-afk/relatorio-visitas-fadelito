"""Leitura e escrita no Google Sheets (colunas A–L)."""
import json
import sys
from datetime import date, datetime, timedelta

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

import config
import logger

# Colunas de controle do agente (H–K, índice 0-based = 7–10)
CABECALHO_AGENTE = [
    "status_agente",    # H
    "tentativas",       # I
    "ultima_tentativa", # J
    "nova_data",        # K
]


def _get_creds() -> Credentials:
    creds_json = __import__("os").getenv("GOOGLE_CREDENTIALS_JSON", "")
    creds_file = __import__("os").getenv("GOOGLE_CREDENTIALS_FILE", "")
    if creds_json:
        return Credentials.from_service_account_info(
            json.loads(creds_json), scopes=config.GOOGLE_SCOPES
        )
    if creds_file:
        return Credentials.from_service_account_file(creds_file, scopes=config.GOOGLE_SCOPES)
    sys.exit("[ERRO] Configure GOOGLE_CREDENTIALS_JSON ou GOOGLE_CREDENTIALS_FILE.")


def _service():
    return build("sheets", "v4", credentials=_get_creds())


_FERIADOS_FIXOS: frozenset[tuple[int, int]] = frozenset({
    (1, 1), (21, 4), (1, 5), (7, 9),
    (12, 10), (2, 11), (15, 11), (20, 11), (25, 12),
})

# Feriados móveis por ano: {ano: {(dia, mes), ...}}
_FERIADOS_MOVEIS: dict[int, frozenset[tuple[int, int]]] = {
    2026: frozenset({(16, 2), (17, 2), (3, 4), (4, 6)}),
}


def _is_feriado(d: date) -> bool:
    if (d.day, d.month) in _FERIADOS_FIXOS:
        return True
    return (d.day, d.month) in _FERIADOS_MOVEIS.get(d.year, frozenset())


def _ultimo_dia_util() -> date:
    if config.DATA_OVERRIDE:
        return datetime.strptime(config.DATA_OVERRIDE, "%d/%m/%Y").date()
    d = date.today() - timedelta(days=1)
    while d.weekday() >= 5 or _is_feriado(d):
        d -= timedelta(days=1)
    return d


def hoje_e_dia_util() -> bool:
    """Retorna True se hoje for dia útil (não fim de semana, não feriado)."""
    hoje = date.today()
    return hoje.weekday() < 5 and not _is_feriado(hoje)


def tab_name(d: date | None = None) -> str:
    """Retorna nome da aba no formato dd/mm/yyyy."""
    return (d or _ultimo_dia_util()).strftime("%d/%m/%Y")


def _col_letra(idx_zero: int) -> str:
    """Converte índice 0-based para letra de coluna (0→A, 7→H, ...)."""
    result = ""
    n = idx_zero + 1
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def ensure_agent_columns(aba: str | None = None) -> None:
    """Garante que as colunas H–L existam com cabeçalho correto."""
    if aba is None:
        aba = tab_name()

    svc = _service()
    try:
        res = svc.spreadsheets().values().get(
            spreadsheetId=config.GOOGLE_SHEETS_ID,
            range=f"'{aba}'!H1:K1",
        ).execute()
        atual = (res.get("values") or [[]])[0]
    except Exception:
        atual = []

    if atual != CABECALHO_AGENTE:
        if config.DRY_RUN:
            logger.info(f"[DRY-RUN] Seria gravado cabeçalho agente em '{aba}'!H1:K1")
            return
        svc.spreadsheets().values().update(
            spreadsheetId=config.GOOGLE_SHEETS_ID,
            range=f"'{aba}'!H1:K1",
            valueInputOption="RAW",
            body={"values": [CABECALHO_AGENTE]},
        ).execute()


def get_leads(aba: str | None = None) -> list[dict]:
    """Lê todas as linhas da aba e retorna lista de dicts com colunas A–L."""
    if aba is None:
        aba = tab_name()

    svc = _service()
    try:
        res = svc.spreadsheets().values().get(
            spreadsheetId=config.GOOGLE_SHEETS_ID,
            range=f"'{aba}'!A:L",
        ).execute()
    except Exception as exc:
        logger.erro(f"Falha ao ler aba '{aba}': {exc}")
        return []

    values = res.get("values", [])
    if not values:
        return []

    leads = []
    for i, linha in enumerate(values[1:], start=2):  # linha 1 é cabeçalho
        while len(linha) < 12:
            linha.append("")
        leads.append({
            "row_index": i,
            "aba": aba,
            "id":               linha[0],
            "data_hora":        linha[1],
            "nome":             linha[2],
            "unidade":          linha[3],
            "servico":          linha[4],
            "status":           linha[5],
            "telefone":         linha[6],
            "status_agente":    linha[7],
            "tentativas":       linha[8],
            "ultima_tentativa": linha[9],
            "nova_data":        linha[10],
            "log_conversa":     linha[11],
        })
    return leads


def update_lead_agente(aba: str, row_index: int, **kwargs) -> None:
    """Atualiza colunas de controle do agente (H–K) para a linha indicada."""
    col_map = {
        "status_agente":    7,
        "tentativas":       8,
        "ultima_tentativa": 9,
        "nova_data":        10,
    }

    data = []
    for chave, col_idx in col_map.items():
        if chave in kwargs:
            col = _col_letra(col_idx)
            data.append({
                "range": f"'{aba}'!{col}{row_index}",
                "values": [[str(kwargs[chave])]],
            })

    if not data:
        return

    if config.DRY_RUN:
        resumo = ", ".join(f"{k}={kwargs[k]}" for k in col_map if k in kwargs)
        logger.info(f"[DRY-RUN] Seria gravado no Sheets: linha {row_index}, {resumo}")
        return

    _service().spreadsheets().values().batchUpdate(
        spreadsheetId=config.GOOGLE_SHEETS_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()


