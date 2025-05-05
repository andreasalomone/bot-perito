import asyncio
import json, re
from openai import OpenAI, OpenAIError            # ← sync client
from tenacity import retry, wait_exponential, stop_after_attempt

from app.core.config import settings
from app.services.style_loader import load_style_samples

BULLET = "•"  # match bullet used in samples

# ---------------------------------------------------------------
# OpenRouter client (sync) with required headers
# ---------------------------------------------------------------
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key,
    default_headers={
        "HTTP-Referer": "http://localhost",
        "X-Title":      "bot-perito",
        # Authorization is auto‑added from api_key
    },
)

# ---------------------------------------------------------------
# LLM call wrapped in a thread so FastAPI remains async
# ---------------------------------------------------------------
@retry(wait=wait_exponential(multiplier=1, min=2, max=10),
       stop=stop_after_attempt(3),
       retry=lambda exc: isinstance(exc, OpenAIError)
                         and exc.status in {429, 500, 502, 503, 504})
async def call_llm(prompt: str) -> str:
    print("DEBUG key prefix:", settings.openrouter_api_key[:12])

    def _sync_call() -> str:
        rsp = client.chat.completions.create(
            model=settings.model_id,
            messages=[
                {"role": "system",
                 "content": "Rispondi SOLO con un JSON valido e nient'altro."},
                {"role": "user", "content": prompt},
            ],
        )
        return rsp.choices[0].message.content.strip()

    return await asyncio.to_thread(_sync_call)

# ---------------------------------------------------------------
# JSON extractor helper
# ---------------------------------------------------------------
def extract_json(text: str) -> dict:
    """
    Tenta di deserializzare `text` come JSON puro.
    Se fallisce, estrae il primo blocco { … } con regex e riprova.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group(0))

# ---------------------------------------------------------------
# Prompt builder (unchanged)
# ---------------------------------------------------------------
def build_prompt(template_excerpt: str,
                 corpus: str,
                 images: list[str],
                 notes: str) -> str:
    """
    Prompt per LLama4: restituisce SOLO un JSON con i campi del template.
    Il testo finale verrà inserito da docxtpl, quindi qui non serve
    formattazione.
    """

    # --- blocco stile aggiuntivo (facoltativo) -----------------------------
    extra_styles = load_style_samples()
    if extra_styles:
        extra_styles = (
            "\n\nESEMPIO DI FORMATTAZIONE (SOLO PER TONO E STILE; IGNORA CONTENUTO):\n<<<\n"
            f"{extra_styles}\n>>>"
        )

    # --- eventuali immagini -------------------------------------------------
    img_block = ""
    if images and settings.allow_vision:
        img_block = "\n\nIMMAGINI_BASE64 (usa se utili):\n" + "\n".join(images)

    # --- prompt finale ------------------------------------------------------
    return f"""
Sei un perito assicurativo italiano della Salomone e Associati. Analizza i documenti e restituisci
ESCLUSIVAMENTE un JSON valido, senza testo extra, con le chiavi qui sotto.

## Definizione chiavi
- "client"            : Ragione sociale del cliente assicurato (tag {{CLIENT}})
- "client_address1"   : Indirizzo (prima riga)           ({{CLIENTADDRESS1}})
- "client_address2"   : CAP + Città (seconda riga)       ({{CLIENTADDRESS2}})
- "date"              : Data report in formato GG/MM/AAAA ({{DATE}})
- "vs_rif"            : *Vostro Riferimento* – codice sinistro fornito dal cliente ({{VSRIF}})
- "rif_broker"        : Riferimento del broker           ({{RIFBROKER}})
- "polizza"           : Numero di polizza assicurativa   ({{POLIZZA}})
- "ns_rif"            : *Nostro Riferimento* – ID interno del perito ({{NSRIF}})
- "subject"           : Oggetto sintetico della perizia  ({{SUBJECT}})
- "body"              : Testo della perizia a partire da "1 – DINAMICA DEGLI EVENTI"
                       **senza** intestazione Spett.le ecc.

Se un valore non è rintracciabile, restituisci stringa vuota "".

## Formato di output (rispettare ordine e maiusc/minusc delle chiavi)
{{
  "client": "",
  "client_address1": "",
  "client_address2": "",
  "date": "",
  "vs_rif": "",
  "rif_broker": "",
  "polizza": "",
  "ns_rif": "",
  "subject": "",
  "body": ""
}}

❗ Regole:
1. NIENTE markdown, html o commenti: solo JSON puro.
2. Scarta testo ridondante; mantieni nel campo "body" i paragrafi con
   numerazione, elenchi puntati, grassetti in **asterischi** se servono.
3. Non aggiungere campi extra. Non cambiare i nomi chiave.

RISPOSTA OBBLIGATORIA:
Restituisci SOLO il JSON, senza testo extra prima o dopo. No talk, just go.

## Template di riferimento (tono & terminologia):
<<<
{template_excerpt}
>>>{extra_styles}

## Documentazione utente:
<<<
{corpus}
>>>

## Note extra:
{notes}{img_block}
"""