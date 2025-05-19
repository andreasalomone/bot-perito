import json
import logging
import pathlib
import re
from typing import Any
from uuid import uuid4

import httpx
import jinja2
from openai import AsyncOpenAI
from openai import OpenAIError
from tenacity import RetryCallState
from tenacity import retry
from tenacity import stop_after_attempt
from tenacity import wait_exponential

from app.core.config import settings

# Configure module logger
logger = logging.getLogger(__name__)


# Custom exceptions for better error handling
class LLMError(Exception):
    """Raised when LLM call fails"""


class JSONParsingError(Exception):
    """Raised when JSON parsing fails"""


# --- Reusable Jinja2 Environment ---
# Initialize Jinja2 environment for prompt templates
PROMPT_DIR = pathlib.Path(__file__).parent.parent / "services/prompt_templates"  # Adjusted path
env: jinja2.Environment | None = None
try:
    loader = jinja2.FileSystemLoader(PROMPT_DIR)
    env = jinja2.Environment(loader=loader)
    logger.info("Jinja2 environment initialized successfully for path: %s", PROMPT_DIR)
except Exception:
    logger.exception("Failed to initialize Jinja2 environment at %s", PROMPT_DIR)
    # Depending on application needs, might re-raise or handle differently
    env = None  # Ensure env is defined, even if initialization fails


# ---------------------------------------------------------------
# OpenRouter client (sync) with required headers
# ---------------------------------------------------------------
# Define timeouts based on settings
timeout_config = httpx.Timeout(
    settings.LLM_CONNECT_TIMEOUT,
    read=settings.LLM_READ_TIMEOUT,
    # Pool timeout can be added if supported and needed: pool=settings.LLM_POOL_TIMEOUT
)

client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key,
    default_headers={
        "HTTP-Referer": "https://aiperito.vercel.app",
        "X-Title": "bot-perito",
        # Authorization is auto‑added from api_key
    },
    timeout=timeout_config,  # Pass the timeout config
    max_retries=2,  # Add max retries directly to the client config
)


# ---------------------------------------------------------------
# Helper predicate for tenacity retry
# ---------------------------------------------------------------


def _should_retry_llm_call(retry_state: RetryCallState) -> bool:
    """Determines if a retry should occur based on the exception in RetryCallState."""
    if not retry_state.outcome:  # Should not happen if an exception occurred
        return False

    exc = retry_state.outcome.exception()
    if not exc:
        return False  # No exception, no need to retry

    # Unwrap our custom LLMError to get to the original cause (e.g., OpenAIError)
    actual_exception = exc.__cause__ if isinstance(exc, LLMError) and exc.__cause__ else exc

    # Check for status or status_code on the actual underlying exception
    status = getattr(actual_exception, "status", None) or getattr(actual_exception, "status_code", None)
    if status in {429, 500, 502, 503, 504}:
        logger.debug("Retryable API error status %s detected. Retrying...", status)
        return True
    return False


