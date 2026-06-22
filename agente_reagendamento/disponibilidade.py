"""Calcula slots livres nos próximos dias úteis via API Gendo."""
import unicodedata
from datetime import date, datetime, timedelta
from functools import lru_cache

import config
import gendo
import logger

DIAS_PT = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira"]

# Status que indicam horário ocupado na API
STATUS_OCUPADOS = {"1", "2", "6"}


def _norm_unidade(s: str) -> str:
    """Normaliza nome de unidade para comparação fuzzy (sem acento, sem 'Fadelito', V.→Vila)."""
    base = "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    ).lower()
    base = base.replace("fadelito", "").replace("v.", "vila").strip()
    return " ".join(base.split())

# Feriados fixos nacionais: (dia, mês)
_FERIADOS_FIXOS = {
    (1, 1),   # Confraternização Universal
    (21, 4),  # Tiradentes
    (1, 5),   # Dia do Trabalhador
    (7, 9),   # Independência do Brasil
    (12, 10), # Nossa Senhora Aparecida
    (2, 11),  # Finados
    (15, 11), # Proclamação da República
    (25, 12), # Natal
}


def _pascoa(ano: int) -> date:
    """Calcula a data da Páscoa pelo algoritmo de Butcher."""
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


@lru_cache(maxsize=8)
def _feriados_do_ano(ano: int) -> frozenset[date]:
    """Retorna conjunto de feriados nacionais (fixos + móveis) para o ano."""
    fixos = {date(ano, mes, dia) for dia, mes in _FERIADOS_FIXOS}
    pascoa = _pascoa(ano)
    moveis = {
        pascoa - timedelta(days=48),  # Carnaval — segunda-feira
        pascoa - timedelta(days=47),  # Carnaval — terça-feira
        pascoa - timedelta(days=2),   # Sexta-Feira da Paixão
        pascoa + timedelta(days=60),  # Corpus Christi
    }
    return frozenset(fixos | moveis)


def _e_feriado(d: date) -> bool:
    return d in _feriados_do_ano(d.year)


def _gerar_slots_do_dia() -> list[str]:
    """Gera lista de horários de início a partir das variáveis de ambiente."""
    h_i, m_i = map(int, config.SLOT_INICIO.split(":"))
    h_f, m_f = map(int, config.SLOT_FIM.split(":"))
    inicio_min = h_i * 60 + m_i
    fim_min = h_f * 60 + m_f

    slots = []
    atual = inicio_min
    while atual <= fim_min:
        slots.append(f"{atual // 60:02d}:{atual % 60:02d}")
        atual += config.VISITA_DURACAO
    return slots


def _proximos_dias_uteis(n: int = 5) -> list[date]:
    dias = []
    d = date.today() + timedelta(days=1)
    while len(dias) < n:
        if d.weekday() < 5 and not _e_feriado(d):  # segunda–sexta, sem feriados
            dias.append(d)
        d += timedelta(days=1)
    return dias


def _horarios_ocupados(dia: date, unidade: str = "") -> set[str]:
    """Retorna conjunto de horários (HH:MM) já ocupados ou bloqueados no dia.

    Se `unidade` for fornecida, considera apenas agendamentos dessa unidade
    (campo `atendente` na API Gendo). O match é bidirecional e normalizado
    (sem acento, sem prefixo 'Fadelito', 'V.'→'Vila') para lidar com divergências
    entre o nome no Sheets e o retornado pela API.
    """
    iso = dia.isoformat()
    try:
        agendamentos = gendo.get_agendamentos(iso, iso)
    except Exception as exc:
        logger.aviso(f"Falha ao consultar disponibilidade para {iso}: {exc}")
        return set()

    unidade_norm = _norm_unidade(unidade) if unidade else ""
    ocupados: set[str] = set()
    for a in agendamentos:
        if unidade_norm:
            atendente_norm = _norm_unidade(a.get("atendente") or "")
            if not atendente_norm:
                continue
            # Bidirecional: "osasco" bate tanto em "osasco" quanto em "fadelito osasco"
            if unidade_norm not in atendente_norm and atendente_norm not in unidade_norm:
                continue

        start = a.get("start", "")
        if not start:
            continue
        try:
            hora = datetime.strptime(start[:16], "%Y-%m-%dT%H:%M").strftime("%H:%M")
        except ValueError:
            continue

        status = str(a.get("status_agendamento", ""))
        servico = a.get("servico")

        if status in STATUS_OCUPADOS or servico is None:
            ocupados.add(hora)

    logger.info(f"Disponibilidade {iso} [{unidade_norm or 'todas'}]: {len(agendamentos)} agendamentos, {len(ocupados)} ocupados: {sorted(ocupados)}")
    return ocupados


def get_slots_disponiveis(n_opcoes: int = 3, unidade: str = "") -> list[dict]:
    """Retorna até n_opcoes slots livres nos próximos 5 dias úteis para a unidade indicada.

    Formato: [{"data": "2025-05-05", "horario": "09:00", "label": "segunda-feira, 05/05 às 09h"}]
    """
    slots_do_dia = _gerar_slots_do_dia()
    dias = _proximos_dias_uteis(5)
    resultado = []

    for dia in dias:
        ocupados = _horarios_ocupados(dia, unidade)
        dia_semana = DIAS_PT[dia.weekday()]

        for horario in slots_do_dia:
            if horario not in ocupados:
                resultado.append({
                    "data": dia.isoformat(),
                    "horario": horario,
                    "label": f"{dia_semana}, {dia.strftime('%d/%m')} às {horario[:2]}h",
                })
                if len(resultado) >= n_opcoes:
                    return resultado

    return resultado
