"""Limpeza determinística de HTML de e-mails para economia extrema de tokens."""

import re

from bs4 import BeautifulSoup

_TRACKING_PATTERNS = (
    r"unsubscribe.*",
    r"cancelar inscrição.*",
    r"view in browser.*",
    r"ver no navegador.*",
)


def clean_email_html(raw_html: str, max_chars: int = 6000) -> str:
    """Remove tags de estilo, scripts, trackers e espaços excessivos antes do prompt."""
    if not raw_html:
        return ""

    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "head", "meta", "link", "noscript", "svg", "img"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    cleaned_lines: list[str] = []

    for line in lines:
        if not line:
            continue
        lowered = line.lower()
        if any(re.search(pattern, lowered) for pattern in _TRACKING_PATTERNS):
            continue
        cleaned_lines.append(line)

    collapsed = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines))
    return collapsed[:max_chars].strip()
