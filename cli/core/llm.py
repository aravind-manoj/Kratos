import os
from dataclasses import dataclass
from typing import Literal
from langchain_core.language_models.chat_models import BaseChatModel

Role = Literal["main", "sub"]

PROVIDER_ALIASES: dict[str, str] = {
  "openai": "openai",
  "anthropic": "anthropic",
  "claude": "anthropic",
  "google": "google",
  "gemini": "google",
  "google-ai": "google",
  "google_ai": "google",
  "openrouter": "openrouter",
  "router": "openrouter",
  "groq": "groq",
}

# First match wins when multiple API keys are set without LLM_PROVIDER / --provider.
AUTO_DETECT_ORDER = ("openai", "anthropic", "google", "openrouter", "groq")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class ProviderSpec:
  env_keys: tuple[str, ...]
  main_model: str
  sub_model: str


PROVIDERS: dict[str, ProviderSpec] = {
  "openai": ProviderSpec(
    env_keys=("OPENAI_API_KEY",),
    main_model="gpt-5-mini",
    sub_model="gpt-5.5",
  ),
  "anthropic": ProviderSpec(
    env_keys=("ANTHROPIC_API_KEY",),
    main_model="claude-haiku-4-5",
    sub_model="claude-sonnet-4-6",
  ),
  "google": ProviderSpec(
    env_keys=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    main_model="gemini-3.1-flash-lite",
    sub_model="gemini-3.1-pro-preview",
  ),
  "openrouter": ProviderSpec(
    env_keys=("OPENROUTER_API_KEY",),
    main_model="anthropic/claude-sonnet-4.6",
    sub_model="anthropic/claude-opus-4.6",
  ),
  "groq": ProviderSpec(
    env_keys=("GROQ_API_KEY",),
    main_model="openai/gpt-oss-20b",
    sub_model="openai/gpt-oss-120b",
  ),
}


class LLMProviderError(Exception):
  pass


def normalize_provider(name: str) -> str:
  key = name.strip().lower().replace("_", "-")
  provider = PROVIDER_ALIASES.get(key)
  if not provider:
    supported = ", ".join(PROVIDERS)
    raise LLMProviderError(f"Unknown provider '{name}'. Supported: {supported}")
  return provider


def provider_env_key(provider: str) -> str | None:
  spec = PROVIDERS[provider]
  for env_key in spec.env_keys:
    if os.getenv(env_key):
      return env_key
  return None


def provider_has_credentials(provider: str) -> bool:
  return provider_env_key(provider) is not None


def list_configured_providers() -> list[str]:
  return [p for p in AUTO_DETECT_ORDER if provider_has_credentials(p)]


def resolve_provider(explicit: str | None = None) -> str:
  if explicit:
    provider = normalize_provider(explicit)
    if not provider_has_credentials(provider):
      spec = PROVIDERS[provider]
      keys = " or ".join(spec.env_keys)
      raise LLMProviderError(
        f"Provider '{provider}' selected but no API key found. Set {keys}."
      )
    return provider

  env_provider = os.getenv("LLM_PROVIDER")
  if env_provider:
    return resolve_provider(env_provider)

  configured = list_configured_providers()
  if len(configured) == 1:
    return configured[0]
  if len(configured) > 1:
    raise LLMProviderError(
      "Multiple LLM API keys found "
      f"({', '.join(configured)}). Set LLM_PROVIDER or pass --provider."
    )

  key_hints = ", ".join(
    f"{p}: {'/'.join(PROVIDERS[p].env_keys)}" for p in AUTO_DETECT_ORDER
  )
  raise LLMProviderError(
    f"No LLM API key found. Set one of: {key_hints}. "
    "Optionally set LLM_PROVIDER to choose when multiple keys are present."
  )


def _model_for(provider: str, role: Role) -> str:
  spec = PROVIDERS[provider]
  override = os.getenv("LLM_MAIN_MODEL" if role == "main" else "LLM_SUB_MODEL")
  if override:
    return override
  return spec.main_model if role == "main" else spec.sub_model


def create_llm(provider: str, *, role: Role) -> BaseChatModel:
  model = _model_for(provider, role)
  temperature = 0

  if provider == "openai":
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model, api_key=os.getenv("OPENAI_API_KEY"), temperature=temperature)

  if provider == "anthropic":
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=model, api_key=os.getenv("ANTHROPIC_API_KEY"), temperature=temperature)

  if provider == "google":
    from langchain_google_genai import ChatGoogleGenerativeAI

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=temperature)

  if provider == "openrouter":
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
      model=model,
      api_key=os.getenv("OPENROUTER_API_KEY"),
      base_url=os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL),
      temperature=temperature,
      default_headers={
        "HTTP-Referer": os.getenv("OPENROUTER_HTTP_REFERER", "https://github.com/kratos"),
        "X-Title": os.getenv("OPENROUTER_APP_NAME", "Kratos"),
      },
    )

  if provider == "groq":
    from langchain_groq import ChatGroq

    return ChatGroq(model=model, api_key=os.getenv("GROQ_API_KEY"), temperature=temperature)

  raise LLMProviderError(f"Unsupported provider: {provider}")


def create_main_llm(provider: str | None = None) -> BaseChatModel:
  return create_llm(resolve_provider(provider), role="main")


def create_sub_llm(provider: str | None = None) -> BaseChatModel:
  return create_llm(resolve_provider(provider), role="sub")
