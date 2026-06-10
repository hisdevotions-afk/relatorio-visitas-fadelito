"""Teste manual de regressão: simula cenários de conversa do agente em dry-run.

Não envia WhatsApp, não grava Sheets, não chama Gendo (slots mockados).
Usa o LLM real (Groq) para classificação e respostas RAG.
"""
import config

config.set_dry_run(True)

import agente
import disponibilidade
import prompts

SLOTS_MOCK = [
    {"data": "2026-06-11", "horario": "09:00", "label": "quinta-feira, 11/06 às 09h00"},
    {"data": "2026-06-11", "horario": "14:00", "label": "quinta-feira, 11/06 às 14h00"},
    {"data": "2026-06-12", "horario": "10:00", "label": "sexta-feira, 12/06 às 10h00"},
]
disponibilidade.get_slots_disponiveis = lambda n=3: SLOTS_MOCK[:n]

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
turno(l, "pode ser o primeiro horário")

print("\n" + "=" * 70)
print("CENÁRIO 4 — '1' DEPOIS dos slots (deve ser CONFIRMOU_DATA, não loop)")
l = novo_lead()
turno(l, "1")
turno(l, "1")

print("\n" + "=" * 70)
print("CENÁRIO 4b — '2' DEPOIS dos slots (deve confirmar o 2º horário)")
l = novo_lead()
turno(l, "1")
turno(l, "2")

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
print("HISTÓRICO SERIALIZADO DO CENÁRIO 1 (verifica coluna L limpa):")
print(agente.serializar_historico("T1"))
