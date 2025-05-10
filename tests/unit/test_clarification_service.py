from typing import Any, Dict

import pytest

from app.services.clarification_service import ClarificationService


@pytest.fixture
def clarification_service():
    """Provides a ClarificationService instance for tests."""
    return ClarificationService()


@pytest.fixture
def sample_critical_fields_config():
    """Provides a sample critical_fields_config for tests."""
    return {
        "polizza": {
            "label": "Numero Polizza",
            "question": "Qual è il numero di polizza?",
        },
        "data_danno": {
            "label": "Data Danno",
            "question": "Qual è la data esatta del danno (GG/MM/AAAA)?",
        },
        "responsabile": {"label": "Responsabile", "question": "Chi è il responsabile?"},
    }


def test_identify_missing_fields_llm_has_missing_critical_fields(
    clarification_service: ClarificationService, sample_critical_fields_config: dict
):
    """Test when LLM response is missing fields that are in critical_fields_config."""
    llm_response = {
        "polizza": "12345",
        # "data_danno" is missing
        "responsabile": None,  # Explicitly None
        "other_field": "some_value",
    }
    expected_missing = [
        {
            "key": "data_danno",
            "label": "Data Danno",
            "question": "Qual è la data esatta del danno (GG/MM/AAAA)?",
        },
        {
            "key": "responsabile",
            "label": "Responsabile",
            "question": "Chi è il responsabile?",
        },
    ]
    # Sort for comparison as order doesn't matter for the logic but does for assert list == list
    result = sorted(
        clarification_service.identify_missing_fields(
            llm_response, sample_critical_fields_config
        ),
        key=lambda x: x["key"],
    )
    expected_sorted = sorted(expected_missing, key=lambda x: x["key"])
    assert result == expected_sorted


def test_identify_missing_fields_llm_missing_non_critical_fields(
    clarification_service: ClarificationService, sample_critical_fields_config: dict
):
    """Test when LLM response is missing fields NOT in critical_fields_config."""
    llm_response = {
        "polizza": "12345",
        "data_danno": "01/01/2024",
        "responsabile": "John Doe",
        "non_critical_missing": None,
    }
    result = clarification_service.identify_missing_fields(
        llm_response, sample_critical_fields_config
    )
    assert result == []


def test_identify_missing_fields_no_missing_critical_fields(
    clarification_service: ClarificationService, sample_critical_fields_config: dict
):
    """Test when LLM response has no missing critical fields."""
    llm_response = {
        "polizza": "12345",
        "data_danno": "01/01/2024",
        "responsabile": "John Doe",
        "other_field": "some_value",
    }
    result = clarification_service.identify_missing_fields(
        llm_response, sample_critical_fields_config
    )
    assert result == []


def test_identify_missing_fields_empty_llm_response(
    clarification_service: ClarificationService, sample_critical_fields_config: dict
):
    """Test when LLM response is an empty dictionary."""
    llm_response: Dict[str, Any] = {}
    # Expect all critical fields to be listed as missing
    expected_missing = [
        {
            "key": "polizza",
            "label": "Numero Polizza",
            "question": "Qual è il numero di polizza?",
        },
        {
            "key": "data_danno",
            "label": "Data Danno",
            "question": "Qual è la data esatta del danno (GG/MM/AAAA)?",
        },
        {
            "key": "responsabile",
            "label": "Responsabile",
            "question": "Chi è il responsabile?",
        },
    ]
    result = sorted(
        clarification_service.identify_missing_fields(
            llm_response, sample_critical_fields_config
        ),
        key=lambda x: x["key"],
    )
    expected_sorted = sorted(expected_missing, key=lambda x: x["key"])
    assert result == expected_sorted

    # Test with llm_response being None (though type hint is Dict[str, Any], good to be defensive if possible,
    # but current implementation would raise AttributeError if llm_response.get is called on None)
    # This test will currently fail as written for identify_missing_fields if None is passed
    # For now, we rely on the caller to ensure llm_response is a dict.
    # If identify_missing_fields was to handle None, it would need an initial check.


def test_identify_missing_fields_empty_critical_config(
    clarification_service: ClarificationService,
):
    """Test when critical_fields_config is empty."""
    llm_response: Dict[str, Any] = {"polizza": None, "data_danno": "01/01/2024"}
    critical_fields_config: dict = {}
    result = clarification_service.identify_missing_fields(
        llm_response, critical_fields_config
    )
    assert result == []


def test_identify_missing_fields_field_present_but_empty_string_in_llm_response(
    clarification_service: ClarificationService, sample_critical_fields_config: dict
):
    """Test when a critical field is present in LLM response but its value is an empty string."""
    llm_response = {
        "polizza": "",  # Empty string, not None
        "data_danno": "01/01/2024",
        "responsabile": "John Doe",
    }
    # The current logic `llm_response.get(key) is None` will not identify "" as missing. This is correct.
    result = clarification_service.identify_missing_fields(
        llm_response, sample_critical_fields_config
    )
    assert result == []
