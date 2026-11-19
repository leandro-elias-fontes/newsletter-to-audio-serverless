"""Envio do arquivo de áudio .mp3 e notificações para inscritos no Telegram via Bot API."""

import json
from pathlib import Path

import httpx


def _parse_chat_ids(chat_id: str | list[str]) -> list[str]:
    if isinstance(chat_id, list):
        raw = chat_id
    else:
        raw = str(chat_id).split(",")
    result: list[str] = []
    for item in raw:
        cleaned = str(item).strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def load_saved_subscribers(subscribers_path: Path) -> list[str]:
    """Carrega a lista persistida de chat_ids inscritos."""
    if not subscribers_path.exists():
        return []
    try:
        data = json.loads(subscribers_path.read_text(encoding="utf-8"))
        items = data.get("chat_ids", []) if isinstance(data, dict) else data
        if isinstance(items, list):
            return _parse_chat_ids([str(x) for x in items])
    except (OSError, ValueError) as exc:
        print(f"[Telegram] Aviso ao ler {subscribers_path}: {exc}", flush=True)
    return []


def save_subscribers(subscribers_path: Path, chat_ids: list[str]) -> None:
    """Salva a lista atualizada de chat_ids inscritos em disco."""
    deduped = _parse_chat_ids(chat_ids)
    payload = json.dumps({"chat_ids": deduped}, indent=2, ensure_ascii=False) + "\n"
    if subscribers_path.exists():
        try:
            if subscribers_path.read_text(encoding="utf-8") == payload:
                return
        except OSError:
            pass
    subscribers_path.write_text(payload, encoding="utf-8")


def discover_bot_subscribers(bot_token: str) -> list[str]:
    """Consulta getUpdates na Bot API para descobrir todos os usuários que deram /start no bot."""
    if not bot_token:
        return []
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    discovered: list[str] = []
    try:
        response = httpx.get(url, timeout=15.0)
        response.raise_for_status()
        payload = response.json()
        updates = payload.get("result", []) if isinstance(payload, dict) else []
        for upd in updates:
            if not isinstance(upd, dict):
                continue
            for key in ("message", "edited_message", "my_chat_member", "callback_query"):
                obj = upd.get(key)
                if not isinstance(obj, dict):
                    continue
                chat = obj.get("chat") or (
                    obj.get("message", {}).get("chat")
                    if isinstance(obj.get("message"), dict)
                    else None
                )
                if isinstance(chat, dict) and chat.get("id") is not None:
                    cid = str(chat["id"]).strip()
                    if cid and cid not in discovered:
                        discovered.append(cid)
    except (httpx.HTTPError, ValueError, OSError) as exc:
        print(f"[Telegram] Aviso ao consultar getUpdates: {exc}", flush=True)
    return discovered


def resolve_and_persist_subscribers(
    bot_token: str,
    seed_chat_ids: str | list[str],
    subscribers_path: Path | None = None,
) -> list[str]:
    """Combina chat_ids configurados, salvos em arquivo e descobertos via /start no bot."""
    combined: list[str] = []
    for cid in _parse_chat_ids(seed_chat_ids):
        if cid not in combined:
            combined.append(cid)

    if subscribers_path is not None:
        for cid in load_saved_subscribers(subscribers_path):
            if cid not in combined:
                combined.append(cid)

    for cid in discover_bot_subscribers(bot_token):
        if cid not in combined:
            combined.append(cid)
            print(f"[Telegram] Novo inscrito descoberto via getUpdates: {cid}", flush=True)

    if subscribers_path is not None and combined:
        save_subscribers(subscribers_path, combined)

    return combined


def send_audio_to_telegram(
    bot_token: str,
    chat_id: str | list[str],
    audio_path: Path,
    title: str,
    caption: str,
    subscribers_path: Path | None = None,
) -> int:
    """Envia o .mp3 para todos os inscritos, reutilizando o file_id após o primeiro upload."""
    recipients = resolve_and_persist_subscribers(
        bot_token=bot_token,
        seed_chat_ids=chat_id,
        subscribers_path=subscribers_path,
    )
    if not recipients:
        raise ValueError("Nenhum chat_id configurado ou descoberto para envio no Telegram.")

    url = f"https://api.telegram.org/bot{bot_token}/sendAudio"
    file_id: str | None = None
    sent_count = 0
    last_exc: Exception | None = None

    for target_id in recipients:
        try:
            if file_id:
                response = httpx.post(
                    url,
                    data={
                        "chat_id": target_id,
                        "audio": file_id,
                        "title": title,
                        "performer": "Briefing Diário AI",
                        "caption": caption[:1024],
                    },
                    timeout=30.0,
                )
            else:
                with audio_path.open("rb") as audio_file:
                    response = httpx.post(
                        url,
                        data={
                            "chat_id": target_id,
                            "title": title,
                            "performer": "Briefing Diário AI",
                            "caption": caption[:1024],
                        },
                        files={"audio": (audio_path.name, audio_file, "audio/mpeg")},
                        timeout=60.0,
                    )
            response.raise_for_status()
            sent_count += 1
            if not file_id:
                try:
                    body = response.json()
                    if isinstance(body, dict):
                        extracted = body.get("result", {}).get("audio", {}).get("file_id")
                        if isinstance(extracted, str) and extracted:
                            file_id = extracted
                except ValueError:
                    file_id = None
            print(f"[Telegram] Áudio enviado com sucesso para chat_id={target_id}.", flush=True)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            last_exc = exc
            print(f"[Telegram] Falha ao enviar áudio para chat_id={target_id}: {exc}", flush=True)

    if sent_count == 0 and last_exc is not None:
        raise last_exc
    return sent_count


def send_text_to_telegram(
    bot_token: str,
    chat_id: str | list[str],
    text: str,
    subscribers_path: Path | None = None,
) -> int:
    """Envia mensagem de texto curta (ex.: aviso de execução manual sem newsletters novas)."""
    recipients = resolve_and_persist_subscribers(
        bot_token=bot_token,
        seed_chat_ids=chat_id,
        subscribers_path=subscribers_path,
    )
    if not recipients:
        return 0

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    sent_count = 0
    for target_id in recipients:
        try:
            response = httpx.post(
                url,
                data={"chat_id": target_id, "text": text[:4096]},
                timeout=20.0,
            )
            response.raise_for_status()
            sent_count += 1
            print(f"[Telegram] Aviso enviado para chat_id={target_id}.", flush=True)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            print(f"[Telegram] Falha ao enviar aviso para chat_id={target_id}: {exc}", flush=True)
    return sent_count
