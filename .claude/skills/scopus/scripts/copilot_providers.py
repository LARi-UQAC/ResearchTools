"""
copilot_providers.py - provider chain and latest-model resolution for the GitHub leg of the
deliberation panel.

Two GitHub products are easy to confuse and this module keeps them apart.

- GitHub Copilot (api.githubcopilot.com) is the subscription product whose model picker offers
  GPT, Gemini, Kimi, MAI and others. It refuses a personal access token: it wants a short-lived
  Copilot token minted from an OAuth login, supplied here through COPILOT_TOKEN.
- GitHub Models (models.github.ai, and the older models.inference.ai.azure.com) was the free
  inference API a PAT in GITHUB_TOKEN could call. It was retired on 2026-07-30 and now answers
  410 github_models_retirement_brownout on every route.

Both stay in the chain, tried in order, because a chain is what survives the next retirement.
Nothing here reads a credential store or performs an OAuth flow; a provider whose token is
absent is skipped.

The model is never hardcoded. Each provider is asked for its catalog and the newest text chat
entry wins, which is the same run-time resolution the Gemini leg uses. A frozen default is how
this leg sat on gpt-4o long after newer models shipped, and how the Gemini leg died on the
retired gemini-2.0-flash.
"""

import json
import os
import re
import urllib.error
import urllib.request

# Ordered provider chain. `qualified` says whether the host names a model with its publisher
# prefix ("openai/gpt-4o-mini") or bare ("gpt-4o-mini"); the two GitHub Models hosts differ.
PROVIDERS = (
    {
        "name": "copilot",
        "base": "https://api.githubcopilot.com",
        "catalog": "https://api.githubcopilot.com/models",
        "token_env": ("COPILOT_TOKEN", "GITHUB_COPILOT_TOKEN"),
        "headers": {"Editor-Version": "ResearchTools/1.0",
                    "Copilot-Integration-Id": "vscode-chat"},
        "qualified": False,
    },
    {
        "name": "github-models",
        "base": "https://models.github.ai/inference",
        "catalog": "https://models.github.ai/catalog/models",
        "token_env": ("GITHUB_TOKEN",),
        "headers": {},
        "qualified": True,
    },
    {
        "name": "azure-inference",
        "base": "https://models.inference.ai.azure.com",
        "catalog": "https://models.inference.ai.azure.com/models",
        "token_env": ("GITHUB_TOKEN",),
        "headers": {},
        "qualified": False,
    },
)

# Last-resort model when no catalog answers. Deliberately a widely-available id and NOT a claim
# about what is newest: if this value is what runs, resolution failed and the run is on a known
# stale model.
FALLBACK_MODEL = "gpt-4o"

# Catalog entries that are not text chat reviewers even when the family name looks right.
_NON_TEXT_MARKERS = ("embedding", "embed", "image", "vision-encoder", "tts", "audio", "whisper",
                     "speech", "moderation", "rerank", "dall-e", "video")

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)?)")
_DATE_RE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")

_RESOLVED: dict = {}  # per-process cache keyed by publisher preference; a catalog is one call


# GitHub's own exchange route: a user OAuth token buys a short-lived Copilot token. A personal
# access token is refused here by design ("Personal Access Tokens are not supported for this
# endpoint"), which is why COPILOT_TOKEN and GITHUB_TOKEN are different credentials and not
# interchangeable. Obtain the OAuth token yourself (`gh auth login`, then `gh auth token`) and
# put it in GH_OAUTH_TOKEN; nothing here reads a credential store or runs a login flow.
_COPILOT_EXCHANGE_URL = "https://api.github.com/copilot_internal/v2/token"
_OAUTH_ENV = ("GH_OAUTH_TOKEN", "GITHUB_OAUTH_TOKEN")


