from pathlib import Path
from unittest.mock import patch

import jinja2
import pytest

from app.core.config import Settings
from app.services.llm import build_prompt

# from app.services.llm import (
#     env as llm_env,  # Assuming llm.py initializes and exports 'env'
# )

# If env is not directly exportable, we might need to re-initialize it here for tests
# from app.services.pipeline import env as pipeline_env # If pipeline has a separate env


# Mock settings if they influence prompt generation significantly
@pytest.fixture
def mock_settings_allow_vision(monkeypatch):
    mock_settings = Settings(
        allow_vision=True, openrouter_api_key="test_key"
    )  # Add other necessary fields
    monkeypatch.setattr("app.services.llm.settings", mock_settings)
    return mock_settings


@pytest.fixture
def mock_settings_disallow_vision(monkeypatch):
    mock_settings = Settings(
        allow_vision=False, openrouter_api_key="test_key"
    )  # Add other necessary fields
    monkeypatch.setattr("app.services.llm.settings", mock_settings)
    return mock_settings


# Re-initialize Jinja environment for pipeline templates if necessary,
# or ensure it's importable and correctly configured.
# For simplicity, assuming pipeline.py uses the same PROMPT_DIR or we can access it.
PIPELINE_PROMPT_DIR = (
    Path(__file__).parents[2] / "app" / "services" / "prompt_templates"
)
pipeline_loader = jinja2.FileSystemLoader(PIPELINE_PROMPT_DIR)
pipeline_test_env = jinja2.Environment(loader=pipeline_loader)


# I. Tests for build_prompt from app/services/llm.py


@patch("app.services.llm.load_style_samples")
def test_build_prompt_all_data_with_vision(
    mock_load_styles, mock_settings_allow_vision
):
    mock_load_styles.return_value = "Test Style Sample"
    prompt = build_prompt(
        template_excerpt="Excerpt data",
        corpus="Corpus data",
        images=["image1_base64", "image2_base64"],
        notes="Notes data",
        similar_cases=[{"title": "Case 1", "content_snippet": "Snippet 1"}],
    )
    assert "Excerpt data" in prompt
    assert "Corpus data" in prompt
    assert "Notes data" in prompt
    assert "Test Style Sample" in prompt
    assert "FOTO_DANNI_BASE64:" in prompt
    assert "image1_base64" in prompt
    assert "image2_base64" in prompt
    assert "CASI_SIMILI" in prompt
    assert "Case 1" in prompt
    assert "Snippet 1" in prompt


@patch("app.services.llm.load_style_samples")
def test_build_prompt_no_optional_data_no_vision(
    mock_load_styles, mock_settings_disallow_vision
):
    mock_load_styles.return_value = ""  # No extra styles
    prompt = build_prompt(
        template_excerpt="Excerpt only",
        corpus="Corpus basic",
        images=[],  # No images
        notes="",  # No notes
        similar_cases=None,  # No similar cases
    )
    assert "Excerpt only" in prompt
    assert "Corpus basic" in prompt
    assert "ESEMPIO DI FORMATTAZIONE" not in prompt  # No style block if style is empty
    assert "FOTO_DANNI_BASE64:" not in prompt
    assert "CASI_SIMILI" not in prompt
    assert (
        "Notes data" not in prompt
    )  # Check if notes section is handled if empty (depends on template)


@patch("app.services.llm.load_style_samples")
def test_build_prompt_images_but_vision_disabled(
    mock_load_styles, mock_settings_disallow_vision
):
    mock_load_styles.return_value = "Style Sample"
    prompt = build_prompt(
        template_excerpt="Excerpt",
        corpus="Corpus",
        images=["image1_base64"],  # Images present
        notes="Notes",
        similar_cases=None,
    )
    assert "FOTO_DANNI_BASE64:" not in prompt  # Vision disabled


@patch("app.services.llm.load_style_samples")
def test_build_prompt_empty_inputs_handled_gracefully(
    mock_load_styles, mock_settings_allow_vision
):
    mock_load_styles.return_value = ""
    prompt = build_prompt(
        template_excerpt="",
        corpus="",
        images=[],
        notes="",
        similar_cases=[],  # Empty list for similar cases
    )
    # Assert that the prompt is still generated and key structures are present
    # This depends heavily on how build_prompt.jinja2 is structured for empty inputs
    assert "## Template di riferimento" in prompt  # A static part of the template
    assert "## Documentazione utente:" in prompt
    assert "## Note extra:" in prompt
    assert "FOTO_DANNI_BASE64:" not in prompt
    assert "CASI_SIMILI" not in prompt


# II. Test Cases for Pipeline Prompts (Jinja Templates)


