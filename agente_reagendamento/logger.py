"""Logger simples com formato padronizado."""
import sys
from datetime import datetime
from pathlib import Path

_LOG_DIR = Path(__file__).parent / "logs"
_LOG_CONVERSA = _LOG_DIR / "conversas.log"

# Força UTF-8 no stdout/stderr para suportar emojis no Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def log(nivel: str, mensagem: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{ts}] [{nivel}] {mensagem}"
    destino = sys.stderr if nivel == "ERRO" else sys.stdout
    print(linha, file=destino)


def info(mensagem: str) -> None:
    log("INFO", mensagem)


def aviso(mensagem: str) -> None:
    log("AVISO", mensagem)


def erro(mensagem: str) -> None:
    log("ERRO", mensagem)


def log_conversa(lead_id: str, nome: str, direcao: str, mensagem: str) -> None:
    """Grava mensagem de conversa em ./logs/conversas.log."""
    _LOG_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    linha = f"[{ts}] [{lead_id}] [{nome}] [{direcao}] {mensagem}\n"
    with open(_LOG_CONVERSA, "a", encoding="utf-8") as f:
        f.write(linha)
