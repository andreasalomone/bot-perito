from typing import Dict, List, Optional

from pydantic import BaseModel


class ReportContext(BaseModel):
    """Represents the core data fields extracted or generated for a report."""

    client: Optional[str] = None
    client_address1: Optional[str] = None
    client_address2: Optional[str] = None
    date: Optional[str] = None
    vs_rif: Optional[str] = None
    rif_broker: Optional[str] = None
    polizza: Optional[str] = None
    ns_rif: Optional[str] = None
    assicurato: Optional[str] = None
    indirizzo_ass1: Optional[str] = None
    indirizzo_ass2: Optional[str] = None
    luogo: Optional[str] = None
    data_danno: Optional[str] = None
    cause: Optional[str] = None
    data_incarico: Optional[str] = None
    merce: Optional[str] = None
    peso_merce: Optional[str] = None
    valore_merce: Optional[str] = None
    data_intervento: Optional[str] = None
    dinamica_eventi: Optional[str] = None
    accertamenti: Optional[str] = None
    quantificazione: Optional[str] = None
    commento: Optional[str] = None
    allegati: Optional[List[str]] = None


class RequestArtifacts(BaseModel):
    """Holds intermediate artifacts and context passed between report generation steps."""

    original_corpus: str
    image_tokens: List[str]  # From the plan, this is what `imgs` corresponds to
    notes: str
    initial_llm_base_fields: (
        ReportContext  # This is the base_ctx from the first LLM call
    )


class ClarificationPayload(BaseModel):
    """Defines the structure for receiving user clarifications."""

    clarifications: Dict[str, Optional[str]]  # Removed redundant comment
    request_artifacts: RequestArtifacts
