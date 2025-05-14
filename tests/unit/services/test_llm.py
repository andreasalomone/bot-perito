import pytest
from unittest.mock import AsyncMock, patch, Mock
# UUID is not used in the current version of the tests, can be removed if not planned for future use.
# from uuid import UUID

# MockSettings is used to mock the settings object accessed by the llm module.
class MockSettings:
    def __init__(self):
        self.model_id = "test_model_123"
        # openrouter_api_key is used by llm.py for client initialization,
        # but client is directly mocked in these tests. Retained for completeness if MockSettings
        # is used elsewhere or if client init was part of the test.
        self.openrouter_api_key = "sk-fakekey"

# Imports from the application code being tested
from app.services.llm import call_llm, LLMError # client is also from here but patched by name
# app_settings is imported from app.core.config but not directly used in these tests as
# 'app.services.llm.settings' is patched. Can be removed if not used for other tests in this file.
# from app.core.config import settings as app_settings
from openai import OpenAIError, APIError # Used for specific error type testing
import tenacity # Added for tenacity.RetryError

# Now also importing extract_json and JSONParsingError for the new tests
from app.services.llm import extract_json, JSONParsingError

# And execute_llm_step_with_template for its tests
from app.services.llm import execute_llm_step_with_template
import jinja2 # For TemplateNotFound

# And build_prompt for its tests
from app.services.llm import build_prompt


@pytest.mark.asyncio
@patch('app.services.llm.settings', new_callable=lambda: MockSettings()) # Mock settings module used by llm.py
@patch('app.services.llm.client', new_callable=AsyncMock) # Mock the client instance in llm.py
async def test_call_llm_success(mock_llm_client_instance, mock_settings_module):
    """
    Tests a successful call to the call_llm function.
    It mocks the AsyncOpenAI client's chat.completions.create method
    to return a successful response.
    """
    # Arrange
    test_prompt = "Hello, LLM!"
    expected_response_content = "Hello, User!"
    request_id_capture = None

    # Configure the mock client's behavior
    # The client itself is mocked, so we configure its methods
    mock_chat_completion = AsyncMock()
    mock_chat_completion.choices = [AsyncMock()]
    mock_chat_completion.choices[0].message = AsyncMock()
    mock_chat_completion.choices[0].message.content = expected_response_content

    # The client is already an AsyncMock due to @patch.
    # We need to make sure its 'chat.completions.create' returns our mock_chat_completion
    mock_llm_client_instance.chat.completions.create = AsyncMock(return_value=mock_chat_completion)

    # Act
    actual_response = await call_llm(prompt=test_prompt)

    # Assert
    assert actual_response == expected_response_content

    # Verify that the mocked client method was called correctly
    mock_llm_client_instance.chat.completions.create.assert_called_once()
    call_args = mock_llm_client_instance.chat.completions.create.call_args

    # Check model_id from mocked settings
    assert call_args.kwargs['model'] == mock_settings_module.model_id
    assert call_args.kwargs['messages'] == [{"role": "user", "content": test_prompt}]

    # Optionally, capture and validate the request_id if needed for logging checks
    # This requires inspecting logger calls if the ID is not returned.
    # For simplicity, we're focusing on the call_llm return and client interaction here.

@pytest.mark.asyncio
@patch('app.services.llm.settings', new_callable=lambda: MockSettings())
@patch('app.services.llm.client', new_callable=AsyncMock)
async def test_call_llm_empty_response_content(mock_llm_client_instance, mock_settings_module):
    """
    Tests call_llm when the LLM returns a response with None or empty string content.
    """
    test_prompt = "Test prompt for empty content"

    mock_chat_completion = AsyncMock()
    mock_chat_completion.choices = [AsyncMock()]
    mock_chat_completion.choices[0].message = AsyncMock()
    mock_chat_completion.choices[0].message.content = None # Simulate None content

    mock_llm_client_instance.chat.completions.create = AsyncMock(return_value=mock_chat_completion)

    actual_response_none = await call_llm(prompt=test_prompt)
    assert actual_response_none == "" # Expected to strip None to empty string

    mock_chat_completion.choices[0].message.content = "" # Simulate empty string content
    actual_response_empty = await call_llm(prompt=test_prompt)
    assert actual_response_empty == ""

