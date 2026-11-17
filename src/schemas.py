"""Schemas Pydantic para tipagem estrita e Structured Outputs."""

from pydantic import BaseModel, Field


class RawEmail(BaseModel):
    """Representa um e-mail não lido recuperado da Gmail API."""

    message_id: str
    sender: str
    subject: str
    clean_body: str


class EmailClassification(BaseModel):
    """Saída estruturada do Gemini para distinguir newsletters de e-mails comuns."""

    is_newsletter: bool = Field(
        description="True apenas se for newsletter informativa/técnica/curadoria; False para e-mails pessoais, trabalho, faturas, códigos 2FA ou spam promocional."
    )
    source_name: str = Field(
        description="Nome curto da publicação ou remetente (ex: TLDR AI, The Batch, Filipe Deschamps)."
    )
    category: str = Field(
        description="Tema principal em português (ex: IA & Tech, Mercado, Engenharia de Software)."
    )
    core_summary: str = Field(
        description="Resumo objetivo e denso em português dos principais assuntos e insights."
    )
    key_takeaways: list[str] = Field(
        default_factory=list,
        description="Lista de 2 a 4 pontos-chave práticos extraídos da edição.",
    )
