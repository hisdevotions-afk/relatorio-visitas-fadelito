"""Templates de mensagem e prompts para o LLM."""

# ── Tentativa 1 (mensagem fixa, sem LLM) ─────────────────────────────────────

MENSAGEM_TENTATIVA_1 = (
    "Olá, {primeiro_nome}. Vocês fizeram falta na nossa visita! 💙💛\n\n"
    "Desejo que esteja tudo bem com a sua família.\n\n"
    "A rotina com os pequenos pode mudar a qualquer momento, e entendemos isso com empatia.\n\n"
    "Será um prazer recebê-los e mostrar cada detalhe da nossa unidade {unidade}.\n\n"
    "Que tal remarcarmos? Temos os seguintes horários disponíveis:\n"
    "🗓 {opcao_1}\n"
    "🗓 {opcao_2}\n"
    "🗓 {opcao_3}\n\n"
    "Qual desses funciona melhor para vocês? 😊"
)

# ── Mensagem simplificada para teste de entrega ───────────────────────────────

PRIMEIRA_MENSAGEM_TESTE = "Olá [PRIMEIRO_NOME]! Teste do agente de reagendamento. Visita [UNIDADE]."

# ── Tentativas 2 e 3 (prompts para o LLM) ────────────────────────────────────

PROMPT_TENTATIVA_2 = (
    "Gere uma mensagem de segundo contato em português brasileiro para {nome} que cancelou/faltou "
    "uma visita escolar em {data_original} na unidade {unidade}. "
    "Tom: propositivo, empático, reforça o valor da visita presencial, leve senso de disponibilidade (sem urgência forçada). "
    "Máximo 4 linhas. Inclua as seguintes opções de horário:\n{opcoes}\n"
    "Nunca soar como robô. Retorne apenas o texto da mensagem."
)

PROMPT_TENTATIVA_3 = (
    "Gere uma mensagem final de terceiro contato em português brasileiro para {nome}. "
    "Tom: cordial, deixa claro que é o último contato, mantém porta aberta. "
    "Máximo 3 linhas. Inclua as seguintes opções de horário:\n{opcoes}\n"
    "Retorne apenas o texto da mensagem."
)

# ── Classificação de resposta do cliente ──────────────────────────────────────

PROMPT_CLASSIFICAR = """Você classifica respostas de clientes em um contexto de reagendamento de visita escolar.

Opções oferecidas ao cliente:
{opcoes}

Mensagem do cliente: "{mensagem}"

Classifique em EXATAMENTE UMA categoria:
- CONFIRMOU_DATA: escolheu opção oferecida ou sugeriu data/horário específico
- QUER_NEGOCIAR: pediu horário diferente dos oferecidos
- QUER_LIGAR: prefere contato telefônico
- RECUSOU: não quer reagendar
- INDEFINIDO: resposta vaga ou sem relação com reagendamento

Responda SOMENTE com a categoria na primeira linha.
Se CONFIRMOU_DATA ou QUER_NEGOCIAR, na segunda linha escreva: DATA: <data e horário mencionado>"""

# ── Respostas fixas ao cliente ────────────────────────────────────────────────

MSG_CONFIRMADO = (
    "Perfeito! Visita confirmada para {data_hora} na unidade Fadelito {unidade}. 💙\n\n"
    "Quais os nomes das pessoas que virão à visita? (para liberar na portaria)\n"
    "E me informe um e-mail, por favor 🙂\n\n"
    "A diretora irá recebê-los. Por segurança, pedimos que apresentem um documento com foto na portaria.\n\n"
    "Te esperamos! 💙💛"
)

MSG_QUER_LIGAR = (
    "Claro! Vou avisar nossa equipe para entrar em contato com você.\n"
    "Até breve! 💙"
)

MSG_RECUSOU = (
    "Entendemos! Se mudar de ideia, estaremos aqui.\n"
    "Desejamos tudo de bom para sua família! 💙💛"
)

# ── Notificações para o SDR ───────────────────────────────────────────────────

NOTIF_SDR_REAGENDADO = "✅ *Reagendado* | {nome} | {data_hora} | {unidade} | Tel: {telefone}"
NOTIF_SDR_LIGAR = "📞 *Ligar agora* | {nome} quer falar por telefone | {unidade} | Tel: {telefone}"
NOTIF_SDR_PERDIDO = "❌ *Sem retorno* | {nome} | 3 tentativas | Tel: {telefone}"