@pytest.mark.asyncio
@patch('app.services.llm.settings', new_callable=lambda: MockSettings())
@patch('app.services.llm.client', new_callable=AsyncMock) # Mock the client instance in llm.py
async def test_call_llm_openai_error_raises_llm_error(mock_llm_client_instance, mock_settings_module):
    """
    Tests that an OpenAIError during the LLM call is caught and re-raised as LLMError.
    This version ensures the error is NOT retryable.
    """
    test_prompt = "Prompt that causes a non-retryable error"

    # Simulate a non-retryable OpenAIError
    class MockOpenAIError(OpenAIError):
        def __init__(self, message, status_code=None):
            super().__init__(message)
            self.status_code = status_code
            self.message = message

    # Use a status_code that _should_retry_llm_call evaluates as False (e.g., 400)
    mock_error = MockOpenAIError("Simulated Non-Retryable API Error", status_code=400)
    mock_llm_client_instance.chat.completions.create.side_effect = mock_error

    with pytest.raises(LLMError) as excinfo:
        await call_llm(prompt=test_prompt)

    assert "OpenAI API error: Simulated Non-Retryable API Error" in str(excinfo.value)
    assert excinfo.value.__cause__ is mock_error
    # Ensure create was called only once, no retries
    mock_llm_client_instance.chat.completions.create.assert_called_once()

@pytest.mark.asyncio
@patch('app.services.llm.settings', new_callable=lambda: MockSettings())
@patch('app.services.llm.client', new_callable=AsyncMock)
async def test_call_llm_retry_logic_success_on_third_attempt(mock_llm_client_instance, mock_settings_module):
    """
    Tests the retry logic of call_llm.
    It should retry on specific OpenAIError status codes and succeed on the third attempt.
    The retry decorator is set to stop_after_attempt(3).
    """
    test_prompt = "Prompt for retry test"
    expected_response_content = "Success after retries!"

    # Mock response for successful call
    mock_successful_completion = AsyncMock()
    mock_successful_completion.choices = [AsyncMock()]
    mock_successful_completion.choices[0].message = AsyncMock()
    mock_successful_completion.choices[0].message.content = expected_response_content

    # Simulate retriable OpenAIError (e.g., rate limit)
    # The actual OpenAIError requires a response and body for the status_code attribute.
    # For simplicity, we'll mock the status attribute directly on a custom error.
    # In a real scenario with `openai` library, you might need to construct a more complete
    # mock `openai.APIStatusError` if the retry logic specifically checks `error.status_code`.
    # The current retry logic in `llm.py` uses `getattr(exc, "status", None)`.
    # If llm.py is updated to use status_code, this mock needs to provide it.
    class RetriableOpenAIError(APIError): # Using APIError as a base for status_code
        def __init__(self, message, status_code):
            # APIError constructor: message, request, body. Fake these.
            # For testing, it's simpler to just set the attribute if the predicate looks for it.
            super().__init__(message, request=AsyncMock(), body=None)
            self.status_code = status_code
            self.message = message


    # Configure side_effect to raise error twice, then return success
    mock_llm_client_instance.chat.completions.create.side_effect = [
        RetriableOpenAIError("Simulated Rate Limit Error", status_code=429),
        RetriableOpenAIError("Simulated Server Error", status_code=500),
        mock_successful_completion
    ]

    # Act
    actual_response = await call_llm(prompt=test_prompt)

    # Assert
    assert actual_response == expected_response_content
    assert mock_llm_client_instance.chat.completions.create.call_count == 3

    # Verify call arguments for the last successful call (optional, but good practice)
    last_call_args = mock_llm_client_instance.chat.completions.create.call_args_list[-1]
    assert last_call_args.kwargs['model'] == mock_settings_module.model_id
    assert last_call_args.kwargs['messages'] == [{"role": "user", "content": test_prompt}]

