"""Cérebro do agente: LangChain + Groq (ou Claude em produção)."""
import json as _json
import re
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import config

# ─────────────────────────────────────────────────────────────────────────────
# Para trocar para Claude em produção, substitua APENAS esta linha:
#   from langchain_anthropic import ChatAnthropic
#   _criar_llm = lambda: ChatAnthropic(model="claude-sonnet-4-20250514")
# ─────────────────────────────────────────────────────────────────────────────
def _criar_llm():  # linha única a trocar
    from langchain_groq import ChatGroq
    return ChatGroq(model="llama-3.3-70b-versatile", api_key=config.GROQ_API_KEY)


_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = _criar_llm()
    return _llm

import disponibilidade
import gendo
import logger
import prompts
import rag

# Histórico em memória por ID do agendamento (chave: str)
_conversas: dict[str, list] = {}


def _historico(lead_id: str) -> list:
    if lead_id not in _conversas:
        _conversas[lead_id] = []
    return _conversas[lead_id]


def carregar_historico(lead_id: str, json_str: str) -> None:
    """Restaura histórico de conversa a partir do JSON salvo no Sheets (coluna L)."""
    if not json_str:
        return
    try:
        entries = _json.loads(json_str)
    except Exception:
        return
    hist = _historico(lead_id)
    hist.clear()
    for e in entries:
        role, content = e.get("role", ""), e.get("content", "")
        if role == "assistant":
            hist.append(AIMessage(content=content))
        elif role == "user":
            hist.append(HumanMessage(content=content))


def serializar_historico(lead_id: str) -> str:
    """Serializa histórico em memória para JSON (para persistir no Sheets)."""
    hist = _historico(lead_id)
    entries = []
    for msg in hist:
        if isinstance(msg, AIMessage):
            entries.append({"role": "assistant", "content": msg.content})
        elif isinstance(msg, HumanMessage):
            entries.append({"role": "user", "content": msg.content})
    return _json.dumps(entries, ensure_ascii=False)


def registrar_mensagem_agente(lead_id: str, mensagem: str) -> None:
    """Adiciona mensagem do agente ao histórico (inclusive tentativa 1 que não passa pelo LLM)."""
    _historico(lead_id).append(AIMessage(content=mensagem))


def registrar_mensagem_cliente(lead_id: str, mensagem: str) -> None:
    """Adiciona resposta do cliente ao histórico."""
    _historico(lead_id).append(HumanMessage(content=mensagem))


def _invocar_llm(system: str, user: str, lead_id: str) -> str:
    hist = _historico(lead_id)
    msgs = [SystemMessage(content=system)] + hist + [HumanMessage(content=user)]
    resp = _get_llm().invoke(msgs)
    conteudo = resp.content.strip()
    hist.append(HumanMessage(content=user))
    hist.append(AIMessage(content=conteudo))
    return conteudo


def _invocar_llm_instrucao(system: str, instrucao: str, lead_id: str) -> str:
    """Invoca o LLM com o histórico real da conversa + instrução interna.

    A instrução NÃO entra no histórico — só a resposta gerada. Assim a
    coluna L fica fiel ao que cliente e agente realmente trocaram.
    """
    hist = _historico(lead_id)
    msgs = [SystemMessage(content=system)] + hist + [HumanMessage(content=instrucao)]
    resp = _get_llm().invoke(msgs)
    conteudo = resp.content.strip()
    hist.append(AIMessage(content=conteudo))
    return conteudo


def _ultima_mensagem_agente(lead_id: str) -> str:
    hist = _historico(lead_id)
    return next(
        (m.content for m in reversed(hist) if isinstance(m, AIMessage)), ""
    )


def _classificar_resposta(mensagem: str, slots: list[dict], lead_id: str) -> tuple[str, str]:
    """Retorna (categoria, data_info). Não grava histórico de conversa."""
    opcoes_partes = ["1 - Quero reagendar", "2 - Optei por outra escola"]
    if slots:
        opcoes_partes += [f"- {s['label']}" for s in slots]
    opcoes_str = "\n".join(opcoes_partes)
    prompt = prompts.PROMPT_CLASSIFICAR.format(
        opcoes=opcoes_str,
        contexto=_ultima_mensagem_agente(lead_id) or "(nenhuma)",
        mensagem=mensagem,
    )
    resp = _get_llm().invoke([
        SystemMessage(content="Você é um classificador preciso. Seja conciso."),
        HumanMessage(content=prompt),
    ]).content.strip()
    linhas = resp.strip().splitlines()
    categoria = linhas[0].strip()
    data_info = ""
    for linha in linhas[1:]:
        if linha.startswith("DATA:"):
            data_info = linha.replace("DATA:", "").strip()
    return categoria, data_info


