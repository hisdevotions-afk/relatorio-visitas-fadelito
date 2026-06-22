"""Feriados nacionais brasileiros — fonte única usada por disponibilidade.py e sheets.py."""
from datetime import date, timedelta
from functools import lru_cache

# Feriados fixos: (dia, mês)
_FIXOS: frozenset[tuple[int, int]] = frozenset({
    (1, 1),   # Confraternização Universal
    (21, 4),  # Tiradentes
    (1, 5),   # Dia do Trabalhador
    (7, 9),   # Independência do Brasil
    (12, 10), # Nossa Senhora Aparecida
    (2, 11),  # Finados
    (15, 11), # Proclamação da República
    (20, 11), # Consciência Negra
    (25, 12), # Natal
})


def _pascoa(ano: int) -> date:
    """Algoritmo de Meeus/Jones/Butcher."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


@lru_cache(maxsize=8)
def feriados_do_ano(ano: int) -> frozenset[date]:
    """Retorna conjunto de feriados nacionais (fixos + móveis via Páscoa) para o ano."""
    pascoa = _pascoa(ano)
    moveis = {
        pascoa - timedelta(days=48),  # Carnaval — segunda-feira
        pascoa - timedelta(days=47),  # Carnaval — terça-feira
        pascoa - timedelta(days=2),   # Sexta-Feira da Paixão
        pascoa + timedelta(days=60),  # Corpus Christi
    }
    return frozenset({date(ano, mes, dia) for dia, mes in _FIXOS} | moveis)


def is_feriado(d: date) -> bool:
    return d in feriados_do_ano(d.year)
