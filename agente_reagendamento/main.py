"""Orquestrador principal do agente de reagendamento de visitas."""
import argparse
import sys
from datetime import datetime, timedelta

# config deve ser importado ANTES dos demais módulos do projeto
import config

import agente
import disponibilidade
import logger
import prompts
import sheets as sh
import whatsapp as wa

# Visitas elegíveis para reagendamento
STATUS_VISIITA_ALVO = {"Faltou", "Cancelado"}

# Dias de espera entre tentativas
DIAS_TENTATIVA_2 = 2
DIAS_TENTATIVA_3 = 5
DIAS_ENCERRAR = 2   # dias após tentativa_3 para marcar como perdido


# ── Processamento proativo (envio de mensagens) ───────────────────────────────

def processar_leads(aba: str | None = None, teste_simples: bool = False) -> None:
    """Lê a planilha e envia mensagens para todos os leads elegíveis."""
    if aba is None:
        if not sh.hoje_e_dia_util():
            logger.info("Hoje não é dia útil. Processamento ignorado.")
            return
        aba = sh.tab_name()

    logger.info(f"Iniciando processamento da aba '{aba}'")
    sh.ensure_agent_columns(aba)
    leads = sh.get_leads(aba)
    logger.info(f"{len(leads)} leads carregados")

    if config.MODO_TESTE:
        leads_teste = []
        tel_teste = _normalizar_tel(config.WHATSAPP_TESTE_NUMBER)
        for lead in leads:
            tel_lead = _normalizar_tel(lead.get("telefone", ""))
            if tel_lead == tel_teste and tel_teste != "":
                leads_teste.append(lead)
            else:
                logger.info(f"[MODO TESTE] Pulando lead real: {lead.get('nome', 'Sem nome')} ({lead.get('telefone', 'Sem telefone')})")
        leads = leads_teste
        if not leads:
            logger.info(f"[MODO TESTE] Nenhum lead de teste encontrado. Cadastre uma linha na planilha com o telefone {config.WHATSAPP_TESTE_NUMBER}.")

    agora = datetime.now()
    processados = 0

    for lead in leads:
        try:
            if _processar_lead(lead, agora, teste_simples):
                processados += 1
        except Exception as exc:
            logger.erro(f"Lead {lead.get('id')} ({lead.get('nome')}): {exc}")

    logger.info(f"Processamento concluído. Leads acionados: {processados}")


def _processar_lead(lead: dict, agora: datetime, teste_simples: bool = False) -> bool:
    """Avalia e aciona um lead. Retorna True se mensagem foi enviada."""
    status_visita = lead["status"]
    status_agente = lead["status_agente"] or "pendente"
    telefone = lead["telefone"]
    lead_id = str(lead["id"])
    nome = lead["nome"]

    if status_visita not in STATUS_VISIITA_ALVO:
        return False

    if status_agente in ("reagendado", "perdido"):
        return False

    if not telefone:
        logger.aviso(f"Lead {lead_id} ({nome}) sem telefone. Ignorado.")
        return False

    # Idempotência: não envia se mensagem foi enviada nas últimas 2h
    ultima = lead["ultima_tentativa"]
    if ultima:
        try:
            ultima_dt = datetime.fromisoformat(ultima)
            if (agora - ultima_dt).total_seconds() < 7200:
                return False
        except ValueError:
            pass

    # Encerrar lead sem resposta após tentativa_3
    if status_agente == "tentativa_3":
        if _dias_desde(ultima, agora) >= DIAS_ENCERRAR:
            _encerrar_lead(lead, agora)
        return False

    deve_enviar, proximo_status = _avaliar_timing(status_agente, ultima, agora)
    if not deve_enviar:
        return False

    slots = disponibilidade.get_slots_disponiveis(3)
    if not slots:
        logger.aviso(f"Nenhum slot disponível para lead {lead_id}")
        return False

    tentativa_num = int(lead["tentativas"] or 0) + 1
    if teste_simples:
        primeiro_nome = nome.split()[0]
        mensagem = (
            prompts.PRIMEIRA_MENSAGEM_TESTE
            .replace("[PRIMEIRO_NOME]", primeiro_nome)
            .replace("[UNIDADE]", lead["unidade"])
        )
    else:
        mensagem = agente.gerar_mensagem_tentativa(tentativa_num, lead, slots)
    if not mensagem:
        return False

    if tentativa_num == 1 and not teste_simples:
        primeiro_nome = nome.split()[0] if nome else "Cliente"
        wa.send_template(telefone, primeiro_nome)
    else:
        wa.send_message(telefone, mensagem)
    logger.log_conversa(lead_id, nome, "AGENTE→CLIENTE", mensagem)

    agora_iso = agora.isoformat()
    agente.carregar_historico(lead_id, lead.get("log_conversa", ""))
    agente.registrar_mensagem_agente(lead_id, mensagem)
    sh.update_lead_agente(
        lead["aba"],
        lead["row_index"],
        status_agente=proximo_status,
        tentativas=tentativa_num,
        ultima_tentativa=agora_iso,
        log_conversa=agente.serializar_historico(lead_id),
    )

    logger.info(f"Mensagem enviada para {nome} (ID {lead_id}), tentativa {tentativa_num}")
    return True