def _escolha_de_slot(mensagem: str, slots: list[dict], lead_id: str) -> dict | None:
    """Detecta escolha de slot por número simples (ex.: "1", "2", "3").

    Só vale quando a última mensagem do agente foi a lista de horários —
    fora desse contexto, "1"/"2" são as opções reagendar/recusar do template.
    """
    m = re.fullmatch(r"\s*(\d)\s*[.!]?\s*", mensagem or "")
    if not m or not slots:
        return None
    if "horários disponíveis" not in _ultima_mensagem_agente(lead_id):
        return None
    idx = int(m.group(1)) - 1
    return slots[idx] if 0 <= idx < len(slots) else None


def _encontrar_slot(data_info: str, slots: list[dict]) -> dict | None:
    """Tenta casar data_info com um slot disponível."""
    if not data_info:
        return slots[0] if slots else None

    match = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})", data_info)
    if match:
        try:
            data_iso = datetime.strptime(match.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
            return {"data": data_iso, "horario": match.group(2)}
        except ValueError:
            pass

    for slot in slots:
        if slot["horario"] in data_info or slot["data"] in data_info:
            return slot

    return slots[0] if slots else None


def gerar_mensagem_tentativa(tentativa: int, lead: dict, slots: list[dict]) -> str:
    """Gera o texto da mensagem para a tentativa indicada (1, 2 ou 3)."""
    nome = lead["nome"]
    primeiro_nome = nome.split()[0] if nome else "Cliente"
    unidade = lead["unidade"]
    opcoes_labels = [s["label"] for s in slots]
    while len(opcoes_labels) < 3:
        opcoes_labels.append("(sem disponibilidade)")

    if tentativa == 1:
        return prompts.MENSAGEM_TENTATIVA_1.format(primeiro_nome=primeiro_nome)

    opcoes_str = "\n".join(f"- {o}" for o in opcoes_labels[:3])
    lead_id = str(lead["id"])

    if tentativa == 2:
        user_msg = prompts.PROMPT_TENTATIVA_2.format(
            nome=primeiro_nome,
            data_original=lead["data_hora"],
            unidade=unidade,
            opcoes=opcoes_str,
        )
        return _invocar_llm(rag.SYSTEM_PROMPT_AGENTE, user_msg, f"{lead_id}_t2")

    if tentativa == 3:
        user_msg = prompts.PROMPT_TENTATIVA_3.format(nome=primeiro_nome, opcoes=opcoes_str)
        return _invocar_llm(rag.SYSTEM_PROMPT_AGENTE, user_msg, f"{lead_id}_t3")

    return ""


def processar_resposta_cliente(lead: dict, mensagem_cliente: str) -> dict:
    """Processa a resposta do cliente e retorna dict com ação a tomar.

    Retorna:
        resposta       str   — mensagem a enviar de volta
        status_agente  str   — novo status do lead
        nova_data      str   — data confirmada (se houver)
        notif_sdr      str|None — notificação para o SDR (se houver)
    """
    lead_id = str(lead["id"])
    nome = lead["nome"]
    unidade = lead["unidade"]
    telefone = lead["telefone"]
    slots = disponibilidade.get_slots_disponiveis(3)

    slot_direto = _escolha_de_slot(mensagem_cliente, slots, lead_id)
    if slot_direto:
        categoria = "CONFIRMOU_DATA"
        data_info = (
            datetime.strptime(slot_direto["data"], "%Y-%m-%d").strftime("%d/%m/%Y")
            + " " + slot_direto["horario"]
        )
    else:
        categoria, data_info = _classificar_resposta(mensagem_cliente, slots, lead_id)
    logger.info(f"Lead {lead_id} ({nome}): classificação = {categoria}")

    if "QUER_REAGENDAR" in categoria:
        opcoes_labels = [s["label"] for s in slots]
        while len(opcoes_labels) < 3:
            opcoes_labels.append("(sem disponibilidade)")
        resposta = prompts.MSG_ENVIAR_SLOTS.format(
            opcao_1=opcoes_labels[0],
            opcao_2=opcoes_labels[1],
            opcao_3=opcoes_labels[2],
        )
        registrar_mensagem_agente(lead_id, resposta)
        return {
            "resposta": resposta,
            "status_agente": lead["status_agente"],
            "nova_data": "",
            "notif_sdr": None,
        }

    if "CONFIRMOU_DATA" in categoria:
        slot = _encontrar_slot(data_info, slots)
        nova_data = data_info or (slot["label"] if slot else mensagem_cliente[:50])

        if slot and not config.DRY_RUN:
            try:
                dados = gendo.get_agendamento_dados(lead_id)
                novo = gendo.criar_agendamento(
                    id_paciente=dados.get("id_paciente") or dados.get("paciente_id"),
                    id_responsavel=dados.get("id_responsavel") or dados.get("responsavel_id"),
                    id_servico=dados.get("id_servico") or dados.get("servico_id"),
                    data=slot["data"],
                    horario=slot["horario"],
                )
                gendo.atualizar_status(lead_id, "7")  # 7 = Cancelado (substituído)
                logger.info(f"Novo agendamento criado: ID {novo.get('id')}")
            except Exception as exc:
                logger.aviso(f"Falha ao criar agendamento no Gendo: {exc}")
        elif slot and config.DRY_RUN:
            logger.info(
                f"[DRY-RUN] Seria criado agendamento no Gendo: {slot['data']} {slot['horario']}"
            )

        resposta = prompts.MSG_CONFIRMADO.format(data_hora=nova_data, unidade=unidade)
        maps_link = rag.get_maps_link(unidade)
        if maps_link:
            resposta += f"\n\n📍 Como chegar: {maps_link}"

        registrar_mensagem_agente(lead_id, resposta)
        return {
            "resposta": resposta,
            "status_agente": "reagendado",
            "nova_data": nova_data,
            "notif_sdr": prompts.NOTIF_SDR_REAGENDADO.format(
                nome=nome, data_hora=nova_data, unidade=unidade, telefone=telefone
            ),
        }

    if "QUER_LIGAR" in categoria:
        registrar_mensagem_agente(lead_id, prompts.MSG_QUER_LIGAR)
        return {
            "resposta": prompts.MSG_QUER_LIGAR,
            "status_agente": "reagendado",
            "nova_data": "",
            "notif_sdr": prompts.NOTIF_SDR_LIGAR.format(nome=nome, unidade=unidade, telefone=telefone),
        }

    if "RECUSOU" in categoria:
        registrar_mensagem_agente(lead_id, prompts.MSG_RECUSOU)
        return {
            "resposta": prompts.MSG_RECUSOU,
            "status_agente": "perdido",
            "nova_data": "",
            "notif_sdr": prompts.NOTIF_SDR_RECUSOU.format(nome=nome, telefone=telefone),
        }

    if "QUER_NEGOCIAR" in categoria:
        opcoes_alt = "\n".join(f"🗓 {s['label']}" for s in slots)
        preferencia = data_info or "outro horário"
        msg_neg = _invocar_llm_instrucao(
            rag.SYSTEM_PROMPT_AGENTE,
            f"O lead quer {preferencia}. Ofereça estas alternativas de forma empática "
            f"(máximo 3 linhas):\n{opcoes_alt}",
            lead_id,
        )
        return {
            "resposta": msg_neg,
            "status_agente": lead["status_agente"],
            "nova_data": "",
            "notif_sdr": None,
        }

    # INDEFINIDO — perguntas ou respostas vagas: responde com a base de conhecimento
    resp_indef = _invocar_llm_instrucao(
        rag.SYSTEM_PROMPT_AGENTE,
        "Responda à última mensagem do cliente usando APENAS a base de conhecimento "
        "(nunca invente valores, vagas ou horários). Se for pergunta, responda de forma "
        "precisa e curta; depois redirecione gentilmente para o reagendamento da visita. "
        "Máximo 4 linhas, estilo WhatsApp.",
        lead_id,
    )
    return {
        "resposta": resp_indef,
        "status_agente": lead["status_agente"],
        "nova_data": "",
        "notif_sdr": None,
    }
