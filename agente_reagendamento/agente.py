"""Cérebro do agente: LangChain + Groq (ou Claude em produção)."""
import json as _json
import re
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import config

# LLM com failover bidirecional entre provedores (NVIDIA NIM + Groq) — ver llm.py
import llm

import disponibilidade
import gendo
import logger
import prompts
import rag
import unidades

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


# Reexporta a exceção do módulo llm para os callers existentes neste arquivo
LLMIndisponivel = llm.LLMIndisponivel


def _invocar_llm(system: str, user: str, lead_id: str) -> str:
    hist = _historico(lead_id)
    msgs = [SystemMessage(content=system)] + hist + [HumanMessage(content=user)]
    conteudo = llm.invoke(msgs).strip()
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
    conteudo = llm.invoke(msgs).strip()
    hist.append(AIMessage(content=conteudo))
    return conteudo


def _ultima_mensagem_agente(lead_id: str) -> str:
    hist = _historico(lead_id)
    return next(
        (m.content for m in reversed(hist) if isinstance(m, AIMessage)), ""
    )


def _classificar_deterministico(mensagem: str, lead_id: str) -> str | None:
    """Classifica respostas óbvias SEM depender do LLM (caminho crítico à prova de falha).

    Cobre o fluxo principal do template (1 = reagendar, 2 = recusou), que é a
    resposta mais comum e NUNCA pode ficar sem retorno por queda do LLM.
    """
    m = re.fullmatch(r"\s*([12])\s*[.!]?\s*", mensagem or "")
    if not m:
        return None
    # só vale como opção do template se a última fala do agente NÃO foi a lista de horários
    if "horários disponíveis" in _ultima_mensagem_agente(lead_id):
        return None
    return "QUER_REAGENDAR" if m.group(1) == "1" else "RECUSOU"


def _classificar_resposta(mensagem: str, slots: list[dict], lead_id: str) -> tuple[str, str]:
    """Retorna (categoria, data_info). Não grava histórico de conversa.

    Tenta primeiro a classificação determinística (sem LLM); se não casar, usa o
    LLM com retry; se o LLM cair, devolve INDEFINIDO para o caminho de fallback.
    """
    deterministico = _classificar_deterministico(mensagem, lead_id)
    if deterministico:
        return deterministico, ""

    opcoes_partes = ["1 - Quero reagendar", "2 - Optei por outra escola"]
    if slots:
        opcoes_partes += [f"- {s['label']}" for s in slots]
    opcoes_str = "\n".join(opcoes_partes)
    prompt = prompts.PROMPT_CLASSIFICAR.format(
        opcoes=opcoes_str,
        contexto=_ultima_mensagem_agente(lead_id) or "(nenhuma)",
        mensagem=mensagem,
    )
    try:
        resp = llm.invoke([
            SystemMessage(content="Você é um classificador preciso. Seja conciso."),
            HumanMessage(content=prompt),
        ], max_tokens=64, temperature=0.0).strip()
    except LLMIndisponivel:
        return "INDEFINIDO", ""
    linhas = resp.strip().splitlines()
    categoria = linhas[0].strip()
    data_info = ""
    for linha in linhas[1:]:
        if linha.startswith("DATA:"):
            data_info = linha.replace("DATA:", "").strip()
    return categoria, data_info


_DIAS_IDX = {
    "segunda-feira": 0, "terca": 1, "terça": 1, "quarta": 2,
    "quinta": 3, "sexta": 4, "sabado": 5, "sábado": 5, "domingo": 6,
}


def _dia_semana_pedido(texto: str) -> int | None:
    """Extrai o dia da semana citado no texto ("sexta", "sábado"...), se houver."""
    t = (texto or "").lower()
    for nome, idx in _DIAS_IDX.items():
        if nome in t:
            return idx
    # "segunda" solta (sem -feira) só vale como dia se não for "segunda opção/horário"
    if re.search(r"\bsegunda\b(?!\s*(op[çc][ãa]o|hor[áa]rio))", t):
        return 0
    return None


