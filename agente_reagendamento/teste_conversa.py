"""Teste manual de regressão: simula cenários de conversa do agente em dry-run.

Não envia WhatsApp, não grava Sheets, não chama Gendo (slots mockados).
Usa o LLM real (Groq) para classificação e respostas RAG.
"""
import config

config.set_dry_run(True)

import agente
import disponibilidade
import prompts

# Pool completo (vários dias) — get_slots_disponiveis deriva dele via escolher_diversos
SLOTS_MOCK = [
    {"data": "2026-06-11", "horario": "09:00", "label": "quinta-feira, 11/06 às 09h00"},
    {"data": "2026-06-11", "horario": "14:00", "label": "quinta-feira, 11/06 às 14h00"},
    {"data": "2026-06-12", "horario": "10:00", "label": "sexta-feira, 12/06 às 10h00"},
    {"data": "2026-06-12", "horario": "15:00", "label": "sexta-feira, 12/06 às 15h00"},
    {"data": "2026-06-15", "horario": "09:00", "label": "segunda-feira, 15/06 às 09h00"},
]
disponibilidade.slots_livres = lambda unidade="", dias=5: SLOTS_MOCK

# As 3 opções exibidas devem cair em 3 dias DIFERENTES (erro histórico: mesmo dia)
_top3 = disponibilidade.get_slots_disponiveis(3)
assert len({s["data"] for s in _top3}) == 3, f"slots exibidos não diversificam dias: {_top3}"

_contador = [0]


def novo_lead() -> dict:
    _contador[0] += 1
    lead_id = f"T{_contador[0]}"
    lead = {
        "row_index": 99, "aba": "09/06/2026",
        "id": lead_id, "data_hora": "09/06/2026 16:30",
        "nome": "Roberto (TESTE)", "unidade": "Campinas",
        "servico": "Visita", "status": "Cancelado",
        "telefone": "5511989171391",
        "status_agente": "tentativa_1", "tentativas": "1",
        "ultima_tentativa": "", "nova_data": "", "log_conversa": "",
    }
    # Semeia o histórico com a mensagem de template (tentativa 1)
    agente.registrar_mensagem_agente(
        lead_id, prompts.MENSAGEM_TENTATIVA_1.format(primeiro_nome="Roberto")
    )
    return lead


def turno(lead: dict, msg: str) -> dict:
    lead_id = str(lead["id"])
    agente.registrar_mensagem_cliente(lead_id, msg)
    r = agente.processar_resposta_cliente(lead, msg)
    print(f"\n  CLIENTE: {msg}")
    print(f"  AGENTE [{r['status_agente']}]: {r['resposta']}")
    if r["notif_sdr"]:
        print(f"  (notif SDR: {r['notif_sdr']})")
    lead["status_agente"] = r["status_agente"]
    return r


print("=" * 70)
print("CENÁRIO 1 — Pergunta sobre preço (INDEFINIDO + RAG, não pode inventar)")
l = novo_lead()
turno(l, "Oi! Antes de remarcar, quanto custa a mensalidade do berçário?")
turno(l, "Entendi. E a alimentação tá inclusa?")
turno(l, "Ah legal, então quero remarcar sim")

print("\n" + "=" * 70)
print("CENÁRIO 2 — Pergunta sobre funcionamento/turmas (RAG)")
l = novo_lead()
turno(l, "Vocês têm período integral? Meu filho tem 1 ano e fico até tarde no trabalho")

print("\n" + "=" * 70)
print("CENÁRIO 3 — Fluxo completo: 1 → escolhe slot por posição")
l = novo_lead()
turno(l, "1")
r = turno(l, "pode ser o primeiro horário")
assert r["status_agente"] == "reagendado", f"esperava reagendado, veio {r['status_agente']}"

print("\n" + "=" * 70)
print("CENÁRIO 4 — '1' DEPOIS dos slots (deve ser CONFIRMOU_DATA, não loop)")
l = novo_lead()
turno(l, "1")
turno(l, "1")

print("\n" + "=" * 70)
print("CENÁRIO 4b — '2' DEPOIS dos slots (deve confirmar o 2º horário)")
l = novo_lead()
turno(l, "1")
r = turno(l, "2")
assert r["status_agente"] == "reagendado" and "12/06" in r["nova_data"], r

