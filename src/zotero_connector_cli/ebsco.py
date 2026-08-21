"""Driving an EBSCO-shaped results page to its PDF, for whichever institution.

The route itself -- host, databases, control name -- is a :mod:`providers`
record now, not a constant compiled in here. What stays in this module is the
part that genuinely is EBSCO- and Windows-specific: walking the results page
by keyboard and recognising the download control by its accessible name.
"""

from __future__ import annotations

import re
import time

from pywinauto.keyboard import send_keys
from pywinauto.uia_defines import IUIA
from pywinauto.uia_element_info import UIAElementInfo

from .providers import UTWENTE_EBSCO, Provider
from .windows import Window, activate_window, is_foreground

#: Kept so existing callers and recorded reports keep resolving. The values
#: now live on the built-in provider rather than being the only route this
#: package knows about.
EBSCO_SEARCH_BASE = UTWENTE_EBSCO.search_base
EBSCO_DATABASES = UTWENTE_EBSCO.databases


def build_search_url(provider: Provider, title: str) -> str:
    """The provider's advanced-results URL for one exact title."""
    return provider.search_url(title)


def build_ebsco_search_url(title: str, provider: Provider | None = None) -> str:
    """Back-compatible spelling of :func:`build_search_url`."""
    return (provider or UTWENTE_EBSCO).search_url(title)


def _normalized_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def matches_pdf_access_control(
    control_type: str,
    name: str,
    title: str,
    prefix: str = UTWENTE_EBSCO.access_control_prefix,
) -> bool:
    """Is this focused control the download for *this* exact title?

    The title has to appear in the control's own accessible name. Matching the
    prefix alone would happily open whichever record the page rendered first.
    """
    normalized_name = _normalized_text(name)
    normalized_title = _normalized_text(title)
    normalized_prefix = _normalized_text(prefix)
    return (
        control_type == "Button"
        and bool(normalized_prefix)
        and normalized_name.startswith(normalized_prefix + " ")
        and bool(normalized_title)
        and normalized_title in normalized_name
    )


def _focused_control() -> tuple[str, str]:
    element = IUIA().iuia.GetFocusedElement()
    info = UIAElementInfo(element)
    return info.control_type, (info.name or "").strip()


def activate_pdf_access(
    window: Window,
    title: str,
    max_tabs: int = 220,
    tab_wait: float = 0.04,
    provider: Provider | None = None,
) -> dict | None:
    """Activate the provider's exact-title PDF control via UI Automation."""
    prefix = (provider or UTWENTE_EBSCO).access_control_prefix
    activate_window(window)
    send_keys("{F6}")
    time.sleep(max(0, tab_wait))
    for index in range(max_tabs):
        if not is_foreground(window):
            raise RuntimeError(
                "The EBSCO browser window lost focus during automatic navigation"
            )
        control_type, name = _focused_control()
        if matches_pdf_access_control(control_type, name, title, prefix):
            send_keys("{ENTER}")
            return {
                "tabIndex": index,
                "controlType": control_type,
                "accessibleName": name,
            }
        send_keys("{TAB}")
        time.sleep(max(0, tab_wait))
    return None
