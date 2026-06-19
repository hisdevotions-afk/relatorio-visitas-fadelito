"""Base de conhecimento Fadelito RAG v2.0 — injetado no system prompt do agente."""
import json
import os
import random
import unicodedata
from functools import lru_cache

KNOWLEDGE_BASE = """\
=== FADELITO — BASE DE CONHECIMENTO (RAG v2.0) ===

PERFIL DO LEAD
Leads mornos: já demonstraram interesse, agendaram visita, não compareceram ou cancelaram.
NÃO precisam ser convencidos do zero — precisam ser reativados com leveza, sem pressão.

OBJETIVO DO AGENTE
Principal: reagendar a visita presencial à unidade Fadelito.
NÃO FAZER: nova apresentação completa, negociações financeiras, pressionar, inventar informações, tentar fechar matrícula.

TOM E ESTILO
Leve, natural, humano, empático, frases curtas (estilo WhatsApp), direto, sem pressão.
Evitar: textos longos, linguagem formal/institucional, tom de venda agressiva, múltiplas perguntas por mensagem, excesso de emojis.

REGRAS ANTI-ALUCINAÇÃO (CRÍTICAS)
- NUNCA inventar valores, mensalidades, promoções, vagas ou horários
- NUNCA confirmar vaga sem verificar no sistema Gendo
- NUNCA criar horários — usar apenas os fornecidos na mensagem
- NUNCA informar nome da diretora (usar sempre "a diretora")
- NUNCA prometer ou sugerir ligação telefônica — todo atendimento é feito pelo WhatsApp
- Se não souber algo: "Posso verificar isso para você com a equipe."
- Negociações financeiras: SOMENTE presencialmente com a diretora

SOBRE A FADELITO
- Maior rede especializada em Berçário e Educação Infantil do Brasil (25+ anos)
- Crianças de 4 meses (Berçário) até 6 anos (Pré)
- São Paulo, Grande SP e Interior — sistema de ensino próprio, atualizado anualmente

TURMAS
- Berçário (4m–18m): Programa Baby Learning — cognitivo, motor, alimentação e amor
- Minimaternal (até 3 anos): relações sociais, psicomotricidade, linguagem oral
- Maternal I: ensino próprio + inglês (National Geographic ou CEL.LEP)
- Maternal II: inglês diário + extracurriculares inclusas (Judô, Ballet, Arte, Mindfulness, Música, Culinária, Horticultura)
- Jardim e Pré: todas as extracurriculares, preparação para alfabetização, inglês diário

HORÁRIOS DE FUNCIONAMENTO
- 4h30: 7h30–12h ou 13h–17h30
- 4h (Perdizes, Guarulhos, Real Parque, Klabin): 8h–12h ou 13h–17h
- 6h+: flexíveis, combinados na matrícula
- Integral (12h): 7h–19h

FINANCEIRO (contexto apenas — NÃO negociar)
- Anuidade: 13 parcelas (13ª é reserva de vaga, pode ser parcelada em 2x R$1.050)
- Alimentação: NÃO inclusa — aprox. R$14/refeição com pacotes mensais
- Atividades extracurriculares: SEM custo adicional (inclusas no período)
- Uniforme: fadelitostore.com.br
- Novas unidades (São Caetano, Higienópolis): condições especiais de lançamento — mencionar APENAS se o lead perguntar
- Qualquer negociação: presencialmente com a diretora

UNIDADES E ENDEREÇOS (use SEMPRE estes endereços — nunca invente)
- Aclimação: R. Loureiro da Cruz, 332
- Anália Franco: R. Vilela, 872
- Boa Vista: Rua Conde de Itu, 464
- Bonfiglioli: Praça Isai Leirner, 164
- Brooklin: Av. Professor Vicente Rao, 1208
- Campinas: Av. Júlio de Mesquita, 594
- Campo Belo: Rua Gil Eanes, 553
- Guarulhos: R. Josephina Mandotti, 47
- Granja Viana: R. Direita, 110 - Vila Santo Antônio
- Higienópolis: R. Rosa e Silva, 270
- Indianópolis: Av. Indianópolis, 977
- Ipiranga: Rua Padre Marchetti, 378
- Jardins: Alameda Casa Branca, 583
- Klabin: R. Rodrigo Vieira, 315
- Lapa: R. Espártaco, 215
- Marajoara: Av. Washington Luís, 814
- Moema: R. Inhambu, 891
- Mooca: R. Teresina, 464
- Osasco: Av. Santo Antônio, 1750
- Panamby: R. José Ramon Urtiza, 835
- Paraíso: R. Afonso de Freitas, 687
- Perdizes: R. João Ramalho, 1063
- Pinheiros: R. Francisco Leitão, 497
- Piracicaba: Av. Torquato da Silva Leitão, 208
- Portal do Morumbi: Rua Dr. Luiz Migliano, 425
- Real Parque: Av. Morumbi, 6560
- Santo André: R. das Monções, 345
- São Caetano: R. Rafael Corrêa Sampaio, 99
- Saúde: R. Gal. Chagas Santos, 301
- Tatuapé: R. Ivaí, 187
- Vila Gumercindo: Rua Assungui, 432
- Vila Leopoldina: R. Aroaba, 155
- Vila Madalena: R. das Tabocas, 170
- Vila Mariana: R. Morgado de Mateus, 287
- Vila Sônia: R. Cenobelino Serra, 71

LINKS GOOGLE MAPS (enviar junto do endereço ao confirmar visita ou quando lead pedir localização)
- Vila Leopoldina: https://maps.app.goo.gl/SWQb5PrjWYe176Dn8
- Moema: https://maps.app.goo.gl/gLQDD9YbHnttF93V7
- Pinheiros: https://maps.app.goo.gl/qxrXWfqD6YpQVHpN6
- Vila Madalena: https://maps.app.goo.gl/jHGBwiC3H5DRrPwdA
- Perdizes: https://maps.app.goo.gl/aiQPXHVNZpBmHtdf9
- Jardins: https://maps.app.goo.gl/DPaeAWF7ne6Nihie6
- Mooca: https://maps.app.goo.gl/rhowCo84Snraz49s5
- Guarulhos: https://maps.app.goo.gl/Y1HTEN4k26s75VEG7
- Campinas: https://maps.app.goo.gl/FKGtoGzsVtMaufoGA

CENÁRIOS E RESPOSTAS MODELO
Lead não responde há dias:
  Oi, [NOME]! Vi que você tinha uma visita com a gente, mas acabou não conseguindo vir. Ainda faz sentido conhecer a escola? Posso te ajudar com um novo horário.

Lead estava ocupado:
  Imagino, a rotina acaba ficando corrida mesmo. Se fizer sentido, posso te sugerir um horário mais tranquilo para você essa semana.

Lead esfriou / sumiu:
  Super entendo. Muitas famílias decidem melhor depois de conhecer o espaço pessoalmente. Se quiser, posso te ajudar a remarcar.

Lead comparando escolas:
  Faz todo sentido comparar! A visita costuma ajudar bastante — você consegue sentir o ambiente e ver se faz sentido. Posso te sugerir alguns horários?

Lead menciona preço:
  Entendo, é uma decisão importante mesmo. A visita ajuda porque você vê tudo de perto e a diretora apresenta as opções de valores. Posso te ajudar a remarcar?

Lead optou por outra escola:
  Sem problemas, [NOME]! Se em algum momento fizer sentido, estaremos aqui. Poderia nos dizer o motivo? Muito obrigada e boa sorte!

Lead quer mais informações:
  Posso verificar isso com a equipe para te dar uma resposta certinha. Mas o mais completo mesmo é a visita — você vê tudo de perto e a diretora responde cada detalhe. Que tal agendarmos?

Perguntas fora do escopo:
  Posso pedir para nossa equipe te explicar isso melhor.

HANDOFF PARA SDR
Passar para SDR quando: lead exige negociação financeira; reclamação sobre a escola;
prefere atendimento mais pessoal (nunca prometer ligação — o SDR também atende via WhatsApp);
resposta vaga após 2 rodadas; perguntas complexas sobre pedagogia/valores/vagas.
Frase de handoff: "Vou passar você para nossa equipe, que continua te ajudando aqui pelo WhatsApp."
"""

