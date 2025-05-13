from typing import Any, Dict, List


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
        return [
            {
                "key": key,
                "label": config_item["label"],
                "question": config_item["question"],
            }
            for key, config_item in critical_fields_config.items()
            if llm_response.get(key) is None
        ]