def _filtrar_por_dia(slots: list[dict], weekday: int) -> list[dict]:
    return [
        s for s in slots
        if datetime.strptime(s["data"], "%Y-%m-%d").weekday() == weekday
    ]


def _periodo_pedido(texto: str) -> str | None:
    """Extrai preferência de período ("de manhã"/"à tarde") citada no texto, se houver.

    Usa \\b para não casar "manhã" dentro de "amanhã".
    """
    t = (texto or "").lower()
    if re.search(r"\btarde\b", t):
        return "tarde"
    if re.search(r"\bmanh[ãa]\b", t):
        return "manha"
    return None


def _filtrar_por_periodo(slots: list[dict], periodo: str) -> list[dict]:
    corte = "12:00"
    if periodo == "manha":
        return [s for s in slots if s["horario"] < corte]
    return [s for s in slots if s["horario"] >= corte]


def _normalizar_horas(texto: str) -> str:
    """Converte '9h', '09h00', '14h30' para o formato HH:MM usado nos slots."""
    def _rep(m: re.Match) -> str:
        return f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
    return re.sub(r"\b(\d{1,2})h(\d{2})?\b", _rep, texto or "")


def _escolha_de_slot(mensagem: str, slots: list[dict], lead_id: str) -> dict | None:
    """Detecta escolha de slot por número ("1") ou posição ("o primeiro horário").

    Só vale quando a última mensagem do agente apresentou horários — seja pela
    lista padrão ("horários disponíveis") ou pela resposta a uma negociação
    (que inclui os labels dos slots literalmente). Fora desse contexto, "1"/"2"
    são as opções reagendar/recusar do template.
    """
    if not slots:
        return None
    idx = None
    m = re.fullmatch(r"\s*(\d)\s*[.!]?\s*", mensagem or "")
    if m:
        idx = int(m.group(1)) - 1
    else:
        # ordinais por extenso; "segunda" (feminino) fica de fora — é dia da semana
        m = re.search(r"\b(primeir[oa]|segundo|terceir[oa])\b", (mensagem or "").lower())
        if m:
            idx = {"p": 0, "s": 1, "t": 2}[m.group(1)[0]]
    if idx is None:
        return None
    ultima = _ultima_mensagem_agente(lead_id)
    agente_ofereceu_horarios = (
        "horários disponíveis" in ultima
        or any(s["label"] in ultima for s in slots)
    )
    if not agente_ofereceu_horarios:
        return None
    return slots[idx] if 0 <= idx < len(slots) else None