_SYSTEM_BASE = (
    "Você é o agente de reagendamento de visitas da rede de escolas infantis Fadelito. "
    "Responda sempre em português brasileiro informal (estilo WhatsApp). "
    "Emojis: evite no corpo do texto; em saudações e despedidas, até 2 são aceitáveis. "
    "Siga rigorosamente a base de conhecimento abaixo — nunca invente informações.\n\n"
    + KNOWLEDGE_BASE
)

SYSTEM_PROMPT_AGENTE = _SYSTEM_BASE


def build_system_prompt(lead: dict) -> str:
    """Constrói system prompt personalizado com os dados do lead."""
    nome = lead.get("nome", "")
    unidade = lead.get("unidade", "")
    data_hora = lead.get("data_hora", "")
    contexto = (
        f"DADOS DO LEAD NESTA CONVERSA:\n"
        f"- Nome: {nome}\n"
        f"- Unidade agendada: Fadelito {unidade}\n"
        f"- Data/hora da visita original: {data_hora}\n\n"
    )
    exemplos = get_exemplos_roberto(unidade=unidade)
    return (
        "Você é o agente de reagendamento de visitas da rede de escolas infantis Fadelito. "
        "Responda sempre em português brasileiro informal (estilo WhatsApp). "
        "Emojis: evite no corpo do texto; em saudações e despedidas, até 2 são aceitáveis. "
        "Siga rigorosamente a base de conhecimento abaixo — nunca invente informações.\n\n"
        + contexto
        + KNOWLEDGE_BASE
        + exemplos
    )