print("\n" + "=" * 70)
print("CENÁRIO 4c — '2' na PRIMEIRA resposta (deve ser RECUSOU)")
l = novo_lead()
turno(l, "2")

print("\n" + "=" * 70)
print("CENÁRIO 5 — Negociação de horário fora dos slots")
l = novo_lead()
turno(l, "1")
turno(l, "esses horários não dão pra mim, só consigo sábado de manhã")

print("\n" + "=" * 70)
print("CENÁRIO 6 — Pergunta fora do escopo / endereço de outra unidade")
l = novo_lead()
turno(l, "Vocês têm unidade em Osasco? Qual o endereço de lá?")

print("\n" + "=" * 70)
print("CENÁRIO 7 — Recusa educada")
l = novo_lead()
turno(l, "Oi, agradeço o contato mas acabamos fechando com outra escola perto de casa")

print("\n" + "=" * 70)
print("CENÁRIO 8 — Troca de unidade (slots reais da nova unidade + confirma lá)")
l = novo_lead()
turno(l, "Consigo agendar visita em outra unidade?")   # sem dizer qual → pergunta
turno(l, "Tenho interesse na Aclimação")               # define unidade_alvo
l["unidade_alvo"] = "Aclimação"  # simula persistência da coluna M entre rodadas
turno(l, "pode ser o primeiro horário")                # confirma NA Aclimação

print("\n" + "=" * 70)
print("CENÁRIO 9 — Negocia DIA específico (sexta) e confirma slot fora do top-3")
l = novo_lead()
turno(l, "1")
r = turno(l, "esses horários não dão pra mim, tem algum na sexta à tarde?")
assert "15h00" in r["resposta"], f"negociação não ofereceu o slot de sexta 15h: {r['resposta']}"
r = turno(l, "pode ser sexta às 15h")
assert r["status_agente"] == "reagendado" and "15" in r["nova_data"], r

print("\n" + "=" * 70)
print("CENÁRIO 10 — 'o segundo horário' por extenso (ordinal ≠ segunda-feira)")
l = novo_lead()
turno(l, "1")
r = turno(l, "pode ser o segundo horário")
assert r["status_agente"] == "reagendado" and "12/06" in r["nova_data"], r

print("\n" + "=" * 70)
print("CENÁRIO 11b — '2' após tentativa 2/3 parafraseada pelo LLM (bug real: "
      "vinha classificando como RECUSOU por não dizer 'horários disponíveis')")
l = novo_lead()
# Não passa pelo gerador de tentativa — simula o texto que o LLM realmente
# mandou numa conversa real (paráfrase livre, lista numerada, sem a frase
# fixa "horários disponíveis" e sem reproduzir os labels ao pé da letra).
agente.registrar_mensagem_agente(l["id"], (
    "Oi, Roberto! Vi que você tinha uma visita agendada, mas acabou não "
    "conseguindo vir. Ainda faz sentido conhecer a escola?\n\n"
    "Tenho estas opções disponíveis:\n"
    "1) quinta-feira, 11/06 às 09h\n"
    "2) sexta-feira, 12/06 às 10h\n"
    "3) segunda-feira, 15/06 às 09h\n\n"
    "Qual funciona melhor pra você?"
))
r = turno(l, "2")
assert r["status_agente"] == "reagendado", (
    f"lead escolheu o 2º horário mas foi tratado como recusa: {r}"
)
assert "12/06" in r["nova_data"], r

print("\n" + "=" * 70)
print("CENÁRIO 11 — Gendo FORA DO AR na criação (não pode confirmar ao lead)")
import gendo
config.set_dry_run(False)
_orig_dados = gendo.get_agendamento_dados
def _gendo_fora(_id):
    raise RuntimeError("Gendo fora do ar (simulado)")
gendo.get_agendamento_dados = _gendo_fora
l = novo_lead()
turno(l, "1")
r = turno(l, "1")
assert r["status_agente"] == "transferido_sdr", f"falha do Gendo deveria transferir ao SDR: {r}"
assert "confirmada" not in r["resposta"].lower(), f"confirmou visita inexistente: {r['resposta']}"
gendo.get_agendamento_dados = _orig_dados
config.set_dry_run(True)

print("\n" + "=" * 70)
print("HISTÓRICO SERIALIZADO DO CENÁRIO 1 (verifica coluna L limpa):")
print(agente.serializar_historico("T1"))

print("\n✅ Todos os asserts determinísticos passaram.")