# ---------------------------------------------------------------
# LLM call wrapped in a thread so FastAPI remains async
# ---------------------------------------------------------------
@retry(
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
    retry=_should_retry_llm_call,
)  # type: ignore
async def call_llm(prompt: str) -> str:
    request_id = str(uuid4())
    logger.info("[%s] Making LLM API call with model: %s", request_id, settings.model_id)

    try:
        rsp = await client.chat.completions.create(
            model=settings.model_id,
            messages=[
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=3000,
            temperature=0.2,  # Lower temperature for more reliable responses
            timeout=timeout_config,  # Use our timeout config
        )

        # Log the raw response structure for debugging
        logger.debug("[%s] Raw LLM response structure: %s", request_id, str(rsp))

        # Add null checks for response structure
        if not rsp or not hasattr(rsp, "choices") or not rsp.choices:
            logger.error("[%s] Invalid response structure from LLM API: %s", request_id, str(rsp))
            raise LLMError(f"Invalid response structure from LLM API: {str(rsp)}")

        # Check if message and content exist in the first choice
        first_choice = rsp.choices[0]
        if not hasattr(first_choice, "message") or first_choice.message is None:
            logger.error("[%s] Missing 'message' in LLM API response: %s", request_id, str(first_choice))
            raise LLMError(f"Missing 'message' in LLM API response: {str(first_choice)}")

        # Handle potential structured content (e.g., OpenRouter's JSON response mode)
        if hasattr(first_choice.message, "content") and first_choice.message.content is not None:
            content = first_choice.message.content.strip()
        elif hasattr(first_choice.message, "function_call") and first_choice.message.function_call is not None:
            # Handle possible function call response (for JSON mode)
            fcall = first_choice.message.function_call
            if hasattr(fcall, "arguments") and fcall.arguments:
                content = fcall.arguments
            else:
                logger.error("[%s] Function call response missing arguments: %s", request_id, str(fcall))
                raise LLMError(f"Function call response missing arguments: {str(fcall)}")
        else:
            logger.error("[%s] No content or function_call in message: %s", request_id, str(first_choice.message))
            raise LLMError(f"No content or function_call in message: {str(first_choice.message)}")

        logger.debug("[%s] LLM response received, length: %d chars", request_id, len(content))
        return content
    except OpenAIError as e:
        # Let the retry decorator decide whether to retry. We wrap in LLMError only
        # *after* all retry attempts are exhausted (tenacity will surface the exception here).
        logger.error("[%s] OpenAI API error: %s", request_id, str(e), exc_info=True)
        raise LLMError(f"OpenAI API error: {str(e)}") from e
    except Exception as e:
        logger.exception("[%s] Unexpected error in LLM call", request_id)
        raise LLMError(f"Unexpected error in LLM call: {str(e)}") from e


# ---------------------------------------------------------------
# JSON extractor helper
# ---------------------------------------------------------------
def extract_json(text: str) -> dict:
    """Attempts to robustly extract and parse JSON from LLM responses, handling markdown fences and extraneous text."""
    request_id = str(uuid4())
    logger.debug("[%s] Attempting to parse JSON response, length: %d", request_id, len(text))

    # If text is already a valid dictionary, return it directly
    if isinstance(text, dict):
        logger.info("[%s] Input is already a dictionary, no parsing needed.", request_id)
        return text

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("[%s] Initial JSON parse failed, attempting extraction strategies...", request_id)

    # Strategy 1: Markdown Code Fence Extraction
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.DOTALL)
    if match:
        extracted_block = match.group(1)
        try:
            result = json.loads(extracted_block)
            logger.info("[%s] Successfully parsed JSON from markdown code fence.", request_id)
            return result
        except json.JSONDecodeError:
            logger.warning("[%s] Failed to parse JSON from fenced block, trying next strategy...", request_id)

    # Strategy 2: Use JSONDecoder().raw_decode for first object/array
    decoder = json.JSONDecoder()
    obj_start = text.find("{")
    arr_start = text.find("[")
    if obj_start == -1 and arr_start == -1:
        logger.error("[%s] No JSON object or array marker found in response", request_id)
        raise JSONParsingError("No JSON object or array marker found in response")
    # Find the minimum non-negative start position
    start_pos = min([pos for pos in [obj_start, arr_start] if pos != -1])
    try:
        obj, _ = decoder.raw_decode(text, start_pos)
        logger.info("[%s] Successfully parsed JSON using raw_decode.", request_id)
        return obj
    except json.JSONDecodeError as e:
        logger.error(
            "[%s] Failed to parse JSON using raw_decode: %s",
            request_id,
            str(e),
            exc_info=True,
        )
    logger.error("[%s] All strategies to parse JSON from LLM response failed.", request_id)
    raise JSONParsingError("All strategies to parse JSON from LLM response failed.")