@pytest.mark.asyncio
@patch('app.services.llm.settings', new_callable=lambda: MockSettings())
@patch('app.services.llm.client', new_callable=AsyncMock)
async def test_call_llm_retry_logic_fails_after_max_attempts(mock_llm_client_instance, mock_settings_module):
    """
    Tests the retry logic of call_llm when it fails after all retry attempts.
    The retry decorator is set to stop_after_attempt(3).
    It should raise tenacity.RetryError wrapping the final LLMError.
    """
    test_prompt = "Prompt for retry failure test"

    class RetriableOpenAIError(APIError):
        def __init__(self, message, status_code):
            super().__init__(message, request=AsyncMock(), body=None)
            self.status_code = status_code
            self.message = message

    # Simulate retriable OpenAIError for all attempts
    error_to_raise_on_each_attempt = RetriableOpenAIError("Simulated Persistent Server Error", status_code=502)
    mock_llm_client_instance.chat.completions.create.side_effect = [
        error_to_raise_on_each_attempt,
        error_to_raise_on_each_attempt,
        error_to_raise_on_each_attempt  # This will be the 3rd attempt
    ]

    # Act & Assert
    with pytest.raises(tenacity.RetryError) as excinfo_retry:
        await call_llm(prompt=test_prompt)

    # The RetryError contains information about the last attempt.
    # The exception from the last attempt of call_llm should be an LLMError.
    final_llm_error = excinfo_retry.value.last_attempt.exception()

    assert isinstance(final_llm_error, LLMError), "The exception from the last attempt should be LLMError"
    assert "OpenAI API error: Simulated Persistent Server Error" in str(final_llm_error)
    assert isinstance(final_llm_error.__cause__, RetriableOpenAIError)
    assert final_llm_error.__cause__ is error_to_raise_on_each_attempt # Check it's the same error instance

    assert mock_llm_client_instance.chat.completions.create.call_count == 3

@pytest.mark.asyncio
@patch('app.services.llm.settings', new_callable=lambda: MockSettings())
@patch('app.services.llm.client', new_callable=AsyncMock)
async def test_call_llm_generic_exception_raises_llm_error(mock_llm_client_instance, mock_settings_module):
    """
    Tests that a generic Exception during the LLM call (not an OpenAIError)
    is caught and re-raised as an LLMError.
    """
    test_prompt = "Prompt that causes a generic error"

    # Simulate a generic RuntimeError
    generic_error_message = "Simulated unexpected runtime error"
    generic_error = RuntimeError(generic_error_message)
    mock_llm_client_instance.chat.completions.create.side_effect = generic_error

    with pytest.raises(LLMError) as excinfo:
        await call_llm(prompt=test_prompt)

    # Check that the LLMError message contains the generic error's message
    assert f"Unexpected error in LLM call: {generic_error_message}" in str(excinfo.value)
    # Check that the original generic error is chained as the cause
    assert excinfo.value.__cause__ is generic_error

# --- Tests for extract_json ---

def test_extract_json_perfect_match():
    text = '{"key": "value", "number": 123}'
    expected = {"key": "value", "number": 123}
    assert extract_json(text) == expected

def test_extract_json_with_markdown_fences():
    text = 'Some leading text\n```json\n{"key": "value", "nested": {"foo": "bar"}}\n```\nTrailing text.'
    expected = {"key": "value", "nested": {"foo": "bar"}}
    assert extract_json(text) == expected

def test_extract_json_embedded_in_text():
    text = 'Here is some JSON: {"name": "Test", "valid": true} and some more text.'
    expected = {"name": "Test", "valid": True}
    assert extract_json(text) == expected

def test_extract_json_with_newlines_inside_json_block():
    text = '```json\n{\n  "user_name": "test_user",\n  "user_id": 12345,\n  "roles": [\n    "editor",\n    "viewer"\n  ]\n}\n```'
    expected = {
        "user_name": "test_user",
        "user_id": 12345,
        "roles": ["editor", "viewer"]
    }
    assert extract_json(text) == expected

def test_extract_json_no_json_structure():
    text = "This is just a plain string without any JSON."
    with pytest.raises(JSONParsingError, match="No JSON structure found in response"):
        extract_json(text)

