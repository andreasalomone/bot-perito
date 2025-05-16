import asyncio
import io
import logging
from uuid import uuid4

from docxtpl import DocxTemplate
from jinja2 import UndefinedError

from app.models.report_models import ReportContext

# Configure module logger
logger = logging.getLogger(__name__)


# Maps the DOCX template tags (keys) to the expected keys in the context dictionary (values).
TEMPLATE_TAG_TO_CONTEXT_KEY_MAPPING: dict[str, str] = {
    "CLIENT": "client",
    "CLIENTADDRESS1": "client_address1",
    "CLIENTADDRESS2": "client_address2",
    "DATE": "date",
    "VSRIF": "vs_rif",
    "RIFBROKER": "rif_broker",
    "POLIZZA": "polizza",
    "NSRIF": "ns_rif",
    "ASSICURATO": "assicurato",
    "INDIRIZZOASSICURATO1": "indirizzo_ass1",
    "INDIRIZZOASSICURATO2": "indirizzo_ass2",
    "LUOGO": "luogo",
    "DATADANNO": "data_danno",
    "CAUSE": "cause",
    "DATAINCARICO": "data_incarico",
    "MERCE": "merce",
    "PESOMERCE": "peso_merce",
    "VALOREMERCE": "valore_merce",
    "DATAINTERVENTO": "data_intervento",
    "ALLEGATI": "allegati",
    "DINAMICA_EVENTI": "dinamica_eventi",
    "ACCERTAMENTI": "accertamenti",
    "QUANTIFICAZIONE": "quantificazione",
    "COMMENTO": "commento",
}


class DocBuilderError(Exception):
    """Raised when DOCX generation fails"""


async def inject(template_path: str, context: ReportContext) -> bytes:
    """Render *template_path* with *context* using docxtpl (single pass)."""

    def _sync(tpl_path: str, ctx: ReportContext) -> bytes:
        rid = str(uuid4())
        logger.info("[%s] Generating report from %s", rid, tpl_path)
        try:
            tpl = DocxTemplate(tpl_path)

            # Build mapping_data straight from pydantic/dict
            base_data = ctx.dict() if hasattr(ctx, "dict") else ctx.__dict__

            # Create mapping with keys as expected in the template
            mapping_data = {}
            for tpl_tag, ctx_key in TEMPLATE_TAG_TO_CONTEXT_KEY_MAPPING.items():
                mapping_data[tpl_tag] = base_data.get(ctx_key, "")

            try:
                tpl.render(mapping_data)
            except UndefinedError as e:
                # This happens when the Word template contains a tag that is
                # not present in TEMPLATE_TAG_TO_CONTEXT_KEY_MAPPING.
                logger.error("[%s] Undefined Jinja tag in template: %s", rid, e)
                raise DocBuilderError(f"Undefined template tag: {e}") from e

            bio = io.BytesIO()
            tpl.save(bio)
            size = bio.tell()
            bio.seek(0)
            logger.info("[%s] Report ready (%d bytes)", rid, size)
            return bio.read()
        except Exception as err:
            logger.exception("[%s] Report generation failed (other error)", rid)
            raise DocBuilderError("unexpected rendering error") from err

    # run sync work in a thread
    return await asyncio.to_thread(_sync, template_path, context)
