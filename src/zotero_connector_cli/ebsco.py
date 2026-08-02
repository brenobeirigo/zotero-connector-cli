from __future__ import annotations

import re
import time
from urllib.parse import urlencode

from pywinauto.keyboard import send_keys
from pywinauto.uia_defines import IUIA
from pywinauto.uia_element_info import UIAElementInfo

from .windows import Window, activate_window, is_foreground


EBSCO_SEARCH_BASE = (
    "https://research-ebsco-com.ezproxy2.utwente.nl/"
    "c/i2dku7/search/advanced-results"
)
EBSCO_DATABASES = (
    "bth,nlebk,ecn,eric,hev,8gh,lxh,phl,pdh,pbh,psyh,bwh,ddu,trh,"
    "e001mww,cmedm"
)


def build_ebsco_search_url(title: str) -> str:
    query = urlencode(
        {
            "q": title,
            "autocorrect": "y",
            "db": EBSCO_DATABASES,
            "expanders": "concept",
            "limiters": "None",
            "searchMode": "boolean",
            "searchSegment": "all-results",
            "skipResultsFetch": "true",
            "p": "1",
        }
    )
    return f"{EBSCO_SEARCH_BASE}?{query}"


def _normalized_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def matches_pdf_access_control(control_type: str, name: str, title: str) -> bool:
    normalized_name = _normalized_text(name)
    normalized_title = _normalized_text(title)
    return (
        control_type == "Button"
        and normalized_name.startswith("access now pdf ")
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
) -> dict | None:
    """Activate EBSCO's exact-title Access now (PDF) control via UI Automation."""
    activate_window(window)
    send_keys("{F6}")
    time.sleep(max(0, tab_wait))
    for index in range(max_tabs):
        if not is_foreground(window):
            raise RuntimeError(
                "The EBSCO browser window lost focus during automatic navigation"
            )
        control_type, name = _focused_control()
        if matches_pdf_access_control(control_type, name, title):
            send_keys("{ENTER}")
            return {
                "tabIndex": index,
                "controlType": control_type,
                "accessibleName": name,
            }
        send_keys("{TAB}")
        time.sleep(max(0, tab_wait))
    return None