def test_extract_json_malformed_extracted_json():
    text = 'Some text preceding a malformed structure: {"key": "value", "unterminated" "True" } and some trailing text'
    # The regex will extract '{"key": "value", "unterminated" "True" }'
    # which is not valid JSON due to missing colon after "unterminated".
    with pytest.raises(JSONParsingError) as excinfo:
        extract_json(text)
    # The error from json.loads(extracted) will be "Expecting ':' delimiter..."
    # This is wrapped by JSONParsingError in llm.py
    assert "Failed to parse JSON: Expecting ':' delimiter" in str(excinfo.value)

def test_extract_json_empty_string():
    text = ""
    with pytest.raises(JSONParsingError, match="Unexpected error parsing JSON: No JSON structure found in response"):
        extract_json(text)

def test_extract_json_only_curly_braces():
    text = "{}"
    expected = {}
    assert extract_json(text) == expected

def test_extract_json_with_text_after_valid_json_in_fences():
    text = '```json\n{"key": "value"}\n``` some other text {"ignored": true}'
    # The current regex r"\{.*\}" is greedy. It will find the first { and the last }.
    # So it would extract '{"key": "value"}\n``` some other text {"ignored": true}'
    # This would fail to parse.
    # This test highlights the greedy nature of the current regex if multiple JSON-like blocks exist.
    # Depending on desired behavior, the regex or logic might need adjustment.
    # For now, testing current behavior.
    with pytest.raises(JSONParsingError):
        extract_json(text)

def test_extract_json_first_json_block_is_malformed_second_is_valid():
    text = "Text with malformed: {key: value}, then valid: {\"valid_key\": \"valid_value\"}. End."
    # Current regex r"{.*}" will grab from the first '{' to the last '}'
    # extracted = "{key: value}, then valid: {\"valid_key\": \"valid_value\"}. End."
    # This will fail parsing.
    with pytest.raises(JSONParsingError):
        extract_json(text)

# --- Tests for execute_llm_step_with_template ---

@pytest.mark.asyncio
@patch('app.services.llm.extract_json')
@patch('app.services.llm.call_llm', new_callable=AsyncMock) # call_llm is async
@patch('app.services.llm.env') # Mock the Jinja2 environment
async def test_execute_llm_step_successful(mock_jinja_env, mock_call_llm, mock_extract_json):
    request_id = "test_req_id_success"
    step_name = "TestStepSuccess"
    template_name = "test_template.jinja2"
    context = {"var": "value"}
    expected_data = {"result": "llm_data"}
    rendered_prompt = "This is the rendered prompt from template."
    raw_llm_response = "{\"result\": \"llm_data\"}" # Raw string from LLM

    # Configure mocks
    mock_template = Mock() # Jinja2 template methods are sync
    mock_template.render = Mock(return_value=rendered_prompt) # render is sync
    mock_jinja_env.get_template = Mock(return_value=mock_template) # get_template is sync
    mock_call_llm.return_value = raw_llm_response
    mock_extract_json.return_value = expected_data

    result = await execute_llm_step_with_template(
        request_id, step_name, template_name, context, expected_type=dict
    )

    assert result == expected_data
    mock_jinja_env.get_template.assert_called_once_with(template_name)
    mock_template.render.assert_called_once_with(**context)
    mock_call_llm.assert_called_once_with(rendered_prompt)
    mock_extract_json.assert_called_once_with(raw_llm_response)

@pytest.mark.asyncio
@patch('app.services.llm.extract_json')
@patch('app.services.llm.call_llm', new_callable=AsyncMock)
@patch('app.services.llm.env')
async def test_execute_llm_step_type_validation_fails(mock_jinja_env, mock_call_llm, mock_extract_json):
    request_id = "test_req_id_type_fail"
    step_name = "TestStepTypeFail"
    template_name = "test_template.jinja2"
    context = {"var": "value"}
    # LLM returns a list, but we expect a dict
    llm_parsed_data = ["item1", "item2"]
    rendered_prompt = "Rendered prompt"
    raw_llm_response = '["item1", "item2"]'

    mock_template = Mock()
    mock_template.render = Mock(return_value=rendered_prompt)
    mock_jinja_env.get_template = Mock(return_value=mock_template)
    mock_call_llm.return_value = raw_llm_response
    mock_extract_json.return_value = llm_parsed_data

    with pytest.raises(LLMError, match=f"Invalid data format received during '{step_name}' step."):
        await execute_llm_step_with_template(
            request_id, step_name, template_name, context, expected_type=dict
        )

