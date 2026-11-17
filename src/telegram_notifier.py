"""Envio do arquivo de áudio .mp3 para o Telegram via Bot API."""

from pathlib import Path

import httpx


def send_audio_to_telegram(
    bot_token: str,
    chat_id: str,
    audio_path: Path,
    title: str,
    caption: str,
) -> None:
    """Envia o .mp3 gerado diretamente para o chat configurado no Telegram."""
    url = f"https://api.telegram.org/bot{bot_token}/sendAudio"
    with audio_path.open("rb") as audio_file:
        response = httpx.post(
            url,
            data={
                "chat_id": chat_id,
                "title": title,
                "performer": "Briefing Diário AI",
                "caption": caption[:1024],
            },
            files={"audio": (audio_path.name, audio_file, "audio/mpeg")},
            timeout=60.0,
        )
    response.raise_for_status()
