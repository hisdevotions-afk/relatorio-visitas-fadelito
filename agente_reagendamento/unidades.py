"""Registro de unidades Fadelito a partir da API Gendo.

No Gendo, cada unidade é um "responsável" (`atendente` = nome da unidade,
`resp`/`id_responsavel` = id da agenda). Esse id é o que define em qual unidade
o agendamento cai ao criar. Este módulo descobre o mapeamento
`atendente -> id_responsavel` dinamicamente (cacheado) e resolve nomes de
unidade (livres ou canônicos) para o par (atendente_gendo, id_responsavel).
"""
import time
import unicodedata
from datetime import date, timedelta

import gendo
import logger

_CACHE: dict[str, int] | None = None
_CACHE_TS = 0.0
_TTL = 3600.0  # 1h


def _norm(s: str) -> str:
    """Normaliza p/ comparação: minúsculas, sem acento, abreviação 'V.'→'Vila'."""
    base = "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    ).lower().strip()
    base = base.replace("v.", "vila")
    return " ".join(base.split())


def normalizar(s: str) -> str:
    """Normalização pública p/ comparar nomes de unidade vindos de fontes diferentes
    (Sheets vs Gendo) sem depender de igualdade exata de string."""
    return _norm(s)


def _carregar() -> dict[str, int]:
    """Lê agendamentos recentes e extrai {atendente: id_responsavel}."""
    ini = (date.today() - timedelta(days=60)).isoformat()
    fim = (date.today() + timedelta(days=30)).isoformat()
    reg: dict[str, int] = {}
    for a in gendo.get_agendamentos(ini, fim):
        atendente = a.get("atendente")
        resp = a.get("resp")
        if atendente and resp is not None and a.get("id"):
            reg[atendente] = resp
    return reg


def _registro() -> dict[str, int]:
    global _CACHE, _CACHE_TS
    if _CACHE is None or (time.time() - _CACHE_TS) > _TTL:
        try:
            novo = _carregar()
            if novo:
                _CACHE, _CACHE_TS = novo, time.time()
        except Exception as exc:
            logger.aviso(f"Falha ao carregar registro de unidades da Gendo: {exc}")
            if _CACHE is None:
                _CACHE = {}
    return _CACHE or {}


def resolver(nome: str) -> tuple[str | None, int | None]:
    """Resolve um nome de unidade para (atendente_gendo, id_responsavel).

    Casa de forma acento/abreviação-insensível. Se o registro não estiver
    disponível (Gendo fora), devolve (nome, None) como melhor esforço — assim o
    fluxo segue, apenas sem o id da agenda.
    """
    if not nome:
        return None, None
    reg = _registro()
    if not reg:
        return nome, None

    alvo = _norm(nome)

    # 1) casamento exato
    for atendente, resp in reg.items():
        if _norm(atendente) == alvo:
            return atendente, resp

    # 2) substring em qualquer direção (ex.: "Boa Vista" ⊂ "Alto da Boa Vista")
    candidatos = [
        (at, resp) for at, resp in reg.items()
        if alvo in _norm(at) or _norm(at) in alvo
    ]
    if candidatos:
        candidatos.sort(key=lambda x: len(_norm(x[0])))  # mais específico/curto
        return candidatos[0]

    return None, None


def id_responsavel(nome: str) -> int | None:
    """Atalho: retorna apenas o id_responsavel (id da agenda) da unidade."""
    return resolver(nome)[1]