@pytest.mark.asyncio
@patch('app.services.llm.env') # Only need to mock env for this specific failure
async def test_execute_llm_step_jinja_env_none(mock_jinja_env):
    # Temporarily set the module's `env` to None for this test
    with patch('app.services.llm.env', None):
        with pytest.raises(LLMError, match="Internal configuration error: Template environment not available."):
            await execute_llm_step_with_template(
                "req_id_env_none", "StepEnvNone", "any_template.jinja2", {}, expected_type=dict
            )

@pytest.mark.asyncio
@patch('app.services.llm.env')
async def test_execute_llm_step_template_not_found(mock_jinja_env):
    request_id = "test_req_id_tpl_not_found"
    step_name = "TestStepTplNotFound"
    template_name = "non_existent_template.jinja2"
    context = {}

    mock_jinja_env.get_template.side_effect = jinja2.TemplateNotFound(template_name)

    with pytest.raises(LLMError, match=f"Internal configuration error: Template '{template_name}' not found."):
        await execute_llm_step_with_template(
            request_id, step_name, template_name, context
        )

@pytest.mark.asyncio
@patch('app.services.llm.extract_json') # Mock this as it's called after call_llm
@patch('app.services.llm.call_llm', new_callable=AsyncMock)
@patch('app.services.llm.env')
async def test_execute_llm_step_call_llm_raises_llmerror(mock_jinja_env, mock_call_llm, mock_extract_json):
    error_message = "LLM failed spectacularly"
    mock_template = Mock()
    mock_template.render = Mock(return_value="prompt")
    mock_jinja_env.get_template = Mock(return_value=mock_template)
    mock_call_llm.side_effect = LLMError(error_message)

    with pytest.raises(LLMError, match=error_message) as excinfo:
        await execute_llm_step_with_template("req", "step", "tpl.j2", {})

    # Ensure it's the exact same error instance being re-raised
    assert excinfo.value is mock_call_llm.side_effect
    mock_extract_json.assert_not_called() # Should not be called if call_llm fails

@pytest.mark.asyncio
@patch('app.services.llm.extract_json')
@patch('app.services.llm.call_llm', new_callable=AsyncMock)
@patch('app.services.llm.env')
async def test_execute_llm_step_extract_json_raises_jsonparsingerror(mock_jinja_env, mock_call_llm, mock_extract_json):
    error_message = "JSON totally unparseable"
    mock_template = Mock()
    mock_template.render = Mock(return_value="prompt")
    mock_jinja_env.get_template = Mock(return_value=mock_template)
    mock_call_llm.return_value = "invalid json string"
    mock_extract_json.side_effect = JSONParsingError(error_message)

    with pytest.raises(JSONParsingError, match=error_message) as excinfo:
        await execute_llm_step_with_template("req", "step", "tpl.j2", {})

    assert excinfo.value is mock_extract_json.side_effect

@pytest.mark.asyncio
@patch('app.services.llm.call_llm', new_callable=AsyncMock)
@patch('app.services.llm.env')
async def test_execute_llm_step_generic_exception_in_render(mock_jinja_env, mock_call_llm):
    # Test for a generic exception occurring, for example, during template rendering
    error_message = "Something broke in render"
    mock_template = Mock() # Sync mock
    mock_template.render = Mock(side_effect=RuntimeError(error_message)) # Sync method
    mock_jinja_env.get_template = Mock(return_value=mock_template) # Sync method
    step_name = "TestStepGenericException"

    with pytest.raises(LLMError, match=f"Unexpected error during '{step_name}' step.") as excinfo:
        await execute_llm_step_with_template("req_generic", step_name, "tpl.j2", {})

    assert isinstance(excinfo.value.__cause__, RuntimeError)
    assert str(excinfo.value.__cause__) == error_message
    mock_call_llm.assert_not_called()

