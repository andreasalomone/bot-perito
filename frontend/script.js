'use strict';

import {
    form,
    fileInput,
    spinner, // Keep direct spinner access for now
    statusMessageElement, // Keep direct access
    submitButton, // Keep direct access
    apiKeyInput, // Keep direct access
    clarificationUIElement, // Keep direct access
    validateFiles,
    disableSubmitButton,
    enableSubmitButton,
    showSpinner,
    hideSpinner,
    updateStatus,
    showGeneralError,
    hideClarificationUI,
    getClarificationInputs
} from './ui.js';

import {
    fetchStream,
} from './api.js';

import {
    processStreamResponse
} from './stream.js';

import {
    GENERATE_ENDPOINT,
    CLARIFY_ENDPOINT
} from './config.js';

// File size limits matching backend configuration
const MAX_FILE_SIZE = 25 * 1024 * 1024; // 25MB per file
const MAX_TOTAL_SIZE = 100 * 1024 * 1024; // 100MB total upload

// Helper functions
const getApiUrl = (endpoint) => {
  return window.location.hostname === 'localhost'
    ? `http://localhost:8000/${endpoint}`
    : `/api/${endpoint}`;
};

const handleApiError = async (response) => {
  let errorMsg = `Errore del server: ${response.status}`;
  const responseText = await response.text();
  try {
    const errorData = JSON.parse(responseText);
    errorMsg = errorData.detail || errorData.message || errorMsg;
  } catch (jsonError) {
    errorMsg = responseText || errorMsg;
  }
  throw new Error(errorMsg);
};

// --- Event Listeners ---

fileInput.addEventListener('change', validateFiles);

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateFiles()) return; // Re-validate before submit

    disableSubmitButton();
    showSpinner();
    updateStatus('Inizializzazione...');
    hideClarificationUI();

    try {
        const formData = new FormData(form);
        const response = await fetchStream(GENERATE_ENDPOINT, {
            method: 'POST',
            body: formData
            // Content-Type is set automatically by browser for FormData
        });

        // Pass the handler for the clarification submit button
        await processStreamResponse(response, handleSubmitClarifications);

    } catch (err) {
        // UI update (spinner hide, button enable, message) is handled
        // within the specific error functions (showApiError, showGeneralError etc.)
        // or by handleApiErrorResponse called within fetchStream
        // Log the error here if it wasn't handled by those
        if (!(err instanceof Error && (err.message.includes('Errore del server') || err.message.includes('File troppo grande')))){
             showGeneralError(err.message);
        }
        console.error('Errore durante la generazione iniziale:', err);
    }
    // No finally block needed here for button/spinner state, handled by specific outcome handlers
});

// Handler for the dynamically created clarification submit button
async function handleSubmitClarifications(event) {
    const submitClarificationsButton = event.target;

    disableSubmitButton(); // Disable main button
    showSpinner();
    updateStatus('Invio chiarimenti...');

    try {
        const missingFields = JSON.parse(submitClarificationsButton.dataset.missingFields || '[]');
        const requestArtifacts = JSON.parse(submitClarificationsButton.dataset.requestArtifacts || 'null');
        const userClarifications = getClarificationInputs(missingFields);

        const payload = {
            clarifications: userClarifications,
            request_artifacts: requestArtifacts
        };

        const response = await fetchStream(CLARIFY_ENDPOINT, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        // Process the new stream response, passing the handler again (though unlikely to be needed)
        await processStreamResponse(response, handleSubmitClarifications);

    } catch (err) {
        // Error handling similar to the main submit handler
         if (!(err instanceof Error && (err.message.includes('Errore del server') || err.message.includes('File troppo grande')))){
             showGeneralError(err.message);
        }
        console.error('Errore durante la generazione con chiarimenti:', err);
    }
}

// Initial state setup
disableSubmitButton(); // Disable button initially until files are selected/validated
