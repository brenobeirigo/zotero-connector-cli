"""Institutional PDF providers, as configuration rather than as code.

The PDF fallback used to be one hard-coded University of Twente EZproxy URL
compiled into the module. That made the route unusable anywhere else and made
"the EBSCO route" and "this author's library subscription" the same thing.

A provider is now a named record: where its search lives, which databases it
covers, and what its download control is called. The UT route survives as one
built-in entry -- a tested configuration, not the universal default -- and any
other institution can add its own without touching this package.

Deliberately importable everywhere: no ``pywinauto``, no Windows, no browser.
Resolving and validating a provider is exactly the part that should be
testable on any machine.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

#: Environment variables. Both are optional; neither may hold a credential.
CONFIG_ENV = "ZOTERO_CONNECTOR_PROVIDERS"
DEFAULT_ENV = "ZOTERO_CONNECTOR_PROVIDER"

#: Where a provider file is looked for when nothing names one.
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "zotero-connector" / "providers.json"


class ProviderError(RuntimeError):
    """A provider was requested that does not exist, or is not usable."""


@dataclass(frozen=True)
class Provider:
    """One institution's route to a PDF.

    ``search_base`` is normally an EZproxy-rewritten host, which is what ties
    a route to an institution. It carries no credential: authentication is the
    browser session's business, and a provider file that contained one would
    be a password stored in plain text.
    """

    name: str
    search_base: str
    databases: str = ""
    #: Accessible-name prefix of the control that opens the PDF, lowercased
    #: and reduced to words. EBSCO's reads "Access now (PDF) <title>".
    access_control_prefix: str = "access now pdf"
    extra_query: dict = field(default_factory=dict)
    description: str = ""

    def search_url(self, title: str) -> str:
        query = {"q": title}
        if self.databases:
            query["db"] = self.databases
        query.update(self.extra_query)
        return f"{self.search_base}?{urlencode(query)}"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "searchBase": self.search_base,
            "databases": self.databases,
            "accessControlPrefix": self.access_control_prefix,
            "extraQuery": dict(self.extra_query),
            "description": self.description,
        }


#: The query EBSCO's advanced-results page expects, minus the title and the
#: database list. Shared by every EBSCO-shaped provider.
EBSCO_QUERY = {
    "autocorrect": "y",
    "expanders": "concept",
    "limiters": "None",
    "searchMode": "boolean",
    "searchSegment": "all-results",
    "skipResultsFetch": "true",
    "p": "1",
}

UTWENTE_EBSCO = Provider(
    name="utwente-ebsco",
    search_base=(
        "https://research-ebsco-com.ezproxy2.utwente.nl/"
        "c/i2dku7/search/advanced-results"
    ),
    databases=(
        "bth,nlebk,ecn,eric,hev,8gh,lxh,phl,pdh,pbh,psyh,bwh,ddu,trh,"
        "e001mww,cmedm"
    ),
    extra_query=dict(EBSCO_QUERY),
    description="University of Twente EBSCO via EZproxy. The tested reference route.",
)

#: Providers that ship with this package. One entry, and it is an example.
BUILTIN_PROVIDERS = {UTWENTE_EBSCO.name: UTWENTE_EBSCO}

#: Used when nothing else names a provider. Named explicitly so that reports
#: can say which route ran instead of implying there is only one.
FALLBACK_PROVIDER = UTWENTE_EBSCO.name

_REQUIRED = ("searchBase",)
_KNOWN_KEYS = {
    "searchBase",
    "databases",
    "accessControlPrefix",
    "extraQuery",
    "description",
}


def provider_from_dict(name: str, payload: dict) -> Provider:
    if not isinstance(payload, dict):
        raise ProviderError(f"Provider {name!r} must be an object, not {type(payload).__name__}")
    unknown = sorted(set(payload) - _KNOWN_KEYS)
    if unknown:
        raise ProviderError(
            f"Provider {name!r} has unknown key(s): {', '.join(unknown)}. "
            f"Known keys are: {', '.join(sorted(_KNOWN_KEYS))}"
        )
    for key in _REQUIRED:
        if not payload.get(key):
            raise ProviderError(f"Provider {name!r} is missing required key {key!r}")
    base = str(payload["searchBase"])
    if not base.startswith("https://"):
        # An EZproxy route carries a session cookie. Sending it over http
        # would leak the institutional session, so this is refused rather
        # than warned about.
        raise ProviderError(
            f"Provider {name!r} searchBase must be https, got {base.split(':', 1)[0]!r}"
        )
    extra = payload.get("extraQuery") or {}
    if not isinstance(extra, dict):
        raise ProviderError(f"Provider {name!r} extraQuery must be an object")
    return Provider(
        name=name,
        search_base=base,
        databases=str(payload.get("databases") or ""),
        access_control_prefix=str(
            payload.get("accessControlPrefix") or Provider.access_control_prefix
        ),
        extra_query={str(k): str(v) for k, v in extra.items()},
        description=str(payload.get("description") or ""),
    )


def load_providers(path: str | Path | None = None) -> tuple[dict, str | None]:
    """Read a provider file, returning ``(providers, declared default)``.

    Built-ins are always present. A file entry with a built-in's name replaces
    it, so a site can correct the shipped UT route without forking anything.
    """
    providers = dict(BUILTIN_PROVIDERS)
    resolved = Path(path) if path else None
    if resolved is None:
        from_env = os.environ.get(CONFIG_ENV)
        resolved = Path(from_env) if from_env else DEFAULT_CONFIG_PATH
        if not resolved.is_file():
            return providers, None
    if not resolved.is_file():
        raise ProviderError(f"Provider file not found: {resolved}")

    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Provider file {resolved} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProviderError(f"Provider file {resolved} must hold an object")

    entries = payload.get("providers")
    if entries is None:
        raise ProviderError(f"Provider file {resolved} has no 'providers' object")
    if not isinstance(entries, dict):
        raise ProviderError(f"Provider file {resolved}: 'providers' must be an object")
    for name, entry in entries.items():
        providers[name] = provider_from_dict(name, entry)

    declared = payload.get("default")
    if declared is not None and declared not in providers:
        raise ProviderError(
            f"Provider file {resolved} names default {declared!r}, which it does not define"
        )
    return providers, declared


def resolve_provider(
    name: str | None = None, config_path: str | Path | None = None
) -> Provider:
    """Pick the provider to run, most explicit source first.

    ``--provider``, then the file's own ``default``, then
    ``ZOTERO_CONNECTOR_PROVIDER``, then the shipped UT route. The last step
    keeps existing installs working; it is a fallback with a name, not a
    built-in assumption about which university you are at.
    """
    providers, declared = load_providers(config_path)
    chosen = name or declared or os.environ.get(DEFAULT_ENV) or FALLBACK_PROVIDER
    if chosen not in providers:
        known = ", ".join(sorted(providers))
        raise ProviderError(f"Unknown provider {chosen!r}. Available: {known}")
    return providers[chosen]