def _avaliar_timing(
    status_agente: str, ultima_tentativa: str | None, agora: datetime
) -> tuple[bool, str]:
    """Decide se deve enviar mensagem agora. Retorna (enviar, proximo_status)."""
    if status_agente in ("pendente", ""):
        return True, "tentativa_1"

    if status_agente == "tentativa_1":
        if _dias_desde(ultima_tentativa, agora) >= DIAS_TENTATIVA_2:
            return True, "tentativa_2"

    if status_agente == "tentativa_2":
        if _dias_desde(ultima_tentativa, agora) >= DIAS_TENTATIVA_3:
            return True, "tentativa_3"

    return False, status_agente


def _dias_desde(ultima: str | None, agora: datetime) -> int:
    if not ultima:
        return 999
    try:
        return (agora - datetime.fromisoformat(ultima)).days
    except ValueError:
        return 0


def _encerrar_lead(lead: dict, agora: datetime) -> None:
    """Marca lead como perdido e notifica SDR."""
    nome = lead["nome"]
    logger.info(f"Lead {lead['id']} ({nome}): marcado como perdido")

    notif = f"❌ *Sem retorno* | {nome} | 3 tentativas | Tel: {lead['telefone']}"
    wa.notify_sdr(notif)

    logger.log_conversa(lead["id"], nome, "AGENTE→CLIENTE", "lead encerrado após 3 tentativas sem resposta")

    sh.update_lead_agente(
        lead["aba"],
        lead["row_index"],
        status_agente="perdido",
        ultima_tentativa=agora.isoformat(),
    )


# ── Processamento de resposta recebida (webhook) ──────────────────────────────

def processar_resposta_webhook(payload: dict) -> None:
    """Ponto de entrada para mensagens recebidas via webhook Meta."""
    mensagens = wa.parse_webhook(payload)
    aba = sh.tab_name()
    leads = sh.get_leads(aba)

    for msg in mensagens:
        telefone_de = msg["from"]
        texto = msg["text"]
        lead = _buscar_lead_por_telefone(leads, telefone_de)
        if not lead:
            logger.info(f"Mensagem de número desconhecido: {telefone_de}")
            continue
        _tratar_resposta(lead, texto, aba)


def _buscar_lead_por_telefone(leads: list[dict], telefone: str) -> dict | None:
    tel_norm = _normalizar_tel(telefone)
    return next(
        (l for l in leads if _normalizar_tel(l["telefone"]) == tel_norm),
        None,
    )


def _normalizar_tel(tel: str) -> str:
    digits = "".join(c for c in (tel or "") if c.isdigit())
    if digits and not digits.startswith("55"):
        digits = "55" + digits
    return digits


