"""Testes unitários offline (custo zero de tokens) para o pipeline de newsletters."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config import Settings
from src.html_cleaner import clean_email_html
from src.llm_client import SQLitePromptCache
from src.main import run_pipeline
from src.schemas import EmailClassification, RawEmail


def test_clean_email_html_removes_noise_and_tracking() -> None:
    raw = """
    <html>
      <head><style>body { color: red; }</style></head>
      <body>
        <script>alert('x')</script>
        <h1>Edição #42 - IA Hoje</h1>
        <p>Novo modelo open-source lançado com suporte a tool calling.</p>
        <p>Unsubscribe from this list anytime.</p>
      </body>
    </html>
    """
    cleaned = clean_email_html(raw)
    assert "Edição #42 - IA Hoje" in cleaned
    assert "Novo modelo open-source" in cleaned
    assert "color: red" not in cleaned
    assert "Unsubscribe" not in cleaned


def test_sqlite_prompt_cache_roundtrip(tmp_path: Path) -> None:
    db_file = tmp_path / "cache.sqlite"
    cache = SQLitePromptCache(str(db_file))
    assert cache.get("gemini-2.5-flash", "oi", "text") is None
    cache.set("gemini-2.5-flash", "oi", "olá", "text")
    assert cache.get("gemini-2.5-flash", "oi", "text") == "olá"


@patch("src.main.send_audio_to_telegram")
@patch("src.main.generate_audio_mp3")
@patch("src.main.build_podcast_script")
@patch("src.main.classify_email")
@patch("src.main.GmailService")
def test_pipeline_marks_only_newsletters_as_read(
    mock_gmail_cls: MagicMock,
    mock_classify: MagicMock,
    mock_build_script: MagicMock,
    mock_audio: MagicMock,
    mock_telegram: MagicMock,
    tmp_path: Path,
) -> None:
    mock_gmail = mock_gmail_cls.return_value
    mock_gmail.fetch_unread_emails.return_value = [
        RawEmail(
            message_id="msg_news_1",
            sender="TLDR AI <dan@tldrnewsletter.com>",
            subject="TLDR AI: Gemini updates",
            clean_body="Conteúdo técnico sobre Gemini.",
        ),
        RawEmail(
            message_id="msg_bank_2",
            sender="banco@exemplo.com",
            subject="Fatura fechada",
            clean_body="Sua fatura vence dia 20.",
        ),
    ]

    mock_classify.side_effect = [
        EmailClassification(
            is_newsletter=True,
            source_name="TLDR AI",
            category="IA & Tech",
            core_summary="Novidades sobre Gemini e agentes.",
            key_takeaways=["Structured outputs"],
        ),
        EmailClassification(
            is_newsletter=False,
            source_name="Banco",
            category="Financeiro",
            core_summary="Fatura mensal.",
            key_takeaways=[],
        ),
    ]
    mock_build_script.return_value = "Olá, bem-vindo ao briefing de hoje."
    fake_mp3 = tmp_path / "briefing.mp3"
    fake_mp3.write_bytes(b"ID3")
    mock_audio.return_value = fake_mp3

    cfg = Settings(
        gemini_api_key_1="fake-key-1",
        gmail_client_id="cid",
        gmail_client_secret="csec",
        gmail_refresh_token="rtok",
        telegram_bot_token="bot",
        telegram_chat_id="123",
        enable_local_cache=False,
    )
    run_pipeline(cfg)

    mock_gmail.mark_as_read.assert_called_once_with(["msg_news_1"])
    mock_telegram.assert_called_once()
