import os
import sys
import json
import time
from datetime import datetime, date, timedelta

import requests
import pandas as pd
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

load_dotenv()

API_BASE_URL  = os.getenv("API_BASE_URL", "").rstrip("/")
API_TOKEN     = os.getenv("API_TOKEN", "")
API_TIMEOUT   = int(os.getenv("API_TIMEOUT", "30"))
DATA_INICIO   = os.getenv("DATA_INICIO", "")
DATA_FIM      = os.getenv("DATA_FIM", "")

GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
GOOGLE_SCOPES    = [
    "https://www.googleapis.com/auth/spreadsheets",
]

STATUS_LABELS   = {"1": "Agendado", "2": "Confirmado", "3": "Realizado", "7": "Cancelado", "9": "Faltou"}
STATUS_VALIDOS  = set(STATUS_LABELS)
STATUS_PENDENTE = {"Agendado", "Confirmado"}

COLUNAS = ["ID", "Data/Hora", "Nome", "Unidade", "Serviço", "Status", "Telefone",
           "status_agente", "tentativas", "ultima_tentativa", "nova_data"]


def _validate_env() -> None:
    missing = [k for k in ("API_BASE_URL", "API_TOKEN") if not os.getenv(k)]
    if missing:
        sys.exit(f"[ERRO] Variáveis de ambiente obrigatórias não definidas: {', '.join(missing)}")
    if not os.getenv("GOOGLE_CREDENTIALS_JSON") and not os.getenv("GOOGLE_CREDENTIALS_FILE"):
        sys.exit("[ERRO] Configure GOOGLE_CREDENTIALS_JSON ou GOOGLE_CREDENTIALS_FILE.")
    if not GOOGLE_SHEETS_ID:
        sys.exit("[ERRO] Configure GOOGLE_SHEETS_ID com o ID da planilha.")


def _get_google_creds() -> Credentials:
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "")
    if creds_json:
        return Credentials.from_service_account_info(json.loads(creds_json), scopes=GOOGLE_SCOPES)
    if creds_file:
        return Credentials.from_service_account_file(creds_file, scopes=GOOGLE_SCOPES)
    sys.exit("[ERRO] Credenciais do Google não configuradas.")


def _last_business_day() -> date:
    today = date.today()
    delta = 3 if today.weekday() == 0 else 1
    return today - timedelta(days=delta)


def _resolve_dates() -> tuple[str, str]:
    def parse(value: str, label: str) -> str:
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            sys.exit(f"[ERRO] {label} inválida: '{value}'. Use o formato YYYY-MM-DD.")

    inicio = parse(DATA_INICIO, "DATA_INICIO") if DATA_INICIO else _last_business_day().isoformat()
    fim    = parse(DATA_FIM, "DATA_FIM")       if DATA_FIM    else inicio
    return inicio, fim


