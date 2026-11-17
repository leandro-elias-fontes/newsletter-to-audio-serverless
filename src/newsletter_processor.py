"""Classificação de newsletters e geração de roteiro de áudio em português."""

from datetime import datetime

from src.llm_client import GeminiRotatingClient
from src.schemas import EmailClassification, RawEmail


def classify_email(client: GeminiRotatingClient, email: RawEmail) -> EmailClassification:
    """Classifica um e-mail limpo usando Structured Outputs do Gemini."""
    prompt = (
        "Você é um assistente de triagem de caixa de entrada.\n"
        "Analise o e-mail abaixo e decida se ele é uma NEWSLETTER informativa/técnica/editorial.\n"
        "Regras:\n"
        "- Marque is_newsletter=True APENAS para newsletters de conteúdo (tecnologia, IA, negócios, notícias, curadorias).\n"
        "- Marque is_newsletter=False para e-mails pessoais, notificações de trabalho/faculdade, faturas, recibos, códigos 2FA, redes sociais ou promoções de e-commerce.\n\n"
        f"Remetente: {email.sender}\n"
        f"Assunto: {email.subject}\n"
        f"Conteúdo:\n{email.clean_body}"
    )
    return client.generate_structured(prompt, EmailClassification)


def build_podcast_script(
    client: GeminiRotatingClient,
    newsletters: list[EmailClassification],
    today_label: str | None = None,
) -> str:
    """Consolida os resumos das newsletters em um roteiro fluido de 5 a 10 minutos para TTS."""
    date_str = today_label or datetime.now().strftime("%d/%m/%Y")
    digest_blocks = []
    for idx, item in enumerate(newsletters, start=1):
        takeaways = "; ".join(item.key_takeaways) if item.key_takeaways else "Sem pontos extras."
        digest_blocks.append(
            f"[{idx}] Fonte: {item.source_name} | Tema: {item.category}\n"
            f"Resumo: {item.core_summary}\n"
            f"Destaques: {takeaways}"
        )

    joined_digest = "\n\n".join(digest_blocks)
    prompt = (
        "Você é o apresentador de um briefing matinal pessoal em português do Brasil.\n"
        f"Data de hoje: {date_str}.\n"
        "Transforme os resumos abaixo em um roteiro de áudio natural, envolvente e direto ao ponto, "
        "com duração estimada entre 5 e 10 minutos de leitura em voz alta (aprox. 750 a 1300 palavras, "
        "ajustando proporcionalmente à quantidade de notícias para não enrolar).\n\n"
        "REGRAS OBRIGATÓRIAS PARA SÍNTESE DE VOZ (TTS):\n"
        "1. NÃO use formatação Markdown (*, **, #, -, URLs, emojis ou listas com marcadores).\n"
        "2. Escreva apenas texto corrido em parágrafos claros com pontuação natural para pausas.\n"
        "3. Comece com uma saudação rápida listando as fontes resumidas hoje.\n"
        "4. Conecte os assuntos por bloco temático com transições suaves.\n"
        "5. Termine com um encerramento curto e motivador.\n\n"
        f"NEWSLETTERS DO DIA:\n{joined_digest}"
    )
    return client.generate_text(prompt)