# A. generate_outline_prompt.jinja2
def test_generate_outline_prompt_all_data():
    template = pipeline_test_env.get_template("generate_outline_prompt.jinja2")
    rendered_prompt = template.render(
        template_excerpt="Outline template excerpt",
        corpus="Outline corpus",
        similar_cases_str="Similar cases string for outline",
        notes="Outline notes",
        images_str="img1, img2",
    )
    assert "Outline template excerpt" in rendered_prompt
    assert "Outline corpus" in rendered_prompt
    assert "Similar cases string for outline" in rendered_prompt
    assert "Outline notes" in rendered_prompt
    assert "img1, img2" in rendered_prompt
    assert (
        "## CASI_SIMILI:" in rendered_prompt
    )  # Check presence of conditional block header


def test_generate_outline_prompt_no_optional_data():
    template = pipeline_test_env.get_template("generate_outline_prompt.jinja2")
    rendered_prompt = template.render(
        template_excerpt="Outline template excerpt basic",
        corpus="Outline corpus basic",
        similar_cases_str="",  # Empty
        notes="Outline notes basic",
        images_str="",  # Empty
    )
    assert "Outline template excerpt basic" in rendered_prompt
    assert "Outline corpus basic" in rendered_prompt
    assert "Outline notes basic" in rendered_prompt
    # Check that the block for similar_cases is omitted or handled if the string is empty
    # Depending on the template: "{% if similar_cases_str %}{{ similar_cases_str }}{% else %}{% endif %}"
    # An empty string would render an empty spot. If the section header is outside the if, it will be present.
    # The template has "## CASI_SIMILI:
    # <<<
    # {% if similar_cases_str %}{{ similar_cases_str }}{% else %}{% endif %}
    # >>>"
    # So the header will be present, but content empty.
    assert "## CASI_SIMILI:" in rendered_prompt
    # To assert no content for similar cases:
    # A bit tricky with Jinja2, might need regex or more complex parsing if we want to be very specific
    # For now, checking header presence is a good start.


# B. expand_section_prompt.jinja2
def test_expand_section_prompt_all_data():
    template = pipeline_test_env.get_template("expand_section_prompt.jinja2")
    rendered_prompt = template.render(
        title="Test Section Title",
        sec_key="test_section_key",
        bullets=["Bullet 1", "Bullet 2"],
        section_question="What is this section about?",
        corpus="Expansion corpus",
        template_excerpt="Expansion template excerpt",
        similar_cases_str="Similar cases for expansion",
        notes="Expansion notes",
        current_extra_styles="Expansion style sample",
    )
    assert "Test Section Title" in rendered_prompt
    assert "test_section_key" in rendered_prompt
    assert "Bullet 1" in rendered_prompt
    assert "What is this section about?" in rendered_prompt
    assert "Expansion corpus" in rendered_prompt
    assert "Expansion template excerpt" in rendered_prompt
    assert "Similar cases for expansion" in rendered_prompt
    assert "Expansion notes" in rendered_prompt
    assert "Expansion style sample" in rendered_prompt
    assert "## CASI_SIMILI" in rendered_prompt
    assert "## ESEMPIO DI STILE" in rendered_prompt


def test_expand_section_prompt_no_optional_data():
    template = pipeline_test_env.get_template("expand_section_prompt.jinja2")
    rendered_prompt = template.render(
        title="Test Section Title Basic",
        sec_key="test_section_key_basic",
        bullets=["Bullet A"],
        section_question="Basic question?",
        corpus="Expansion corpus basic",
        template_excerpt="Expansion template excerpt basic",
        similar_cases_str="",  # Empty
        notes="Expansion notes basic",
        current_extra_styles="",  # Empty
    )
    assert "Test Section Title Basic" in rendered_prompt
    assert "test_section_key_basic" in rendered_prompt
    assert "Expansion corpus basic" in rendered_prompt
    # Check conditional blocks are handled (header might still be present)
    assert "## CASI_SIMILI" in rendered_prompt  # Header present, content empty
    assert "## ESEMPIO DI STILE" in rendered_prompt  # Header present, content empty


# C. harmonize_prompt.jinja2
def test_harmonize_prompt_all_data():
    template = pipeline_test_env.get_template("harmonize_prompt.jinja2")
    rendered_prompt = template.render(
        sections_input_for_prompt='{"section1": "Text 1", "section2": "Text 2"}',  # JSON string
        extra_styles_example="Harmonization style example",
    )
    assert '{"section1": "Text 1", "section2": "Text 2"}' in rendered_prompt
    assert "Harmonization style example" in rendered_prompt
    assert "ESEMPIO DI STILE" in rendered_prompt


def test_harmonize_prompt_no_optional_data():
    template = pipeline_test_env.get_template("harmonize_prompt.jinja2")
    rendered_prompt = template.render(
        sections_input_for_prompt='{"s1": "abc"}', extra_styles_example=""  # Empty
    )
    assert '{"s1": "abc"}' in rendered_prompt
    assert "(Nessun esempio di stile fornito)" in rendered_prompt  # Check fallback text
    assert "ESEMPIO DI STILE" in rendered_prompt  # Header still present