def _fetch_agendamentos(inicio: str, fim: str) -> list[dict]:
    endpoint = f"{API_BASE_URL}/agendamentos"
    headers  = {"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"}
    params   = {"Inicio": inicio, "Fim": fim}

    try:
        resp = requests.get(endpoint, headers=headers, params=params, timeout=API_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        sys.exit(f"[ERRO] Não foi possível conectar à API: {endpoint}")
    except requests.exceptions.Timeout:
        sys.exit(f"[ERRO] Timeout após {API_TIMEOUT}s ao chamar a API.")
    except requests.exceptions.HTTPError as exc:
        sys.exit(f"[ERRO] API retornou HTTP {resp.status_code}: {exc}")

    try:
        payload = resp.json()
    except json.JSONDecodeError:
        sys.exit("[ERRO] Resposta da API não é JSON válido.")

    if isinstance(payload, dict):
        if "data" not in payload:
            sys.exit("[ERRO] Chave 'data' não encontrada na resposta da API.")
        payload = payload["data"]

    if not isinstance(payload, list):
        sys.exit(f"[ERRO] Esperava lista em 'data', mas recebeu {type(payload).__name__}.")

    return payload


def _build_dataframe(agendamentos: list[dict]) -> pd.DataFrame:
    if not agendamentos:
        return pd.DataFrame(columns=COLUNAS)

    rows = []
    for a in agendamentos:
        if a.get("id") == 0:
            continue
        if a.get("status_agendamento") not in STATUS_VALIDOS:
            continue
        if str(a.get("servico") or "").strip().lower() != "visita":
            continue
        rows.append({
            "ID":        a.get("id"),
            "Data/Hora": _fmt_datetime(a.get("start")),
            "Nome":      a.get("cliente"),
            "Unidade":   a.get("atendente"),
            "Serviço":   a.get("servico"),
            "Status":    STATUS_LABELS[a.get("status_agendamento")],
            "Telefone":  None,
        })

    return pd.DataFrame(rows, columns=COLUNAS)


def _fmt_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return value


def _enrich_telefones(df: pd.DataFrame) -> None:
    headers = {"Authorization": f"Bearer {API_TOKEN}", "Accept": "application/json"}
    total   = len(df)

    for i, (idx, row) in enumerate(df.iterrows(), start=1):
        agendamento_id = row["ID"]
        print(f"[INFO] Buscando telefone {i}/{total} (ID {agendamento_id})...", end="\r")

        try:
            resp = requests.get(
                f"{API_BASE_URL}/agendamento-dados/{agendamento_id}",
                headers=headers,
                timeout=API_TIMEOUT,
            )
            resp.raise_for_status()
            dado = resp.json()
            if isinstance(dado, dict) and "data" in dado:
                dado = dado["data"]
            telefone = dado.get("paciente_telefone") if isinstance(dado, dict) else None
            df.at[idx, "Telefone"] = telefone
        except Exception as exc:
            print(f"\n[AVISO] Não foi possível buscar telefone do ID {agendamento_id}: {exc}")

        if i < total:
            time.sleep(0.3)

    print()


def _save_sheets(df: pd.DataFrame, inicio: str, fim: str) -> str:
    creds  = _get_google_creds()
    sheets = build("sheets", "v4", credentials=creds)

    dt_inicio = datetime.strptime(inicio, "%Y-%m-%d").strftime("%d/%m/%Y")
    tab_title = dt_inicio if fim == inicio else (
        f"{dt_inicio} - {datetime.strptime(fim, '%Y-%m-%d').strftime('%d/%m/%Y')}"
    )

    spreadsheet_id = GOOGLE_SHEETS_ID

    # Remove aba existente com o mesmo nome, se houver
    existing = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    pre_requests = []
    for s in existing.get("sheets", []):
        if s["properties"]["title"] == tab_title:
            pre_requests.append({"deleteSheet": {"sheetId": s["properties"]["sheetId"]}})
    if pre_requests:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": pre_requests}
        ).execute()

    # Cria nova aba
    resp = sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": tab_title}}}]},
    ).execute()
    ws_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]

    # Escreve dados (NaN -> "" para evitar JSON inválido)
    data = [COLUNAS] + [
        [("" if (v := row[col]) is None or (isinstance(v, float) and pd.isna(v)) else v)
         for col in COLUNAS]
        for _, row in df.iterrows()
    ]
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_title}'!A1",
        valueInputOption="RAW",
        body={"values": data},
    ).execute()

    # Formata: cabeçalho em negrito, colunas ajustadas, pendentes em amarelo
    batch_requests = [
        {
            "repeatCell": {
                "range": {"sheetId": ws_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        },
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": ws_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": len(COLUNAS),
                }
            }
        },
    ]
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        if row["Status"] in STATUS_PENDENTE:
            batch_requests.append({
                "repeatCell": {
                    "range": {"sheetId": ws_id, "startRowIndex": i, "endRowIndex": i + 1},
                    "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1.0, "green": 1.0, "blue": 0.0}}},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            })
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": batch_requests}
    ).execute()

    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"


def main() -> None:
    _validate_env()

    inicio, fim = _resolve_dates()
    periodo = inicio if inicio == fim else f"{inicio} a {fim}"
    print(f"[INFO] Consultando agendamentos: {periodo}")

    agendamentos = _fetch_agendamentos(inicio, fim)
    total_bruto  = len(agendamentos)

    df    = _build_dataframe(agendamentos)
    total = len(df)

    if total == 0:
        print("[INFO] Nenhum agendamento válido encontrado para o período consultado.")
    else:
        print(f"[INFO] Buscando telefones ({total} agendamentos)...")
        _enrich_telefones(df)

    print("[INFO] Criando planilha no Google Sheets...")
    url = _save_sheets(df, inicio, fim)

    print("-" * 50)
    print(f"Período consultado   : {periodo}")
    print(f"Registros da API     : {total_bruto}")
    print(f"Agendamentos válidos : {total}  (apenas 'Visita'; excluídos bloqueios e status fora de 1/2/3/7/9)")
    print(f"Planilha gerada      : {url}")
    print("-" * 50)


if __name__ == "__main__":
    main()