def exchange_copilot_token(timeout: int = 20) -> str:
    """Mint a short-lived Copilot token from a user OAuth token in the environment. Returns ''
    when no OAuth token is set or the exchange is refused; the caller then skips the provider."""
    oauth = ""
    for name in _OAUTH_ENV:
        oauth = os.environ.get(name, "").strip()
        if oauth:
            break
    if not oauth:
        return ""
    request = urllib.request.Request(
        _COPILOT_EXCHANGE_URL,
        headers={"Authorization": f"Bearer {oauth}", "Accept": "application/json",
                 "Editor-Version": "ResearchTools/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except Exception:  # refused token, wrong token type, or network failure
        return ""
    token = payload.get("token")
    return token.strip() if isinstance(token, str) else ""


def provider_token(provider: dict) -> str:
    """First non-empty environment token declared by this provider, or '' when none is set.
    The Copilot provider additionally falls back to exchanging an OAuth token for one."""
    for name in provider["token_env"]:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    if provider["name"] == "copilot":
        return exchange_copilot_token()
    return ""


def fetch_catalog(provider: dict, token: str, timeout: int = 30) -> list:
    """Read one provider catalog and return its entry list. Returns [] on any failure, so a
    retired or unreachable host falls through to the next provider instead of raising."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    headers.update(provider.get("headers") or {})
    request = urllib.request.Request(provider["catalog"], headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except Exception:  # HTTP status, network failure, or a non-JSON body
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "models", "value"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def entry_id(entry: dict) -> str:
    """The model id of one catalog entry, across the field names the hosts disagree on."""
    for key in ("id", "name", "model", "original_name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def is_text_chat(entry: dict, model_id: str) -> bool:
    """Keep only text chat models: uses the declared task and modalities when the catalog
    provides them, and falls back to reading the id when it does not."""
    lowered = model_id.lower()
    if any(marker in lowered for marker in _NON_TEXT_MARKERS):
        return False
    task = str(entry.get("task") or entry.get("model_type") or "").lower()
    if task and task not in ("chat-completion", "chat", "text-generation", "completion"):
        return False
    capabilities = entry.get("capabilities")
    if isinstance(capabilities, dict) and capabilities.get("supports") is not None:
        pass  # Copilot nests its flags; absence of a chat flag is not evidence of no chat
    modalities = entry.get("supported_input_modalities")
    if isinstance(modalities, list) and modalities:
        if "text" not in [str(m).lower() for m in modalities]:
            return False
    return True


def recency_key(entry: dict, model_id: str) -> tuple:
    """
    --------------------------------------------------------------------------
    Purpose:
        Rank one catalog entry by how recent it is, so 'latest' is decided from
        the catalog rather than from a maintainer's memory. Ordering, most
        significant first: the numeric family version read from the id, then the
        catalog's own version or publication date, then stable over preview, then
        the id itself so ties resolve deterministically.

        Generation before date, deliberately. A publisher that re-publishes an
        older family gives gpt-4o a fresher date than gpt-5.2, and a date-first
        rank would then call the older model the latest. The date only separates
        two releases of the SAME family. Stable only breaks a tie at equal
        version, so a newer-generation preview still outranks an older stable,
        which is the same rule resolve_gemini_model() applies (it is why the
        panel runs gemini-3.1-pro-preview and not gemini-2.5-pro).

        Comparing family versions across publishers is meaningless, so callers
        rank inside one preferred publisher whenever that publisher has entries.

    Inputs:
        entry (dict): one catalog record.
        model_id (str): the id already extracted from that record.

    Outputs:
        key (tuple): sort key, larger is newer.
    --------------------------------------------------------------------------
    """
    stamp = ""
    for field in ("version", "publication_date", "created_at", "updated_at", "release_date"):
        value = entry.get(field)
        if isinstance(value, str) and _DATE_RE.search(value):
            stamp = "".join(_DATE_RE.search(value).groups())
            break
    date_rank = int(stamp) if stamp else 0

    tail = model_id.split("/")[-1]
    match = _VERSION_RE.search(tail)
    version_rank = float(match.group(1)) if match else 0.0

    lowered = model_id.lower()
    stable_rank = 0 if any(t in lowered for t in ("preview", "-rc", "alpha", "beta")) else 1
    return (version_rank, date_rank, stable_rank, model_id)


def rank_catalog(entries: list, publisher: str = "openai") -> str:
    """Newest text chat id in one catalog, preferring `publisher` when it has an entry.
    Returns '' when the catalog holds no usable chat model."""
    candidates = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = entry_id(entry)
        if not model_id or not is_text_chat(entry, model_id):
            continue
        candidates.append((model_id, recency_key(entry, model_id)))
    if not candidates:
        return ""
    wanted = publisher.lower()
    preferred = [c for c in candidates
                 if c[0].lower().startswith(f"{wanted}/")
                 or ("/" not in c[0] and wanted in c[0].lower())]
    return max(preferred or candidates, key=lambda c: c[1])[0]


def resolve_latest_model(publisher: str = "openai") -> tuple:
    """
    --------------------------------------------------------------------------
    Purpose:
        Walk the provider chain and return the newest model the first answering
        catalog offers, together with the provider that answered. Skips a provider
        whose token is unset. Caches per process, since the catalog is one HTTP
        call and the answer cannot change mid-run.

    Inputs:
        publisher (str): preferred publisher prefix ('openai' by default); when
            that publisher has no entry, the newest entry of any publisher wins.

    Outputs:
        (model, provider_name) (tuple[str, str]): the resolved id and the provider
            it came from, or (FALLBACK_MODEL, '') when no catalog answered.
    --------------------------------------------------------------------------
    """
    if publisher in _RESOLVED:
        return _RESOLVED[publisher]
    for provider in PROVIDERS:
        token = provider_token(provider)
        if not token:
            continue
        model = rank_catalog(fetch_catalog(provider, token), publisher)
        if model:
            _RESOLVED[publisher] = (model, provider["name"])
            return _RESOLVED[publisher]
    _RESOLVED[publisher] = (FALLBACK_MODEL, "")
    return _RESOLVED[publisher]


def endpoint_model(model: str, qualified: bool) -> str:
    """Adapt a model id to one host's naming: models.github.ai wants the publisher prefix
    ('openai/gpt-4o-mini'), Copilot and the Azure host want the bare id ('gpt-4o-mini')."""
    if qualified:
        return model if "/" in model else f"openai/{model}"
    return model.split("/")[-1]


def reset_cache() -> None:
    """Drop the per-process resolution cache. For tests, which vary the fake catalog."""
    _RESOLVED.clear()