def _tratar_resposta(lead: dict, mensagem: str, aba: str) -> None:
    if lead["status_agente"] in ("reagendado", "perdido"):
        return

    lead_id = str(lead["id"])
    nome = lead["nome"]

    # Restaura histórico da sessão anterior e registra mensagem do cliente
    agente.carregar_historico(lead_id, lead.get("log_conversa", ""))
    agente.registrar_mensagem_cliente(lead_id, mensagem)

    resultado = agente.processar_resposta_cliente(lead, mensagem)
    agora_iso = datetime.now().isoformat()

    logger.log_conversa(lead_id, nome, "CLIENTE→AGENTE", mensagem)
    logger.log_conversa(lead_id, nome, "AGENTE→CLIENTE", resultado["resposta"])

    # Caminhos sem LLM (confirmado/recusado/ligar) não atualizam _conversas — registra manualmente
    if resultado["status_agente"] in ("reagendado", "perdido"):
        agente.registrar_mensagem_agente(lead_id, resultado["resposta"])

    updates = {
        "status_agente": resultado["status_agente"],
        "ultima_tentativa": agora_iso,
        "log_conversa": agente.serializar_historico(lead_id),
    }
    if resultado.get("nova_data"):
        updates["nova_data"] = resultado["nova_data"]

    sh.update_lead_agente(aba, lead["row_index"], **updates)
    wa.send_message(lead["telefone"], resultado["resposta"])

    if resultado.get("notif_sdr"):
        wa.notify_sdr(resultado["notif_sdr"])


# ── Demo com leads fictícios ──────────────────────────────────────────────────

_LEADS_DEMO = [
    {
        "row_index": 2, "aba": "29/04/2026",
        "id": "1001", "data_hora": "29/04/2026 09:00",
        "nome": "Maria Silva", "unidade": "Fadelito Centro",
        "servico": "Visita", "status": "Cancelado",
        "telefone": "5511988880001",
        "status_agente": "pendente", "tentativas": "0",
        "ultima_tentativa": "", "nova_data": "", "log_conversa": "",
    },
    {
        "row_index": 3, "aba": "29/04/2026",
        "id": "1002", "data_hora": "29/04/2026 10:00",
        "nome": "João Pereira", "unidade": "Fadelito Norte",
        "servico": "Visita", "status": "Faltou",
        "telefone": "5511988880002",
        "status_agente": "pendente", "tentativas": "0",
        "ultima_tentativa": "", "nova_data": "", "log_conversa": "",
    },
]


def _rodar_demo() -> None:
    """Executa dry-run com leads fictícios sem precisar de planilha real."""
    config.set_dry_run(True)
    logger.info("=== MODO DEMO (dry-run com leads fictícios) ===")
    agora = datetime.now()

    # Disponibilidade fictícia para não chamar API Gendo
    slots_mock = [
        {"data": "2026-05-04", "horario": "09:00", "label": "segunda-feira, 04/05 às 09h"},
        {"data": "2026-05-04", "horario": "10:00", "label": "segunda-feira, 04/05 às 10h"},
        {"data": "2026-05-05", "horario": "09:00", "label": "terça-feira, 05/05 às 09h"},
    ]

    for lead in _LEADS_DEMO:
        logger.info(f"--- Processando lead: {lead['nome']} ({lead['status']}) ---")
        tentativa_num = 1
        mensagem = agente.gerar_mensagem_tentativa(tentativa_num, lead, slots_mock)
        logger.info(f"[DRY-RUN] Seria enviado para {lead['telefone']}:\n{mensagem}")
        logger.info(
            f"[DRY-RUN] Seria gravado no Sheets: linha {lead['row_index']}, "
            f"status_agente=tentativa_1, tentativas=1"
        )


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args():
    parser = argparse.ArgumentParser(
        description="Agente de reagendamento de visitas escolares via WhatsApp"
    )
    parser.add_argument(
        "--processar", action="store_true",
        help="Lê a planilha e envia mensagens para leads pendentes",
    )
    parser.add_argument(
        "--tab", default=None,
        help="Aba da planilha no formato dd/mm/yyyy (padrão: último dia útil)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Executa toda a lógica sem enviar WhatsApp, gravar no Sheets ou chamar Gendo",
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Dry-run com 2 leads fictícios (não exige credenciais reais)",
    )
    parser.add_argument(
        "--teste-simples", action="store_true",
        help="Usa mensagem simplificada para validar entrega sem depender do LLM",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.demo:
        _rodar_demo()
        return

    if args.dry_run:
        config.set_dry_run(True)
        logger.info("Modo dry-run ativado")

    if args.processar:
        processar_leads(args.tab, teste_simples=args.teste_simples)
    else:
        logger.erro("Especifique --processar, --demo ou --dry-run --processar")
        sys.exit(1)


if __name__ == "__main__":
    main()
