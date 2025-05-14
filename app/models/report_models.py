from pydantic import BaseModel


class ReportContext(BaseModel):
    """Represents the core data fields extracted or generated for a report."""

    client: str | None = None
    client_address1: str | None = None
    client_address2: str | None = None
    date: str | None = None
    vs_rif: str | None = None
    rif_broker: str | None = None
    polizza: str | None = None
    ns_rif: str | None = None
    assicurato: str | None = None
    indirizzo_ass1: str | None = None
    indirizzo_ass2: str | None = None
    luogo: str | None = None
    data_danno: str | None = None
    cause: str | None = None
    data_incarico: str | None = None
    merce: str | None = None
    peso_merce: str | None = None
    valore_merce: str | None = None
    data_intervento: str | None = None
    dinamica_eventi: str | None = None
    accertamenti: str | None = None
    quantificazione: str | None = None
    commento: str | None = None
    allegati: list[str] | None = None  # List of attachment filenames, e.g., ["file1.pdf", "image.png"]


class OutlineItem(BaseModel):
    """Represents a single item in the generated report outline."""

    section: str
    title: str
    bullets: list[str]


class RequestArtifacts(BaseModel):
    """Holds intermediate artifacts and context passed between report generation steps."""

    original_corpus: str
    notes: str
    template_excerpt: str
    reference_style_text: str
    initial_llm_base_fields: ReportContext  # This is the base_ctx from the first LLM call


class ClarificationPayload(BaseModel):
    """Defines the structure for receiving user clarifications."""

    clarifications: dict[str, str | None]
    request_artifacts: RequestArtifacts
