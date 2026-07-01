"""Calcula slots livres nos próximos dias úteis via API Gendo."""
import unicodedata
from datetime import date, datetime, timedelta

import config
import feriados
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
        if d.weekday() < 5 and not feriados.is_feriado(d):  # segunda–sexta, sem feriados
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


def slots_livres(unidade: str = "", dias: int = 5) -> list[dict]:
    """Retorna TODOS os slots livres (ordem cronológica) nos próximos `dias` dias úteis.

    Formato: [{"data": "2025-05-05", "horario": "09:00", "label": "segunda-feira, 05/05 às 09h00"}]
    """
    slots_do_dia = _gerar_slots_do_dia()
    resultado = []

    for dia in _proximos_dias_uteis(dias):
        ocupados = _horarios_ocupados(dia, unidade)
        dia_semana = DIAS_PT[dia.weekday()]

        for horario in slots_do_dia:
            if horario not in ocupados:
                resultado.append({
                    "data": dia.isoformat(),
                    "horario": horario,
                    "label": f"{dia_semana}, {dia.strftime('%d/%m')} às {horario.replace(':', 'h')}",
                })

    return resultado


def escolher_diversos(slots: list[dict], n_opcoes: int = 3) -> list[dict]:
    """Escolhe até n_opcoes slots espalhados por dias DIFERENTES (1º livre de cada dia).

    Evita oferecer 3 horários do mesmo dia — se o dia não servir ao lead,
    nenhuma opção serviria. Só repete dia quando não há dias distintos suficientes.
    """
    por_dia: dict[str, list[dict]] = {}
    for s in slots:
        por_dia.setdefault(s["data"], []).append(s)

    escolhidos: list[dict] = []
    rodada = 0
    while len(escolhidos) < n_opcoes and any(rodada < len(v) for v in por_dia.values()):
        for data in sorted(por_dia):
            if rodada < len(por_dia[data]) and len(escolhidos) < n_opcoes:
                escolhidos.append(por_dia[data][rodada])
        rodada += 1

    return sorted(escolhidos, key=lambda s: (s["data"], s["horario"]))


def get_slots_disponiveis(n_opcoes: int = 3, unidade: str = "") -> list[dict]:
    """Retorna até n_opcoes slots livres em dias diversificados para a unidade indicada."""
    return escolher_diversos(slots_livres(unidade), n_opcoes)
