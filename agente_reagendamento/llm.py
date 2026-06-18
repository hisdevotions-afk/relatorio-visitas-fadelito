"""Camada de LLM com dois provedores e failover automático bidirecional.

Provedores (ambos OpenAI-compatible): NVIDIA NIM e Groq. O primário (config.LLM_PRIMARY)
atende; se ele falhar por cota/rate-limit, o backup assume — e vice-versa. Quando um
provedor estoura a cota, ele entra em "cooldown" e é pulado por um tempo, para não
desperdiçar chamadas batendo num provedor esgotado.

Exposto:
    invoke(messages, max_tokens=..., temperature=...) -> str
        messages: lista de objetos LangChain (System/Human/AIMessage) OU dicts
                  {"role": ..., "content": ...}. Retorna o texto da resposta.
    LLMIndisponivel: levantada quando TODOS os provedores falham.
"""
import time

from openai import OpenAI

import config
import logger

COOLDOWN_SEGUNDOS = 1800  # 30 min: tempo que um provedor esgotado fica de fora
TENTATIVAS_POR_PROVEDOR = 2


class LLMIndisponivel(Exception):
    """Levantada quando nenhum provedor consegue responder."""


class _Provedor:
    def __init__(self, nome: str, base_url: str, api_key: str, model: str, extra_body: dict | None = None):
        self.nome = nome
        self.model = model
        self.extra_body = extra_body or {}
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=60.0)
        self.cooldown_ate = 0.0

    def disponivel(self) -> bool:
        return time.time() >= self.cooldown_ate

    def chamar(self, messages: list[dict], max_tokens: int, temperature: float) -> str:
        kwargs = dict(model=self.model, messages=messages,
                      max_tokens=max_tokens, temperature=temperature)
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        resp = self._client.chat.completions.create(**kwargs)
        return (resp.choices[0].message.content or "").strip()


_provedores: list[_Provedor] | None = None


def _construir_provedores() -> list[_Provedor]:
    provs: dict[str, _Provedor] = {}
    if config.NVIDIA_API_KEY:
        provs["nvidia"] = _Provedor(
            "nvidia", config.NVIDIA_BASE_URL, config.NVIDIA_API_KEY, config.NVIDIA_MODEL,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    if config.GROQ_API_KEY:
        provs["groq"] = _Provedor(
            "groq", config.GROQ_BASE_URL, config.GROQ_API_KEY, config.GROQ_MODEL,
        )
    # ordena: primário primeiro, backup depois
    ordem = [config.LLM_PRIMARY] + [n for n in provs if n != config.LLM_PRIMARY]
    return [provs[n] for n in ordem if n in provs]


def _get_provedores() -> list[_Provedor]:
    global _provedores
    if _provedores is None:
        _provedores = _construir_provedores()
    return _provedores


def _eh_cota_ou_rate_limit(exc: Exception) -> bool:
    txt = str(exc).lower()
    status = getattr(exc, "status_code", None)
    return status == 429 or "rate" in txt or "quota" in txt or "limit" in txt or "429" in txt


def invoke(messages, max_tokens: int = 1024, temperature: float = 0.6) -> str:
    """Invoca o LLM com failover entre provedores. Levanta LLMIndisponivel se todos falharem."""
    msgs = _normalizar(messages)
    provs = _get_provedores()
    if not provs:
        raise LLMIndisponivel("Nenhum provedor de LLM configurado (NVIDIA_API_KEY/GROQ_API_KEY)")

    ultimo_erro: Exception = LLMIndisponivel("sem tentativas")

    # 1ª passada: só provedores fora de cooldown, na ordem (primário -> backup)
    # 2ª passada: ignora cooldown (último recurso, caso todos estejam marcados)
    for ignorar_cooldown in (False, True):
        for prov in provs:
            if not ignorar_cooldown and not prov.disponivel():
                continue
            for tentativa in range(TENTATIVAS_POR_PROVEDOR):
                try:
                    texto = prov.chamar(msgs, max_tokens, temperature)
                    if texto:
                        return texto
                    raise ValueError("resposta vazia do provedor")
                except Exception as exc:
                    ultimo_erro = exc
                    if _eh_cota_ou_rate_limit(exc):
                        prov.cooldown_ate = time.time() + COOLDOWN_SEGUNDOS
                        logger.aviso(f"LLM '{prov.nome}' esgotado/rate-limit — backup assume "
                                     f"(cooldown {COOLDOWN_SEGUNDOS // 60}min): {str(exc)[:120]}")
                        break  # não insiste no mesmo provedor; vai para o próximo
                    logger.aviso(f"LLM '{prov.nome}' falhou (tentativa {tentativa + 1}): {str(exc)[:120]}")
                    time.sleep(min(2 ** tentativa, 4))
        if not ignorar_cooldown:
            logger.aviso("Todos os provedores em cooldown — tentando mesmo assim (último recurso)")

    raise LLMIndisponivel(str(ultimo_erro))


def _normalizar(messages) -> list[dict]:
    """Converte mensagens LangChain (ou dicts) para o formato {role, content} do OpenAI SDK."""
    _MAP = {"system": "system", "human": "user", "ai": "assistant",
            "user": "user", "assistant": "assistant"}
    out: list[dict] = []
    for m in messages:
        if isinstance(m, dict):
            out.append({"role": _MAP.get(m.get("role", "user"), "user"),
                        "content": m.get("content", "")})
        else:
            tipo = getattr(m, "type", "user")  # LangChain: 'system' | 'human' | 'ai'
            out.append({"role": _MAP.get(tipo, "user"), "content": m.content})
    return out
