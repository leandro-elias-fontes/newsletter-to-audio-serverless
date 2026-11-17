# Newsletter-to-Audio

Eu assinava várias newsletters técnicas e acabava acumulando quase todas na caixa de entrada sem tempo para ler. Criei esse script para resumir as edições não lidas do dia em um áudio de 5 a 10 minutos e mandar direto no meu Telegram toda manhã, rodando de graça no GitHub Actions.

## Como funciona

1. Um cron no GitHub Actions roda todo dia às 07h (BRT).
2. O script busca os e-mails não lidos das últimas 24h via **Gmail API**.
3. O **BeautifulSoup** limpa o HTML (CSS, scripts, trackers e rodapés de descadastro) antes de mandar o texto para o modelo.
4. O **Gemini 2.5 Flash** (com saída estruturada em Pydantic) separa o que é newsletter do que é e-mail comum (banco, faculdade, pessoal, etc.).
5. Apenas os e-mails classificados como newsletter são marcados como lidos no Gmail — o resto fica intacto.
6. O modelo gera um roteiro corrido em português, o **edge-tts** converte em `.mp3` e o arquivo vai para o meu chat no **Telegram**.

```
Gmail (não lidos) -> BeautifulSoup -> Gemini 2.5 Flash -> marca só newsletters como lidas
                                              |
                                              v
                                     roteiro PT-BR -> edge-tts (.mp3) -> Telegram
```

## Estrutura

- `src/gmail_service.py`: leitura de e-mails e remoção da label `UNREAD` apenas nas newsletters processadas.
- `src/html_cleaner.py`: limpeza determinística do HTML.
- `src/llm_client.py`: cliente do `google-genai` com rotação entre duas chaves gratuitas e cache SQLite opcional para testes locais.
- `src/newsletter_processor.py`: classificação e geração do roteiro.
- `src/audio_generator.py`: síntese de voz com `edge-tts`.
- `src/telegram_notifier.py`: envio do `.mp3` pela Bot API do Telegram.
- `scripts/auth_gmail.py`: script local para gerar o `refresh_token` OAuth2 do Gmail uma única vez.

## Configuração

### 1. Instalar dependências e rodar testes

```bash
pip install -e .
pytest -v
```

### 2. Gerar credenciais do Gmail (1 vez)

No Google Cloud Console, ative a **Gmail API**, crie um OAuth Client ID (Desktop App) e baixe o arquivo como `credentials.json` na raiz do projeto. Depois rode:

```bash
python scripts/auth_gmail.py
```

Autorize sua conta no navegador e guarde o `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` e `GMAIL_REFRESH_TOKEN` impressos no terminal.

### 3. Secrets no GitHub Actions

Em **Settings > Secrets and variables > Actions**, adicione:

- `GEMINI_API_KEY_1` e `GEMINI_API_KEY_2`
- `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`
- `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`

Para testar na hora sem esperar o cron, basta ir em **Actions > Daily Newsletter Podcast > Run workflow**.