# --- Tests for build_prompt ---

@patch('app.services.llm.settings', new_callable=lambda: MockSettings())
@patch('app.services.llm.env') # Mock the Jinja2 environment
def test_build_prompt_all_options(mock_jinja_env, mock_settings):
    template_excerpt = "Test excerpt"
    corpus = "Test corpus data."
    notes = "Some important notes."
    reference_style_text = "This is a reference style."
    expected_rendered_prompt = "Final rendered prompt with all parts."

    mock_template = Mock() # Sync mock
    mock_template.render = Mock(return_value=expected_rendered_prompt) # Sync method
    mock_jinja_env.get_template = Mock(return_value=mock_template) # Sync method

    # Expect literal "\\n" sequences because build_prompt inserts them literally.
    expected_extra_styles = (
        f"\\n\\nESEMPIO DI FORMATTAZIONE (SOLO PER TONO E STILE; IGNORA CONTENUTO):\\n<<<\\n{reference_style_text}\\n>>>"
    )

    result = build_prompt(template_excerpt, corpus, notes, reference_style_text)

    assert result == expected_rendered_prompt
    mock_jinja_env.get_template.assert_called_once_with("build_prompt.jinja2")
    mock_template.render.assert_called_once_with(
        template_excerpt=template_excerpt,
        extra_styles=expected_extra_styles,
        corpus=corpus,
        notes=notes,
    )

@patch('app.services.llm.settings', new_callable=lambda: MockSettings())
@patch('app.services.llm.env')
def test_build_prompt_no_style_text(mock_jinja_env, mock_settings):
    # ... similar setup to test_build_prompt_all_options, but reference_style_text is "" ...
    template_excerpt = "Excerpt"
    corpus = "Corpus"
    notes = "Notes"
    reference_style_text = ""
    expected_rendered_prompt = "Rendered without style."

    mock_template = Mock()
    mock_template.render = Mock(return_value=expected_rendered_prompt)
    mock_jinja_env.get_template = Mock(return_value=mock_template)

    expected_extra_styles = ""  # No style text -> no extra_styles block

    result = build_prompt(template_excerpt, corpus, notes, reference_style_text)

    assert result == expected_rendered_prompt
    mock_template.render.assert_called_once_with(
        template_excerpt=template_excerpt,
        extra_styles="",  # Important: empty
        corpus=corpus,
        notes=notes,
    )


def test_build_prompt_jinja_env_none(mocker):
    import app.services.llm as llm_module
    mocker.patch.object(llm_module, 'env', None)
    mocker.patch.object(llm_module, 'settings', MockSettings())
    with pytest.raises(LLMError, match="Internal configuration error: Template environment not available."):
        build_prompt("excerpt", "corpus", "notes", "style")

@patch('app.services.llm.settings', new_callable=lambda: MockSettings())
@patch('app.services.llm.env')
def test_build_prompt_template_not_found(mock_jinja_env_patch_arg, mock_settings_patch_arg): # Corrected param order/names
    # mock_settings_patch_arg is not strictly needed here as settings are not accessed if template loading fails early,
    # but pytest will pass it.
    mock_jinja_env_patch_arg.get_template.side_effect = jinja2.TemplateNotFound("build_prompt.jinja2")
    with pytest.raises(LLMError, match="Internal configuration error: Template 'build_prompt.jinja2' not found."):
        build_prompt("excerpt", "corpus", "notes", "style")

@patch('app.services.llm.settings', new_callable=lambda: MockSettings())
@patch('app.services.llm.env')
def test_build_prompt_generic_exception_in_render(mock_jinja_env, mock_settings):
    error_message = "Render failed spectacularly"
    mock_template = Mock() # Sync mock
    mock_template.render = Mock(side_effect=RuntimeError(error_message)) # Sync method
    mock_jinja_env.get_template = Mock(return_value=mock_template) # Sync method

    with pytest.raises(LLMError, match="Unexpected error building prompt.") as excinfo:
        build_prompt("excerpt", "corpus", "notes", "style")

    assert isinstance(excinfo.value.__cause__, RuntimeError)
    assert str(excinfo.value.__cause__) == error_message
