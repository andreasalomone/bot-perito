from typing import Any


class ClarificationService:
    def identify_missing_fields(
        self,
        llm_response: dict[str, Any],
        critical_fields_config: dict[str, dict[str, str]],
    ) -> list[dict[str, str]]:
        """Identifies fields from the llm_response that are None and are present in critical_fields_config.

        Args:
            llm_response: The parsed JSON output from the LLM.
            critical_fields_config: Configuration mapping field keys to labels and questions.

        Returns:
            A list of dictionaries, each containing the key, label, and question for a missing field.
        """
        return [
            {
                "key": key,
                "label": config_item["label"],
                "question": config_item["question"],
            }
            for key, config_item in critical_fields_config.items()
            if llm_response.get(key) is None
        ]