def _encontrar_slot(data_info: str, slots: list[dict], mensagem: str = "") -> dict | None:
    """Tenta casar data_info com um slot disponível de forma ESTRITA.

    Retorna None quando não há correspondência concreta — NUNCA "chuta" slots[0].
    Confirmar uma visita exige evidência clara do horário escolhido pelo lead;
    do contrário o agente reenvia as opções em vez de inventar uma confirmação.
    """
    if not data_info:
        return None

    # Normaliza "14h"/"09h00" → "14:00"/"09:00" (formato dos labels difere dos slots)
    data_info = _normalizar_horas(data_info)

    # Tenta dd/mm/yyyy HH:MM (formato completo)
    match = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})", data_info)
    if match:
        try:
            data_iso = datetime.strptime(match.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
            horario = match.group(2)
            for slot in slots:
                if slot["data"] == data_iso and slot["horario"] == horario:
                    return slot
            return None
        except ValueError:
            pass

    # Tenta dd/mm HH:MM (sem ano — assume ano corrente)
    match = re.search(r"(\d{2}/\d{2})\s+(\d{2}:\d{2})", data_info)
    if match:
        try:
            ano = datetime.now().year
            data_iso = datetime.strptime(f"{match.group(1)}/{ano}", "%d/%m/%Y").strftime("%Y-%m-%d")
            horario = match.group(2)
            for slot in slots:
                if slot["data"] == data_iso and slot["horario"] == horario:
                    return slot
        except ValueError:
            pass

    # Se o lead citou dia da semana ("sexta às 10h"), restringe aos slots desse dia
    weekday = _dia_semana_pedido(f"{data_info} {mensagem}")
    candidatos = _filtrar_por_dia(slots, weekday) if weekday is not None else slots

    # Fallback: busca por horário (HH:MM) ou data ISO presente em data_info
    for slot in candidatos:
        if slot["horario"] in data_info or slot["data"] in data_info:
            return slot

    return None


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


def _fallback_handoff(lead: dict, motivo: str) -> dict:
    """Resposta segura quando o agente não consegue gerar uma resposta (ex.: LLM fora).

    Envia uma mensagem acolhedora ao lead, transfere para o SDR e notifica a equipe —
    o lead NUNCA fica sem retorno.
    """
    nome = lead.get("nome", "")
    telefone = lead.get("telefone", "")
    logger.aviso(f"Fallback handoff acionado (lead {lead.get('id')}): {motivo}")
    return {
        "resposta": prompts.MSG_FALLBACK,
        "status_agente": "transferido_sdr",
        "nova_data": "",
        "notif_sdr": prompts.NOTIF_SDR_FALLBACK.format(
            nome=nome, motivo=motivo, telefone=telefone, mensagem="—"
        ),
    }


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
    # Unidade efetiva: se o lead já pediu outra unidade numa rodada anterior
    # (persistida na coluna M), todo o fluxo passa a usá-la — slots, endereço,
    # confirmação e Gendo seguem a unidade escolhida, nunca a original.
    unidade = lead.get("unidade_alvo") or lead["unidade"]
    telefone = lead["telefone"]
    try:
        # pool = TODOS os slots livres da janela (p/ negociação e confirmação);
        # slots = 3 opções exibidas, diversificadas por dia
        pool = disponibilidade.slots_livres(unidade)
    except Exception as exc:
        logger.aviso(f"Falha ao buscar slots (lead {lead_id}): {exc}")
        pool = []
    slots = disponibilidade.escolher_diversos(pool, 3)
    system_prompt = rag.build_system_prompt(lead)

    # Slots que o agente de fato ofereceu na última mensagem (lista padrão ou
    # alternativas de negociação) — é contra eles que "1"/"o primeiro" resolve.
    ultima = _ultima_mensagem_agente(lead_id)
    oferecidos = [s for s in pool if s["label"] in ultima] or slots

    slot_direto = _escolha_de_slot(mensagem_cliente, oferecidos, lead_id)
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
            unidade=unidade,
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
        # usa o slot escolhido de forma determinística, ou casa estritamente o
        # data_info contra o POOL inteiro (o lead pode confirmar um horário
        # negociado que não estava entre as 3 opções exibidas)
        slot = slot_direto or _encontrar_slot(data_info, pool, mensagem_cliente)

        # sem horário concreto: NÃO confirma (evita alucinação) — reenvia as opções
        if not slot:
            opcoes_labels = [s["label"] for s in slots]
            while len(opcoes_labels) < 3:
                opcoes_labels.append("(sem disponibilidade)")
            resposta = prompts.MSG_ENVIAR_SLOTS.format(
                unidade=unidade,
                opcao_1=opcoes_labels[0], opcao_2=opcoes_labels[1], opcao_3=opcoes_labels[2],
            )
            registrar_mensagem_agente(lead_id, resposta)
            return {
                "resposta": resposta,
                "status_agente": lead["status_agente"],
                "nova_data": "",
                "notif_sdr": None,
            }

        nova_data = data_info or slot.get("label", "")
        aviso_cancelamento = ""

        if slot and not config.DRY_RUN:
            try:
                dados = gendo.get_agendamento_dados(lead_id)
                id_responsavel = dados.get("id_responsavel") or dados.get("responsavel_id")
                # Troca de unidade: a agenda é definida pelo id_responsavel.
                # Sem sobrescrever, o agendamento cairia na unidade original.
                if lead.get("unidade_alvo"):
                    resp_alvo = unidades.id_responsavel(unidade)
                    if resp_alvo is not None:
                        id_responsavel = resp_alvo
                    else:
                        logger.aviso(
                            f"Não encontrei id_responsavel da unidade '{unidade}' na Gendo "
                            f"(lead {lead_id}); usando o responsável original."
                        )
                novo = gendo.criar_agendamento(
                    id_paciente=dados.get("id_paciente") or dados.get("paciente_id"),
                    id_responsavel=id_responsavel,
                    id_servico=dados.get("id_servico") or dados.get("servico_id"),
                    data=slot["data"],
                    horario=slot["horario"],
                )
                if not novo:
                    raise RuntimeError("resposta vazia da Gendo ao criar o agendamento")
                logger.info(f"Novo agendamento criado: ID {novo.get('id')} | unidade '{unidade}'")
            except Exception as exc:
                # NÃO confirma ao lead uma visita que não foi criada — transfere ao SDR
                logger.erro(f"Falha ao criar agendamento no Gendo (lead {lead_id}): {exc}")
                return _fallback_handoff(
                    lead, f"falha ao criar agendamento {nova_data} na unidade {unidade}: {exc}"
                )
            try:
                gendo.atualizar_status(lead_id, "7")  # 7 = Cancelado (substituído)
            except Exception as exc:
                logger.aviso(f"Falha ao cancelar agendamento antigo {lead_id}: {exc}")
                aviso_cancelamento = (
                    f" | ⚠️ cancelar a visita antiga (ID {lead_id}) falhou — cancelar no Gendo"
                )
        elif slot and config.DRY_RUN:
            logger.info(
                f"[DRY-RUN] Seria criado agendamento no Gendo: {slot['data']} {slot['horario']}"
            )

        endereco = rag.get_endereco(unidade) or "Endereço disponível na unidade"
        maps_link = rag.get_maps_link(unidade)
        if maps_link:
            endereco += f"\n{maps_link}"
        resposta = prompts.MSG_CONFIRMADO.format(
            data_hora=nova_data, unidade=unidade, endereco=endereco
        )

        registrar_mensagem_agente(lead_id, resposta)
        return {
            "resposta": resposta,
            "status_agente": "reagendado",
            "nova_data": nova_data,
            "notif_sdr": prompts.NOTIF_SDR_REAGENDADO.format(
                nome=nome, data_hora=nova_data, unidade=unidade, telefone=telefone
            ) + aviso_cancelamento,
        }

    # Negociação que na verdade nomeia uma unidade diferente da rastreada
    # ("um horário de tarde na Campo Belo") é tratada como troca de unidade —
    # senão o lead cai numa negociação que ignora silenciosamente o pedido
    # real e força o LLM a "inventar" resposta sem dado nenhum (ver abaixo).
    _unidade_negociada = (
        rag.resolver_unidade(mensagem_cliente, excluir=unidade)
        if "QUER_NEGOCIAR" in categoria else None
    )

    if "QUER_OUTRA_UNIDADE" in categoria or _unidade_negociada:
        canonica = _unidade_negociada or rag.resolver_unidade(mensagem_cliente, excluir=unidade)

        # Lead pediu outra unidade mas não disse qual → pergunta qual
        if not canonica:
            registrar_mensagem_agente(lead_id, prompts.MSG_QUAL_UNIDADE)
            return {
                "resposta": prompts.MSG_QUAL_UNIDADE,
                "status_agente": lead["status_agente"],
                "nova_data": "",
                "notif_sdr": None,
            }

        # Resolve a unidade na Gendo (nome real da agenda + id_responsavel).
        # Guardamos o nome como o Gendo o conhece para que o filtro de
        # disponibilidade case exatamente e a criação caia na agenda certa.
        nova_unidade, _resp = unidades.resolver(canonica)
        if not nova_unidade:
            registrar_mensagem_agente(lead_id, prompts.MSG_OUTRA_UNIDADE_SEM_SLOTS.format(unidade=canonica))
            return {
                "resposta": prompts.MSG_OUTRA_UNIDADE_SEM_SLOTS.format(unidade=canonica),
                "status_agente": "transferido_sdr",
                "nova_data": "",
                "notif_sdr": prompts.NOTIF_SDR_LIGAR.format(
                    nome=nome, unidade=canonica, telefone=telefone
                ),
            }

        # Mesma unidade já agendada → trata como pedido normal de reagendamento
        # (normaliza acento/abreviação: Gendo e Sheets podem grafar a unidade
        # de forma diferente — "V. Madalena" vs "Vila Madalena" — e uma
        # comparação de string crua deixaria passar como "unidade diferente")
        if unidades.normalizar(nova_unidade) == unidades.normalizar(unidade):
            opcoes_labels = [s["label"] for s in slots]
            while len(opcoes_labels) < 3:
                opcoes_labels.append("(sem disponibilidade)")
            resposta = prompts.MSG_ENVIAR_SLOTS.format(
                unidade=unidade,
                opcao_1=opcoes_labels[0], opcao_2=opcoes_labels[1], opcao_3=opcoes_labels[2],
            )
            registrar_mensagem_agente(lead_id, resposta)
            return {
                "resposta": resposta,
                "status_agente": lead["status_agente"],
                "nova_data": "",
                "notif_sdr": None,
            }

        # Consulta a disponibilidade REAL da nova unidade na Gendo — respeitando
        # dia/período citados junto do pedido de unidade ("terça de tarde na Campo Belo")
        weekday = _dia_semana_pedido(f"{mensagem_cliente} {data_info}")
        periodo = _periodo_pedido(f"{mensagem_cliente} {data_info}")
        try:
            pool_nova = disponibilidade.slots_livres(nova_unidade)
            if weekday is not None:
                pool_nova = _filtrar_por_dia(pool_nova, weekday)
            if periodo:
                pool_nova = _filtrar_por_periodo(pool_nova, periodo)
            slots_nova = disponibilidade.escolher_diversos(pool_nova, 3)
        except Exception as exc:
            logger.aviso(f"Falha ao buscar slots da unidade {nova_unidade} (lead {lead_id}): {exc}")
            slots_nova = []

        if not slots_nova:
            resposta = prompts.MSG_OUTRA_UNIDADE_SEM_SLOTS.format(unidade=nova_unidade)
            registrar_mensagem_agente(lead_id, resposta)
            return {
                "resposta": resposta,
                "status_agente": "transferido_sdr",
                "nova_data": "",
                "unidade_alvo": nova_unidade,
                "notif_sdr": prompts.NOTIF_SDR_LIGAR.format(
                    nome=nome, unidade=nova_unidade, telefone=telefone
                ),
            }

        opcoes_labels = [s["label"] for s in slots_nova]
        while len(opcoes_labels) < 3:
            opcoes_labels.append("(sem disponibilidade)")
        endereco = rag.get_endereco(nova_unidade) or "Endereço disponível na unidade"
        resposta = prompts.MSG_ENVIAR_SLOTS_OUTRA_UNIDADE.format(
            unidade=nova_unidade,
            endereco=endereco,
            opcao_1=opcoes_labels[0], opcao_2=opcoes_labels[1], opcao_3=opcoes_labels[2],
        )
        registrar_mensagem_agente(lead_id, resposta)
        logger.info(f"Lead {lead_id}: troca de unidade '{unidade}' → '{nova_unidade}'")
        return {
            "resposta": resposta,
            "status_agente": lead["status_agente"],
            "nova_data": "",
            "unidade_alvo": nova_unidade,  # persiste p/ as próximas rodadas (coluna M)
            "notif_sdr": None,
        }

    if "QUER_LIGAR" in categoria:
        registrar_mensagem_agente(lead_id, prompts.MSG_QUER_LIGAR)
        return {
            "resposta": prompts.MSG_QUER_LIGAR,
            "status_agente": "transferido_sdr",
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
        # Se o lead pediu um dia e/ou período específico ("só consigo sexta de
        # tarde"), oferece os slots REAIS filtrados (do pool completo), não os
        # 3 padrão — sem filtro nenhum, "de tarde" era simplesmente ignorado.
        weekday = _dia_semana_pedido(f"{mensagem_cliente} {data_info}")
        periodo = _periodo_pedido(f"{mensagem_cliente} {data_info}")
        if weekday is not None or periodo:
            candidatos = _filtrar_por_dia(pool, weekday) if weekday is not None else pool
            if periodo:
                candidatos = _filtrar_por_periodo(candidatos, periodo)
            alternativas = disponibilidade.escolher_diversos(candidatos, 3)
        else:
            alternativas = slots

        # Sem NENHUM horário real pra oferecer: nunca manda o LLM "incluir
        # literalmente" uma lista vazia — sem dado pra copiar, ele inventa
        # (horário fictício ou uma desculpa tipo "problema técnico"). Aqui a
        # resposta honesta e determinística é o próprio caminho já usado
        # quando uma unidade pedida não tem vaga.
        if not alternativas:
            resposta = prompts.MSG_OUTRA_UNIDADE_SEM_SLOTS.format(unidade=unidade)
            registrar_mensagem_agente(lead_id, resposta)
            return {
                "resposta": resposta,
                "status_agente": "transferido_sdr",
                "nova_data": "",
                "notif_sdr": prompts.NOTIF_SDR_LIGAR.format(nome=nome, unidade=unidade, telefone=telefone),
            }

        opcoes_alt = "\n".join(f"- {s['label']}" for s in alternativas)
        preferencia = data_info or "outro horário"
        try:
            msg_neg = _invocar_llm_instrucao(
                system_prompt,
                f"O lead quer {preferencia}. Responda de forma empática e inclua "
                f"LITERALMENTE estas opções de horário disponíveis na mensagem "
                f"(copie os itens abaixo sem alterar o texto):\n{opcoes_alt}\n"
                f"Máximo 4 linhas. Termine com uma pergunta curta sobre qual horário prefere.",
                lead_id,
            )
        except LLMIndisponivel:
            return _fallback_handoff(lead, "negociação de horário")
        return {
            "resposta": msg_neg,
            "status_agente": lead["status_agente"],
            "nova_data": "",
            "notif_sdr": None,
        }

    # INDEFINIDO — perguntas ou respostas vagas: responde com a base de conhecimento
    hist_atual = _historico(lead_id)
    rodadas = sum(1 for m in hist_atual if isinstance(m, AIMessage))
    if rodadas >= 3 and slots:
        # Conversa já tem 3+ rodadas sem chegar a uma categoria — oferece os slots diretamente
        opcoes_labels = [s["label"] for s in slots]
        while len(opcoes_labels) < 3:
            opcoes_labels.append("(sem disponibilidade)")
        resposta = prompts.MSG_ENVIAR_SLOTS.format(
            unidade=unidade,
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

    try:
        resp_indef = _invocar_llm_instrucao(
            system_prompt,
            "Responda à última mensagem do cliente usando APENAS a base de conhecimento "
            "e os dados do lead informados no system prompt (nunca invente valores, vagas ou horários). "
            "Se for pergunta sobre a unidade ou visita, use os dados do lead. "
            "NUNCA liste horários específicos nem afirme disponibilidade de datas — quem oferece "
            "horários é o sistema, não você. Se o cliente quiser marcar, convide-o a reagendar "
            "com a frase: 'posso te enviar os horários disponíveis?'. "
            "Responda de forma precisa e curta; depois redirecione para o reagendamento. "
            "Máximo 4 linhas, estilo WhatsApp.",
            lead_id,
        )
    except LLMIndisponivel:
        return _fallback_handoff(lead, "mensagem que precisa de atenção humana")
    return {
        "resposta": resp_indef,
        "status_agente": lead["status_agente"],
        "nova_data": "",
        "notif_sdr": None,
    }