_MAPS_LINKS: dict[str, str] = {
    "vila leopoldina": "https://maps.app.goo.gl/SWQb5PrjWYe176Dn8",
    "moema": "https://maps.app.goo.gl/gLQDD9YbHnttF93V7",
    "pinheiros": "https://maps.app.goo.gl/qxrXWfqD6YpQVHpN6",
    "vila madalena": "https://maps.app.goo.gl/jHGBwiC3H5DRrPwdA",
    "perdizes": "https://maps.app.goo.gl/aiQPXHVNZpBmHtdf9",
    "jardins": "https://maps.app.goo.gl/DPaeAWF7ne6Nihie6",
    "mooca": "https://maps.app.goo.gl/rhowCo84Snraz49s5",
    "guarulhos": "https://maps.app.goo.gl/Y1HTEN4k26s75VEG7",
    "campinas": "https://maps.app.goo.gl/FKGtoGzsVtMaufoGA",
}

_ENDERECOS: dict[str, str] = {
    "aclimação": "R. Loureiro da Cruz, 332",
    "anália franco": "R. Vilela, 872",
    "boa vista": "Rua Conde de Itu, 464",
    "bonfiglioli": "Praça Isai Leirner, 164",
    "brooklin": "Av. Professor Vicente Rao, 1208",
    "campinas": "Av. Júlio de Mesquita, 594",
    "campo belo": "Rua Gil Eanes, 553",
    "guarulhos": "R. Josephina Mandotti, 47",
    "granja": "R. Direita, 110 - Vila Santo Antônio",
    "higienópolis": "R. Rosa e Silva, 270",
    "indianópolis": "Av. Indianópolis, 977",
    "ipiranga": "Rua Padre Marchetti, 378",
    "jardins": "Alameda Casa Branca, 583",
    "klabin": "R. Rodrigo Vieira, 315",
    "lapa": "R. Espártaco, 215",
    "marajoara": "Av. Washington Luís, 814",
    "moema": "R. Inhambu, 891",
    "mooca": "R. Teresina, 464",
    "osasco": "Av. Santo Antônio, 1750",
    "panamby": "R. José Ramon Urtiza, 835",
    "paraíso": "R. Afonso de Freitas, 687",
    "perdizes": "R. João Ramalho, 1063",
    "pinheiros": "R. Francisco Leitão, 497",
    "piracicaba": "Av. Torquato da Silva Leitão, 208",
    "portal": "Rua Dr. Luiz Migliano, 425",
    "real parque": "Av. Morumbi, 6560",
    "santo andré": "R. das Monções, 345",
    "são caetano": "R. Rafael Corrêa Sampaio, 99",
    "saúde": "R. Gal. Chagas Santos, 301",
    "tatuapé": "R. Ivaí, 187",
    "vila gumercindo": "Rua Assungui, 432",
    "vila leopoldina": "R. Aroaba, 155",
    "vila madalena": "R. das Tabocas, 170",
    "vila mariana": "R. Morgado de Mateus, 287",
    "vila sônia": "R. Cenobelino Serra, 71",
}


_RAG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "tallos_export", "roberto_rag.jsonl")

_MIN_SDR_LINHAS = 4   # conversa só entra se o Roberto tiver ao menos N falas
_MAX_EXEMPLOS = 6     # quantos exemplos injetar por chamada
_MAX_CHARS_EXEMPLO = 800  # trunca conversas longas para não inflar o prompt