# ---------------------------------------------------------------
# Helper for executing LLM step with template rendering
# ---------------------------------------------------------------
async def execute_llm_step_with_template(
    request_id: str,
    step_name: str,
    template_name: str,
    context: dict[str, Any],
    expected_type: type = dict,  # Expect a dict by default
) -> Any:
    """Executes a single LLM step: load template, render, call LLM, parse JSON.
    Handles common LLM and JSON parsing errors, raising appropriate exceptions.
    """
    logger.debug("[%s] Executing LLM step: %s", request_id, step_name)
    if env is None:
        logger.error("[%s] Jinja2 environment not initialized for step %s", request_id, step_name)
        raise LLMError("Internal configuration error: Template environment not available.") from None

    try:
        template = env.get_template(template_name)
        prompt = template.render(**context)
        raw_response = await call_llm(prompt)
        data = extract_json(raw_response)

        # Optional: Validate the root type of the parsed JSON
        if not isinstance(data, expected_type):
            logger.error(
                "[%s] Invalid data type returned for step '%s'. Expected %s, got %s. Data: %s",
                request_id,
                step_name,
                expected_type.__name__,
                type(data).__name__,
                str(data)[:200],  # Log snippet of data
            )
            raise LLMError(f"Invalid data format received during '{step_name}' step.")

        logger.debug("[%s] Successfully executed LLM step: %s", request_id, step_name)
        return data

    except (LLMError, JSONParsingError) as e:
        # Errors from call_llm or extract_json or the type check above
        logger.error(
            "[%s] Failed LLM step '%s': %s",
            request_id,
            step_name,
            str(e),
            # exc_info=True is included in call_llm/extract_json if needed
        )
        # Re-raise directly as they are already specific
        raise e
    except jinja2.TemplateNotFound:
        logger.error(
            "[%s] Template not found: %s for step %s",
            request_id,
            template_name,
            step_name,
        )
        raise LLMError(f"Internal configuration error: Template '{template_name}' not found.") from None
    except Exception as e:
        logger.exception("[%s] Unexpected error in LLM step '%s'", request_id, step_name)
        raise LLMError(f"Unexpected error during '{step_name}' step.") from e


# ---------------------------------------------------------------
# Prompt builder (unchanged) - NOTE: This might also be refactored later
# ---------------------------------------------------------------

# Initialize Jinja2 environment
# PROMPT_DIR = pathlib.Path(__file__).parent / "prompt_templates" # Defined above
# loader = jinja2.FileSystemLoader(PROMPT_DIR) # Defined above
# env = jinja2.Environment(loader=loader) # Defined above


def build_prompt(
    template_excerpt: str,
    corpus: str,
    notes: str,
    reference_style_text: str,
) -> str:
    """Prompt per LLama4: restituisce SOLO un JSON con i campi del template.
    Il testo finale verrà inserito da docxtpl, quindi qui non serve
    formattazione.
    """
    if env is None:
        logger.error("Jinja2 environment not initialized for build_prompt")
        # Handle error appropriately - maybe return a default prompt or raise
        raise LLMError("Internal configuration error: Template environment not available.") from None

    # --- blocco stile aggiuntivo (facoltativo) -----------------------------
    extra_styles = ""
    if reference_style_text:
        extra_styles = f"\\n\\nESEMPIO DI FORMATTAZIONE (SOLO PER TONO E STILE; IGNORA CONTENUTO):\\n<<<\\n{reference_style_text}\\n>>>"

    # --- eventuali immagini -------------------------------------------------
    # img_block = ""
    # if images and settings.allow_vision:
    #    img_block = "\\n\\nFOTO_DANNI_BASE64:\\n" + "\\n".join(images)

    # --- carica e renderizza template Jinja2 ----------------------------------
    try:
        template = env.get_template("build_prompt.jinja2")
        prompt_content = template.render(
            template_excerpt=template_excerpt,
            extra_styles=extra_styles,
            corpus=corpus,
            notes=notes,
        )
        return prompt_content
    except jinja2.TemplateNotFound:
        logger.error("Template not found: build_prompt.jinja2")
        raise LLMError("Internal configuration error: Template 'build_prompt.jinja2' not found.") from None
    except Exception as e:
        logger.exception("Unexpected error building prompt")
        raise LLMError("Unexpected error building prompt.") from e
