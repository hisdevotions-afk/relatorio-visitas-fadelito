"""Templates de mensagem e prompts para o LLM."""

# ── Tentativa 1 (template fixo, sem LLM) ─────────────────────────────────────

MENSAGEM_TENTATIVA_1 = (
    "Olá, {primeiro_nome}. Vocês fizeram falta na nossa visita! 💙💛\n\n"
    "Desejo que esteja tudo bem com a sua família.\n\n"
    "A rotina com os pequenos pode mudar a qualquer momento, e entendemos isso com empatia.\n\n"
    "Será um prazer recebê-los e mostrar cada detalhe da nossa unidade.\n\n"
    "1 - Quero reagendar\n"
    "2 - Optei por outra escola"
)

# ── Horários enviados após lead responder "1" ─────────────────────────────────

MSG_ENVIAR_SLOTS = (
    "Ótimo! Temos os seguintes horários disponíveis:\n"
    "- {opcao_1}\n"
    "- {opcao_2}\n"
    "- {opcao_3}\n\n"
    "Qual desses funciona melhor para vocês?"
)

# ── Mensagem simplificada para teste de entrega ───────────────────────────────

PRIMEIRA_MENSAGEM_TESTE = "Olá [PRIMEIRO_NOME]! Teste do agente de reagendamento. Visita [UNIDADE]."

# ── Tentativas 2 e 3 (prompts para o LLM) ────────────────────────────────────

PROMPT_TENTATIVA_2 = (
    "Gere uma mensagem de segundo contato em português brasileiro para {nome} que cancelou/faltou "
    "uma visita escolar em {data_original} na unidade {unidade}. "
    "Tom: propositivo, empático, reforça o valor da visita presencial, leve senso de disponibilidade (sem urgência forçada). "
    "Use no máximo 1 emoji, apenas se natural. Máximo 4 linhas. "
    "Inclua as seguintes opções de horário:\n{opcoes}\n"
    "Nunca soar como robô. Retorne apenas o texto da mensagem."
)

PROMPT_TENTATIVA_3 = (
    "Gere uma mensagem final de terceiro contato em português brasileiro para {nome}. "
    "Tom: cordial, deixa claro que é o último contato, mantém porta aberta. "
    "Use no máximo 1 emoji. Máximo 3 linhas. "
    "Inclua as seguintes opções de horário:\n{opcoes}\n"
    "Retorne apenas o texto da mensagem."
)

# ── Classificação de resposta do cliente ──────────────────────────────────────

PROMPT_CLASSIFICAR = """Você classifica respostas de clientes em um contexto de reagendamento de visita escolar.

Opções apresentadas ao cliente:
{opcoes}

Última mensagem que o agente enviou ao cliente (use como contexto para interpretar a resposta):
\"\"\"{contexto}\"\"\"

Mensagem do cliente: "{mensagem}"

Classifique em EXATAMENTE UMA categoria:
- QUER_REAGENDAR: respondeu "1" à mensagem inicial (opções 1/2), quer reagendar ou expressou interesse em remarcar
- RECUSOU: respondeu "2" à mensagem inicial, optou por outra escola ou não quer reagendar
- CONFIRMOU_DATA: escolheu um horário dentre os oferecidos (por número, posição como "o primeiro", ou texto) ou sugeriu data/horário concreto
- QUER_NEGOCIAR: pediu horário/dia diferente dos apresentados
- QUER_LIGAR: prefere atendimento pessoal, pede para falar com alguém da equipe ou solicita ligação
- INDEFINIDO: pergunta sobre a escola (valores, estrutura, turmas, funcionamento, endereço etc.), resposta vaga ou fora das categorias acima

ATENÇÃO: se a última mensagem do agente ofereceu uma lista de horários e o cliente respondeu
com um número ou escolha, isso é CONFIRMOU_DATA (não QUER_REAGENDAR).

Responda SOMENTE com a categoria na primeira linha.
Se CONFIRMOU_DATA ou QUER_NEGOCIAR, na segunda linha escreva: DATA: <data e horário mencionado>"""

# ── Respostas fixas ao cliente ────────────────────────────────────────────────

MSG_CONFIRMADO = (
    "Perfeito! Visita confirmada para {data_hora} na unidade Fadelito {unidade}. 💙\n\n"
    "Quais os nomes das pessoas que virão à visita? (para liberar na portaria)\n"
    "E me informe um e-mail, por favor.\n\n"
    "A diretora irá recebê-los. Por segurança, pedimos que apresentem um documento com foto na portaria.\n\n"
    "Te esperamos!"
)

MSG_QUER_LIGAR = (
    "Nosso atendimento é feito pelo WhatsApp mesmo.\n"
    "Vou avisar nossa equipe, que continua te ajudando por aqui em breve!"
)

MSG_RECUSOU = (
    "Entendemos! Se mudar de ideia, estaremos aqui.\n"
    "Desejamos tudo de bom para sua família!"
)

# ── Respostas automáticas pós-handoff (enviadas uma única vez ao lead) ────────

MSG_POS_REAGENDADO = (
    "Sua visita já está confirmada! 😊\n"
    "Se tiver alguma dúvida, nossa equipe pode te ajudar."
)

MSG_POS_TRANSFERIDO_SDR = (
    "Nossa equipe já foi avisada e vai continuar te atendendo aqui pelo WhatsApp em breve."
)

MSG_POS_PERDIDO = (
    "Olá! Se mudou de ideia e quiser conhecer a Fadelito, é só me dizer — "
    "posso te ajudar a marcar uma visita."
)

# ── Notificações para o SDR ───────────────────────────────────────────────────

NOTIF_SDR_REAGENDADO = "✅ *Reagendado* | {nome} | {data_hora} | {unidade} | Tel: {telefone}"
NOTIF_SDR_LIGAR = "💬 *Assumir conversa* | {nome} prefere atendimento pessoal | {unidade} | Tel: {telefone}"
NOTIF_SDR_PERDIDO = "❌ *Sem retorno* | {nome} | 3 tentativas | Tel: {telefone}"
NOTIF_SDR_RECUSOU = "❌ *Recusou* | {nome} | optou por não reagendar | Tel: {telefone}"

# ── Fallback (quando o agente não consegue processar — LLM/sistema indisponível) ──
MSG_FALLBACK = (
    "Recebi sua mensagem! 😊\n"
    "Nossa equipe vai continuar seu atendimento aqui pelo WhatsApp em instantes."
)
NOTIF_SDR_FALLBACK = (
    "⚠️ *Assumir conversa* | {nome} respondeu mas o agente não conseguiu processar "
    "({motivo}) | Tel: {telefone} | Mensagem: \"{mensagem}\""
)
