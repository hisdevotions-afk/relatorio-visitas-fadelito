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

# ── WhatsApp Business Cloud API (via Gupshup) ─────────────────────────────────
WHATSAPP_API_TOKEN = os.getenv("WHATSAPP_API_TOKEN", "")
WHATSAPP_WABA_ID = os.getenv("WHATSAPP_WABA_ID", "")
WHATSAPP_SOURCE_NUMBER = os.getenv("WHATSAPP_SOURCE_NUMBER", "")
WHATSAPP_APP_NAME = os.getenv("WHATSAPP_APP_NAME", "")
SDR_NUMBER = os.getenv("WHATSAPP_SDR_NUMBER", "")
WHATSAPP_TEMPLATE_NAME = os.getenv("WHATSAPP_TEMPLATE_NAME", "")
WHATSAPP_TEMPLATE_ID = os.getenv("WHATSAPP_TEMPLATE_ID", "")

# ── LLM ───────────────────────────────────────────────────────────────────────
# Dois provedores com failover automático bidirecional (ver llm.py):
# o primário atende; se esgotar a cota, o backup assume — e vice-versa.
LLM_PRIMARY = os.getenv("LLM_PRIMARY", "nvidia").lower()  # "nvidia" ou "groq"

# NVIDIA NIM (OpenAI-compatible)
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")

# Groq (OpenAI-compatible)
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# ── Agendamento ───────────────────────────────────────────────────────────────
VISITA_DURACAO = int(os.getenv("VISITA_DURACAO_MINUTOS", "60"))
SLOT_INICIO = os.getenv("SLOT_INICIO", "09:00")
SLOT_FIM = os.getenv("SLOT_FIM", "16:30")

# ── MODO TESTE ────────────────────────────────────────────────────────────────
MODO_TESTE = os.getenv("MODO_TESTE", "false").lower() == "true"
WHATSAPP_TESTE_NUMBER = os.getenv("WHATSAPP_TESTE_NUMBER", "")

# ── OVERRIDE DE DATA (dd/mm/yyyy) — força aba específica, útil para testes ───
DATA_OVERRIDE = os.getenv("DATA_OVERRIDE", "")

# ── Segurança — endpoints internos (/disponibilidade, /buscar-lead) ───────────
# Quando definida, server.py exige o header X-API-KEY nessas rotas.
# Deixe vazio para desativar a proteção (p.ex., durante transição).
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
