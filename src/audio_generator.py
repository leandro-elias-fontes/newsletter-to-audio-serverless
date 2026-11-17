"""Síntese de áudio neural gratuita em português via edge-tts."""

import asyncio
from pathlib import Path

import edge_tts


async def _synthesize_async(text: str, output_path: Path, voice: str, rate: str) -> None:
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(str(output_path))


def generate_audio_mp3(
    script_text: str,
    output_path: str | Path,
    voice: str = "pt-BR-AntonioNeural",
    rate: str = "+5%",
) -> Path:
    """Converte o roteiro em arquivo .mp3 usando voz neural gratuita da Microsoft Edge."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_synthesize_async(script_text, target, voice, rate))
    return target