@lru_cache(maxsize=1)
def _carregar_exemplos() -> list[dict]:
    """Carrega as conversas reais do Roberto da base Tallos (cacheado)."""
    if not os.path.exists(_RAG_PATH):
        return []
    exemplos = []
    with open(_RAG_PATH, encoding="utf-8") as f:
        for ln in f:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            sdr_linhas = [l for l in r.get("transcript", "").split("\n") if l.startswith("[SDR]")]
            if len(sdr_linhas) >= _MIN_SDR_LINHAS:
                exemplos.append(r)
    return exemplos


def get_exemplos_roberto(unidade: str = "", seed: int | None = None) -> str:
    """Retorna um bloco de exemplos reais do atendimento do Roberto para injetar no prompt.

    Prioriza conversas da mesma unidade do lead; completa com aleatórios.
    Retorna string vazia se a base não estiver disponível.
    """
    exemplos = _carregar_exemplos()
    if not exemplos:
        return ""

    unidade_lower = unidade.lower()
    prioritarios = [e for e in exemplos if any(unidade_lower in t.lower() for t in e.get("unidades_tags", []))]
    demais = [e for e in exemplos if e not in prioritarios]

    rng = random.Random(seed)
    rng.shuffle(prioritarios)
    rng.shuffle(demais)
    selecionados = (prioritarios + demais)[:_MAX_EXEMPLOS]

    blocos = []
    for e in selecionados:
        transcript = e.get("transcript", "")
        # filtra apenas trocas LEAD/SDR, remove linhas de BOT para exemplos mais limpos
        linhas = [l for l in transcript.split("\n") if l.startswith("[LEAD]") or l.startswith("[SDR]")]
        trecho = "\n".join(linhas)
        if len(trecho) > _MAX_CHARS_EXEMPLO:
            trecho = trecho[:_MAX_CHARS_EXEMPLO] + "\n[...]"
        tags = ", ".join(e.get("unidades_tags", []))
        blocos.append(f"[Conversa real — unidade/tags: {tags}]\n{trecho}")

    return (
        "\n\nEXEMPLOS REAIS DE ATENDIMENTO DO SDR ROBERTO (use como referência de tom e abordagem):\n"
        + "\n\n".join(blocos)
    )


def _norm_unidade(s: str) -> str:
    """Normaliza nome de unidade p/ busca: sem acento, abreviação 'V.'→'Vila'."""
    base = _sem_acento(s).replace("v.", "vila")
    return " ".join(base.split())


def get_maps_link(unidade: str) -> str | None:
    """Retorna link Google Maps para a unidade, se disponível."""
    chave = _norm_unidade(unidade)
    for nome, link in _MAPS_LINKS.items():
        if _norm_unidade(nome) in chave:
            return link
    return None


def get_endereco(unidade: str) -> str | None:
    """Retorna endereço completo da unidade, se disponível."""
    chave = _norm_unidade(unidade)
    for nome, end in _ENDERECOS.items():
        n = _norm_unidade(nome)
        if n in chave or chave in n:
            return end
    return None


# Nomes canônicos das unidades, usados para reconhecer trocas de unidade
# pedidas pelo lead e para consultar a agenda correta na Gendo.
UNIDADES: list[str] = [
    "Aclimação", "Anália Franco", "Boa Vista", "Bonfiglioli", "Brooklin",
    "Campinas", "Campo Belo", "Guarulhos", "Granja Viana", "Higienópolis",
    "Indianópolis", "Ipiranga", "Jardins", "Klabin", "Lapa", "Marajoara",
    "Moema", "Mooca", "Osasco", "Panamby", "Paraíso", "Perdizes", "Pinheiros",
    "Piracicaba", "Portal do Morumbi", "Real Parque", "Santo André",
    "São Caetano", "Saúde", "Tatuapé", "Vila Gumercindo", "Vila Leopoldina",
    "Vila Madalena", "Vila Mariana", "Vila Sônia",
]


def _sem_acento(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s or "")
        if unicodedata.category(c) != "Mn"
    ).lower()


def resolver_unidade(texto: str) -> str | None:
    """Identifica o nome canônico de uma unidade citada no texto do lead.

    Casa de forma acento/maiúscula-insensível, do nome mais longo para o mais
    curto (evita "Vila" casar antes de "Vila Madalena"). Retorna None se nada casar.
    """
    alvo = _sem_acento(texto)
    if not alvo:
        return None
    for nome in sorted(UNIDADES, key=len, reverse=True):
        if _sem_acento(nome) in alvo:
            return nome
    return None
