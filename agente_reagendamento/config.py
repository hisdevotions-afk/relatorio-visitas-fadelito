"""Configurações compartilhadas e flag de dry-run."""
import os
from dotenv import load_dotenv

load_dotenv()

# Flag global de dry-run — alterada por main.py antes do processamento
DRY_RUN: bool = False


def set_dry_run(value: bool) -> None:
    global DRY_RUN
    DRY_RUN = value


# ── Gendo ─────────────────────────────────────────────────────────────────────
API_BASE_URL = os.getenv("API_BASE_URL", "").rstrip("/")
API_TOKEN = os.getenv("API_TOKEN", "")
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "30"))

# ── Google Sheets ─────────────────────────────────────────────────────────────
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# ── WhatsApp Z-API ────────────────────────────────────────────────────────────
ZAPI_INSTANCE_ID = os.getenv("ZAPI_INSTANCE_ID", "")
ZAPI_TOKEN = os.getenv("ZAPI_TOKEN", "")
ZAPI_CLIENT_TOKEN = os.getenv("ZAPI_CLIENT_TOKEN", "")
SDR_NUMBER = os.getenv("WHATSAPP_SDR_NUMBER", "")

# ── LLM ───────────────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# ── Agendamento ───────────────────────────────────────────────────────────────
VISITA_DURACAO = int(os.getenv("VISITA_DURACAO_MINUTOS", "60"))
SLOT_INICIO = os.getenv("SLOT_INICIO", "09:00")
SLOT_FIM = os.getenv("SLOT_FIM", "16:30")

# ── MODO TESTE ────────────────────────────────────────────────────────────────
MODO_TESTE = os.getenv("MODO_TESTE", "false").lower() == "true"
WHATSAPP_TESTE_NUMBER = os.getenv("WHATSAPP_TESTE_NUMBER", "")

# ── OVERRIDE DE DATA (dd/mm/yyyy) — força aba específica, útil para testes ───
DATA_OVERRIDE = os.getenv("DATA_OVERRIDE", "")
