import asyncio
import json
import logging
import re
from uuid import uuid4

from openai import OpenAI, OpenAIError  # ← sync client
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.services.style_loader import load_style_samples

# Configure module logger
logger = logging.getLogger(__name__)

BULLET = "•"  # match bullet used in samples


# Custom exceptions for better error handling
class LLMError(Exception):
    """Raised when LLM call fails"""


class JSONParsingError(Exception):
    """Raised when JSON parsing fails"""


# ---------------------------------------------------------------
# OpenRouter client (sync) with required headers
# ---------------------------------------------------------------
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key,
    default_headers={
        "HTTP-Referer": "http://localhost",
        "X-Title": "bot-perito",
        # Authorization is auto‑added from api_key
    },
)


# ---------------------------------------------------------------
# LLM call wrapped in a thread so FastAPI remains async
# ---------------------------------------------------------------
@retry(
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
    retry=lambda exc: isinstance(exc, OpenAIError)
    and getattr(exc, "status", None) in {429, 500, 502, 503, 504},
)
async def call_llm(prompt: str) -> str:
    request_id = str(uuid4())
    logger.info(
        "[%s] Making LLM API call with model: %s", request_id, settings.model_id
    )

    def _sync_call() -> str:
        try:
            rsp = client.chat.completions.create(
                model=settings.model_id,
                messages=[
                    {
                        "role": "system",
                        "content": "Rispondi SOLO con un JSON valido e nient'altro.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            # Guard against None in content
            content = (rsp.choices[0].message.content or "").strip()
            logger.debug(
                "[%s] LLM response received, length: %d chars", request_id, len(content)
            )
            return content
        except OpenAIError as e:
            logger.error("[%s] OpenAI API error: %s", request_id, str(e), exc_info=True)
            raise LLMError(f"OpenAI API error: {str(e)}") from e
        except Exception as e:
            logger.exception("[%s] Unexpected error in LLM call", request_id)
            raise LLMError(f"Unexpected error in LLM call: {str(e)}") from e

    try:
        return await asyncio.to_thread(_sync_call)
    except Exception:
        logger.exception("[%s] Failed to execute LLM call in thread", request_id)
        raise


# ---------------------------------------------------------------
# JSON extractor helper
# ---------------------------------------------------------------
def extract_json(text: str) -> dict:
    """
    Tenta di deserializzare `text` come JSON puro.
    Se fallisce, estrae il primo blocco { … } con regex e riprova.
    """
    request_id = str(uuid4())
    logger.debug(
        "[%s] Attempting to parse JSON response, length: %d", request_id, len(text)
    )

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning(
            "[%s] Initial JSON parse failed, attempting regex extraction", request_id
        )
        try:
            match = re.search(r"\{.*\}", text, re.S)
            if not match:
                logger.error("[%s] No JSON-like structure found in text", request_id)
                raise JSONParsingError("No JSON structure found in response")
            extracted = match.group(0)
            logger.info("[%s] Found JSON-like structure, attempting parse", request_id)
            return json.loads(extracted)
        except json.JSONDecodeError as e:
            logger.error(
                "[%s] Failed to parse extracted JSON: %s",
                request_id,
                str(e),
                exc_info=True,
            )
            raise JSONParsingError(f"Failed to parse JSON: {str(e)}") from e
        except Exception as e:
            logger.exception("[%s] Unexpected error parsing JSON", request_id)
            raise JSONParsingError(f"Unexpected error parsing JSON: {str(e)}") from e


# ---------------------------------------------------------------
# Prompt builder (unchanged)
# ---------------------------------------------------------------
def build_prompt(
    template_excerpt: str,
    corpus: str,
    images: list[str],
    notes: str,
    similar_cases: list[dict] | None = None,
) -> str:
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
        img_block = "\n\nFOTO_DANNI_BASE64:\n" + "\n".join(images)

    # --- blocco casi simili ------------------------------------------------
    cases_block = ""
    if similar_cases:
        joined = "\n\n---\n\n".join(
            f"[{c['title']}]  \n{c['content_snippet']}" for c in similar_cases
        )
        cases_block = (
            "\n\nCASI_SIMILI (usa solo come riferimento stilistico e per informazioni quali indirizzi, cause):\n<<<\n"
            f"{joined}\n>>>"
        )

    # --- prompt finale ------------------------------------------------------

    base_prompt = f"""

Sei un perito assicurativo italiano della Salomone e Associati, abituato a scrivere perizie tecniche più lunghe e dettagliate possibili, ai clienti piace così.
Analizza i documenti e restituisci ESCLUSIVAMENTE un JSON valido, senza testo extra, con le chiavi qui sotto.

## Definizione chiavi
| chiave JSON       | tag DOCX                | contenuto richiesto                                   |
|-------------------|-------------------------|-------------------------------------------------------|
| client            | CLIENT                  | Ragione sociale cliente                               |
| client_address1   | CLIENTADDRESS1          | Via/Piazza + numero indirizzo cliente                 |
| client_address2   | CLIENTADDRESS2          | CAP + città cliente                                   |
| date              | DATE                    | Data di oggi (GG/MM/AAAA)                             |
| vs_rif            | VSRIF                   | Riferimento del sinistro (del cliente)                                   |
| rif_broker        | RIFBROKER               | Riferimento del sinistro (del broker)                                     |
| polizza           | POLIZZA                 | Numero polizza assicurativa                                       |
| ns_rif            | NSRIF                   | Riferimento del sinistro (interno, perito della Salomone e Associati)                           |
| assicurato        | ASSICURATO              | Ragione sociale dell'assicurato                                  |
| indirizzo_ass1    | INDIRIZZOASSICURATO1    | Via/Piazza dell'indirizzo dell'assicurato                                  |
| indirizzo_ass2    | INDIRIZZOASSICURATO2    | CAP + città dell'indirizzo dell'assicurato                                 |
| luogo             | LUOGO                   | Luogo in cui è accaduto ilsinistro                                         |
| data_danno        | DATADANNO               | Data del sinistro                                          |
| cause             | CAUSE                   | Causa presunta del sinistro (oggetto di perizia)                                       |
| data_incarico     | DATAINCARICO            | Data in cui è stato incaricato il perito dal cliente                                |
| merce             | MERCE                   | Tipo merce sinistrata                                             |
| peso_merce        | PESOMERCE               | Peso complessivo in kg della merce sinistrata                                |
| valore_merce      | VALOREMERCE             | Valore in € della merce sinistrata                    |
| data_intervento   | DATAINTERVENTO          | Data del sopralluogo sul luogo del sinistro da parte del perito della Salomone e Associati                                       |
| dinamica_eventi   | DINAMICA_EVENTI         | Sez. 2a – descrivi **solo** la dinamica del sinistro, chi, come, dove, quando, perché è avvenuto — **senza titolo** –                         |
| accertamenti      | ACCERTAMENTI            | Sez. 2b – descrivi gli accertamenti peritali eseguiti, dove, quando, come, con chi, con chi è stato incaricato, con chi è stato coinvolto, le scoperte peritali degli accertamenti — **senza titolo** –                         |
| quantificazione   | QUANTIFICAZIONE         | Sez. 3 – quantificazione del danno totale, le cifre come lista puntata o tabella testo, in stile esempio) — **senza titolo**                        |
| commento          | COMMENTO                | Sez. 4 – sintesi tecnica finale, come da esempio — **senza titolo**                        |
| allegati          | ALLEGATI                | Elenco allegati in bullet list uno sopra l'altro, ovvero i tipi di documenti che ha caricato l'utente per la nuova perizia (“Nolo; Fattura; Bolla; Foto 1; Foto 2 …”)                   |

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
  "assicurato": "",
  "indirizzo_ass1": "",
  "indirizzo_ass2": "",
  "luogo": "",
  "data_danno": "",
  "cause": "",
  "data_incarico": "",
  "merce": "",
  "peso_merce": "",
  "valore_merce": "",
  "data_intervento": "",
  "dinamica_eventi": "",
  "accertamenti": "",
  "quantificazione": "",
  "commento": "",
  "allegati": ""
}}

❗ Regole:
1. NIENTE markdown fuori dai campi specificati, html o commenti: solo JSON puro.
2. Scarta testo ridondante; mantieni nel campo "body" i paragrafi con
   numerazione, elenchi puntati, grassetti in **asterischi** se servono.
3. Non aggiungere campi extra. Non cambiare i nomi chiave.
4. Analizza con attenzione e con occhio peritale
   le immagini nel blocco FOTO_DANNI_BASE64 e integra la causa
   probabile dei danni nella sezione «2 – QUANTIFICAZIONE DEI DANNI».
5. Per le chiavi "dinamica_eventi", "accertamenti", "quantificazione", "commento"
   scrivi solo il contenuto (i titoli sono già nel template).
   Ognuna di queste 4 sezioni deve contenere almeno 200 parole.
6. Separa tutti i paragrafi con UNA riga bianca (\n\n).

RISPOSTA OBBLIGATORIA:
Restituisci SOLO il JSON, senza testo extra prima o dopo. No talk, just go.

### Sezioni testuali da costruire
**dinamica_eventi**
Spiega **solo** l'evento del sinistro rispondendo alle domande: chi, come, dove, quando, perché è avvenuto.

**accertamenti**
Descrivi **solo** gli accertamenti peritali: sopralluogo, rilievi, danni osservati.

**quantificazione**
Riporta le cifre come lista puntata o tabella testo, in stile esempio.
Intestazione già presente nel template e che non devi ripetere: `**3 – QUANTIFICAZIONE DEL DANNO**`.

**commento**
Sintesi tecnica finale. Intestazione già presente nel template e che non devi ripetere: `**4 – COMMENTO FINALE**`.

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

    # --- prompt finale con blocco RAG ------------------------------------
    return f"{base_prompt}{cases_block}"
