from typing import Any, Dict, List

# This can be moved to app/core/config.py later
# CRITICAL_FIELDS_FOR_CLARIFICATION: Dict[str, Dict[str, str]] = {
#     "polizza": {"label": "Numero Polizza", "question": "Qual è il numero di polizza?"},
#     "data_danno": {"label": "Data Danno", "question": "Qual è la data esatta del danno (GG/MM/AAAA)?"},
#     # Add other fields deemed critical for clarification here
#     # For example:
#     # "client": {"label": "Cliente", "question": "Qual è la ragione sociale del cliente?"},
#     # "assicurato": {"label": "Assicurato", "question": "Qual è la ragione sociale dell'assicurato?"},
#     # "luogo": {"label": "Luogo Sinistro", "question": "Dove è avvenuto esattamente il sinistro?"},
#     # "cause": {"label": "Causa Sinistro", "question": "Qual è la causa presunta del sinistro?"},
# }


class ClarificationService:
    def identify_missing_fields(
        self,
        llm_response: Dict[str, Any],
        critical_fields_config: Dict[str, Dict[str, str]],
    ) -> List[Dict[str, str]]:
        """
        Identifies fields from the llm_response that are None and are present in critical_fields_config.

        Args:
            llm_response: The parsed JSON output from the LLM.
            critical_fields_config: Configuration mapping field keys to labels and questions.

        Returns:
            A list of dictionaries, each containing the key, label, and question for a missing field.
        """
        missing_fields: List[Dict[str, str]] = []
        for key, config_item in critical_fields_config.items():
            if llm_response.get(key) is None:
                missing_fields.append(
                    {
                        "key": key,
                        "label": config_item["label"],
                        "question": config_item["question"],
                    }
                )
        return missing_fields
