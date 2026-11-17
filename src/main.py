"""Orquestrador principal da execução diária serverless."""

from datetime import datetime
from pathlib import Path

from src.audio_generator import generate_audio_mp3
from src.config import Settings
from src.gmail_service import GmailService
from src.llm_client import GeminiRotatingClient, SQLitePromptCache
from src.newsletter_processor import build_podcast_script, classify_email
from src.schemas import EmailClassification
from src.telegram_notifier import send_audio_to_telegram


def run_pipeline(settings: Settings | None = None) -> None:
    """Executa o fluxo completo: Gmail -> Gemini -> Marcação seletiva -> edge-tts -> Telegram."""
    cfg = settings or Settings()
    cache = SQLitePromptCache(cfg.cache_db_path) if cfg.enable_local_cache else None
    llm = GeminiRotatingClient(
        api_keys=cfg.get_gemini_keys(),
        model=cfg.gemini_model,
        cache=cache,
    )
    gmail = GmailService(
        client_id=cfg.gmail_client_id,
        client_secret=cfg.gmail_client_secret,
        refresh_token=cfg.gmail_refresh_token,
    )

    unread_emails = gmail.fetch_unread_emails(
        query=cfg.gmail_query,
        max_results=cfg.max_emails_per_run,
    )
    if not unread_emails:
        print("Nenhum e-mail não lido encontrado na janela configurada.")
        return

    newsletter_items: list[EmailClassification] = []
    newsletter_ids: list[str] = []

    for email in unread_emails:
        result = classify_email(llm, email)
        if result.is_newsletter:
            newsletter_items.append(result)
            newsletter_ids.append(email.message_id)

    if not newsletter_items:
        print(f"{len(unread_emails)} e-mails analisados, mas nenhuma newsletter encontrada.")
        return

    today_str = datetime.now().strftime("%d/%m/%Y")
    script = build_podcast_script(llm, newsletter_items, today_label=today_str)

    audio_file = generate_audio_mp3(
        script_text=script,
        output_path=Path(f"newsletter_briefing_{datetime.now().strftime('%Y%m%d')}.mp3"),
        voice=cfg.tts_voice,
        rate=cfg.tts_rate,
    )

    sources = ", ".join(dict.fromkeys(item.source_name for item in newsletter_items))
    caption = (
        f"🎙️ Briefing de Newsletters ({today_str})\n"
        f"📰 Fontes ({len(newsletter_items)}): {sources}"
    )
    send_audio_to_telegram(
        bot_token=cfg.telegram_bot_token,
        chat_id=cfg.telegram_chat_id,
        audio_path=audio_file,
        title=f"Newsletters {today_str}",
        caption=caption,
    )

    # Marca apenas as newsletters processadas como lidas; outros e-mails seguem intactos
    gmail.mark_as_read(newsletter_ids)
    print(f"Sucesso: {len(newsletter_ids)} newsletters resumidas, enviadas e marcadas como lidas.")


if __name__ == "__main__":
    run_pipeline()
