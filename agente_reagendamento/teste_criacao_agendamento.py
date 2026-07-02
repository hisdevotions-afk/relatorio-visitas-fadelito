"""Teste de regressão: valida os parâmetros REAIS enviados à Gendo ao criar um
agendamento (dry_run=False, mas gendo.* mockado — nenhuma chamada de rede).

Cobre o ponto mais crítico do fluxo: `id_responsavel` é o que define em qual
unidade o agendamento cai (ver CLAUDE.md). Errar esse valor bota o agendamento
na agenda errada mesmo com a mensagem certa pro lead.
"""
import config

config.set_dry_run(False)  # precisa estar OFF p/ o bloco de criação real executar

import agente
import disponibilidade
import gendo
import prompts
import unidades

# Registro fixo de unidade -> id_responsavel (valores reais confirmados na Gendo)
unidades._CACHE = {"Marajoara": 25, "Campo Belo": 19}
import time as _time
unidades._CACHE_TS = _time.time()

SLOTS_POR_UNIDADE = {
    "marajoara": [
        {"data": "2026-06-11", "horario": "09:00", "label": "quinta-feira, 11/06 às 09h00"},
        {"data": "2026-06-12", "horario": "10:00", "label": "sexta-feira, 12/06 às 10h00"},
        {"data": "2026-06-15", "horario": "09:00", "label": "segunda-feira, 15/06 às 09h00"},
    ],
    "campo belo": [
        {"data": "2026-06-11", "horario": "14:00", "label": "quinta-feira, 11/06 às 14h00"},
        {"data": "2026-06-12", "horario": "15:00", "label": "sexta-feira, 12/06 às 15h00"},
        {"data": "2026-06-15", "horario": "13:00", "label": "segunda-feira, 15/06 às 13h00"},
    ],
}


def _fake_slots_livres(unidade: str = "", dias: int = 5):
    chave = unidades.normalizar(unidade) if unidade else "marajoara"
    return SLOTS_POR_UNIDADE.get(chave, SLOTS_POR_UNIDADE["marajoara"])


disponibilidade.slots_livres = _fake_slots_livres

# Dados do agendamento original — id_responsavel 25 = Marajoara (a unidade
# originalmente agendada). Se o lead NÃO trocar de unidade, é este valor que
# deve ir pra Gendo sem alteração.
gendo.get_agendamento_dados = lambda _id: {
    "id_paciente": 555, "id_servico": 7, "id_responsavel": 25,
}

CHAMADAS_CRIAR: list[dict] = []
CHAMADAS_STATUS: list[tuple] = []


def _fake_criar_agendamento(**kwargs):
    CHAMADAS_CRIAR.append(kwargs)
    return {"id": 999000 + len(CHAMADAS_CRIAR)}


def _fake_atualizar_status(agendamento_id, status):
    CHAMADAS_STATUS.append((agendamento_id, status))
    return {"ok": True}


gendo.criar_agendamento = _fake_criar_agendamento
gendo.atualizar_status = _fake_atualizar_status

_contador = [0]


def novo_lead(unidade="Marajoara") -> dict:
    _contador[0] += 1
    lead_id = f"B{_contador[0]}"
    lead = {
        "id": lead_id, "data_hora": "09/06/2026 16:30",
        "nome": "Roberto (TESTE)", "unidade": unidade,
        "telefone": "5511989171391", "status_agente": "tentativa_1",
    }
    agente.registrar_mensagem_agente(
        lead_id, prompts.MENSAGEM_TENTATIVA_1.format(primeiro_nome="Roberto")
    )
    return lead


def turno(lead: dict, msg: str) -> dict:
    lead_id = str(lead["id"])
    agente.registrar_mensagem_cliente(lead_id, msg)
    r = agente.processar_resposta_cliente(lead, msg)
    print(f"  CLIENTE: {msg}")
    print(f"  AGENTE [{r['status_agente']}]: {r['resposta'][:90]}...")
    lead["status_agente"] = r["status_agente"]
    if r.get("unidade_alvo"):
        lead["unidade_alvo"] = r["unidade_alvo"]
    return r


print("=" * 70)
print("CASO 1 — Confirma na MESMA unidade (sem troca): id_responsavel = original (25)")
l = novo_lead("Marajoara")
turno(l, "1")
r = turno(l, "pode ser o primeiro horário")
assert r["status_agente"] == "reagendado", r
chamada = CHAMADAS_CRIAR[-1]
assert chamada["id_responsavel"] == 25, f"esperava id_responsavel=25 (Marajoara), veio {chamada}"
assert chamada["id_paciente"] == 555 and chamada["id_servico"] == 7, chamada
assert chamada["data"] == "2026-06-11" and chamada["horario"] == "09:00", chamada
assert CHAMADAS_STATUS[-1] == (l["id"], "7"), "agendamento antigo devia ser cancelado (status 7)"
print("  OK — id_responsavel correto, sem override indevido")

print("\n" + "=" * 70)
print("CASO 2 — Troca de unidade explícita (Campo Belo) e confirma: id_responsavel = 19")
l = novo_lead("Marajoara")
turno(l, "Consigo agendar em outra unidade?")
turno(l, "Campo Belo")
r = turno(l, "pode ser o primeiro horário")
assert r["status_agente"] == "reagendado", r
chamada = CHAMADAS_CRIAR[-1]
assert chamada["id_responsavel"] == 19, (
    f"agendamento caiu na agenda ERRADA — esperava 19 (Campo Belo), veio {chamada}"
)
assert chamada["data"] == "2026-06-11" and chamada["horario"] == "14:00", (
    f"horário não bate com o slot real oferecido da Campo Belo: {chamada}"
)
print("  OK — booking foi pra agenda da unidade nova, não da original")

print("\n" + "=" * 70)
print("CASO 3 — Negociação que já nomeia outra unidade em uma tacada só "
      "(\"horário de tarde na Campo Belo\"): id_responsavel = 19")
l = novo_lead("Marajoara")
turno(l, "1")
turno(l, "Tem algum horário na Campo Belo?")
r = turno(l, "pode ser o primeiro horário")
assert r["status_agente"] == "reagendado", r
chamada = CHAMADAS_CRIAR[-1]
assert chamada["id_responsavel"] == 19, (
    f"negociação com unidade nova não redirecionou a criação pra agenda certa: {chamada}"
)
print("  OK — reroteamento de QUER_NEGOCIAR com unidade nova também acerta o id_responsavel")

print("\n" + "=" * 70)
print(f"✅ {len(CHAMADAS_CRIAR)} agendamentos criados nos testes, todos com id_responsavel correto.")
