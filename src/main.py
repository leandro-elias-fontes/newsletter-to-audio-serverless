"""Orquestrador principal da execução diária serverless."""

from datetime import datetime
from pathlib import Path

from src.audio_generator import generate_audio_mp3
from src.config import Settings
from src.gmail_service import GmailService
from src.llm_client import GeminiRotatingClient, SQLitePromptCache
from src.newsletter_processor import build_podcast_script, classify_email
from src.schemas import EmailClassification
from src.telegram_notifier import send_audio_to_telegram, send_text_to_telegram


def run_pipeline(settings: Settings | None = None) -> None:
    """Executa o fluxo completo: Gmail -> Gemini -> Marcação seletiva -> edge-tts -> Telegram."""
    cfg = settings or Settings()
    subscribers_path = Path(cfg.subscribers_file) if cfg.subscribers_file else None
    cache = SQLitePromptCache(cfg.cache_db_path) if cfg.enable_local_cache else None
    llm = GeminiRotatingClient(
        api_keys=cfg.get_gemini_keys(),
        model=cfg.gemini_model,
        cache=cache,
    )
    print(
        f"[Pipeline] Iniciando busca no Gmail (query='{cfg.gmail_query}', max={cfg.max_emails_per_run})...",
        flush=True,
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
        msg = f"Nenhum e-mail não lido encontrado na janela configurada ({cfg.gmail_query})."
        print(msg, flush=True)
        if cfg.notify_when_empty:
            send_text_to_telegram(
                bot_token=cfg.telegram_bot_token,
                chat_id=cfg.telegram_chat_id,
                text=f"ℹ️ Briefing Diário: {msg}",
                subscribers_path=subscribers_path,
            )
        return

    print(f"[Pipeline] {len(unread_emails)} e-mail(s) encontrado(s). Classificando com Gemini...", flush=True)
    newsletter_items: list[EmailClassification] = []
    newsletter_ids: list[str] = []

    for idx, email in enumerate(unread_emails, start=1):
        print(f"[Pipeline] Analisando e-mail {idx}/{len(unread_emails)}: {email.subject}", flush=True)
        result = classify_email(llm, email)
        if result.is_newsletter:
            newsletter_items.append(result)
            newsletter_ids.append(email.message_id)

    if not newsletter_items:
        msg = f"{len(unread_emails)} e-mails analisados, mas nenhuma newsletter encontrada ({cfg.gmail_query})."
        print(msg, flush=True)
        if cfg.notify_when_empty:
            send_text_to_telegram(
                bot_token=cfg.telegram_bot_token,
                chat_id=cfg.telegram_chat_id,
                text=f"ℹ️ Briefing Diário: {msg}",
                subscribers_path=subscribers_path,
            )
        return

    today_str = datetime.now().strftime("%d/%m/%Y")
    print(f"[Pipeline] Gerando roteiro de áudio para {len(newsletter_items)} newsletter(s)...", flush=True)
    script = build_podcast_script(llm, newsletter_items, today_label=today_str)

    print("[Pipeline] Sintetizando áudio MP3 via edge-tts...", flush=True)
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
        subscribers_path=subscribers_path,
    )

    # Marca apenas as newsletters processadas como lidas; outros e-mails seguem intactos
    gmail.mark_as_read(newsletter_ids)
    print(
        f"Sucesso: {len(newsletter_ids)} newsletters resumidas, enviadas e marcadas como lidas.",
        flush=True,
    )


if __name__ == "__main__":
    run_pipeline()
