'use strict';

import { MAX_FILE_SIZE, MAX_TOTAL_SIZE, DEFAULT_FILENAME } from './config.js';

// --- State Tracking ---
export let isErrorActive = false;
export let isClarificationUIVisible = false;
let activeRequestArtifacts = null; // Variable to store requestArtifacts

// --- DOM Elements ---
export const form = document.getElementById('frm');
export const spinner = document.getElementById('spin');
export const statusMessageElement = document.getElementById('status-message');
export const fileInput = form.querySelector('input[type="file"][name="files"]');
export const submitButton = form.querySelector('button[type="submit"]');
export const apiKeyInput = document.getElementById('api_key');
export const clarificationUIElement = document.getElementById('clarification-ui');

// --- Button State Management ---

export const disableSubmitButton = () => {
  if (submitButton) submitButton.disabled = true;
};

export const enableSubmitButton = () => {
  if (submitButton) submitButton.disabled = false;
};

// --- Spinner Management ---

export const showSpinner = () => {
  if (spinner) spinner.style.display = 'block';
};

export const hideSpinner = () => {
  if (spinner) spinner.style.display = 'none';
};

// --- Status Messages ---

export const updateStatus = (message) => {
  if (statusMessageElement) statusMessageElement.textContent = message;
  console.log('Status Update:', message);
};

export const showSuccess = (message) => {
  if (statusMessageElement) statusMessageElement.textContent = message;
  hideSpinner();
  enableSubmitButton();
  isErrorActive = false;
};

export const showGeneralError = (message) => {
  if (statusMessageElement) statusMessageElement.textContent = `Fallimento: ${message || 'Si è verificato un errore sconosciuto.'}`;
  console.error('General Error:', message);
  hideSpinner();
  enableSubmitButton();
  isErrorActive = true;
};

export const showApiError = (message) => {
  if (statusMessageElement) statusMessageElement.textContent = `Errore: ${message || 'Si è verificato un errore sconosciuto.'}`;
  console.error('API Error:', message);
  hideSpinner();
  enableSubmitButton();
  isErrorActive = true;
};

export const showStreamError = (message) => {
    if (statusMessageElement) statusMessageElement.textContent = `Errore: ${message || 'Comunicazione interrotta.'}`;
    console.error('Stream Error:', message);
    hideSpinner();
    enableSubmitButton();
    isErrorActive = true;
};

// --- File Validation ---

export const validateFiles = () => {
  const files = fileInput.files;
  if (files.length === 0) {
    disableSubmitButton(); // Disable if no files are selected
    updateStatus('Seleziona almeno un file per continuare.');
    return false; // Return false to prevent form submission
  }

  console.log("Files selected:", Array.from(files).map(f => f.name).join(', '));

  let totalSize = 0;
  let oversizedFiles = [];

  Array.from(files).forEach(file => {
    totalSize += file.size;
    if (file.size > MAX_FILE_SIZE) {
      oversizedFiles.push({
        name: file.name,
        size: Math.round(file.size / (1024 * 1024) * 10) / 10
      });
    }
  });

  let errorMessage = "";
  if (oversizedFiles.length > 0) {
    errorMessage = `I seguenti file superano il limite di ${MAX_FILE_SIZE / (1024 * 1024)}MB per file:\n`;
    oversizedFiles.forEach(file => {
      errorMessage += `- ${file.name} (${file.size}MB)\n`;
    });
  }

  if (totalSize > MAX_TOTAL_SIZE) {
    if (errorMessage) errorMessage += "\n";
    errorMessage += `La dimensione totale dei file (${Math.round(totalSize / (1024 * 1024))}MB) supera il limite di ${MAX_TOTAL_SIZE / (1024 * 1024)}MB.`;
  }

  if (errorMessage) {
    alert(errorMessage);
    fileInput.value = ""; // Clear selection
    disableSubmitButton();
    return false;
  } else {
    enableSubmitButton();
    return true;
  }
};

// --- Clarification UI ---

export const displayClarificationUI = (missingFields, requestArtifacts, clarificationSubmitHandler) => {
  if (!clarificationUIElement) {
    console.error('Clarification UI placeholder not found.');
    return;
  }

  hideSpinner(); // Hide spinner when asking for clarification
  clarificationUIElement.innerHTML = ''; // Clear previous
  isClarificationUIVisible = true;
  isErrorActive = false;
  activeRequestArtifacts = requestArtifacts; // Store artifacts in variable

  const formFragment = document.createDocumentFragment();

  const title = document.createElement('h2');
  title.textContent = 'Informazioni Mancanti';
  title.classList.add('clarification-title');
  formFragment.appendChild(title);

  missingFields.forEach(field => {
    const fieldContainer = document.createElement('div');
    fieldContainer.classList.add('clarification-field-container');

    const label = document.createElement('label');
    label.htmlFor = `clarify-${field.key}`;
    label.textContent = `${field.label || field.key}: (${field.question || 'Provide value'})`;
    label.classList.add('clarification-label');
    fieldContainer.appendChild(label);

    const input = document.createElement('input');
    input.type = 'text';
    input.id = `clarify-${field.key}`;
    input.name = field.key;
    input.classList.add('clarification-input');
    fieldContainer.appendChild(input);

    formFragment.appendChild(fieldContainer);
  });

  const submitClarificationsButton = document.createElement('button');
  submitClarificationsButton.type = 'button';
  submitClarificationsButton.id = 'submit-clarifications';
  submitClarificationsButton.textContent = 'Invia Chiarimenti e Genera Report';
  submitClarificationsButton.dataset.missingFields = JSON.stringify(missingFields);
  submitClarificationsButton.classList.add('clarification-submit-button');
  formFragment.appendChild(submitClarificationsButton);

  clarificationUIElement.appendChild(formFragment);

  // Attach the handler passed from main.js
  submitClarificationsButton.addEventListener('click', clarificationSubmitHandler);

  clarificationUIElement.style.display = 'block';
  updateStatus('Compila i campi richiesti per continuare.');
  enableSubmitButton(); // Re-enable main button while clarification is shown
};

export const hideClarificationUI = () => {
  if(clarificationUIElement) clarificationUIElement.style.display = 'none';
  isClarificationUIVisible = false;
  activeRequestArtifacts = null; // Clear artifacts when UI is hidden
};

export const getActiveRequestArtifacts = () => activeRequestArtifacts; // Getter

export const getClarificationInputs = (missingFields) => {
    const userClarifications = {};
    if (missingFields && Array.isArray(missingFields)) {
        missingFields.forEach(field => {
            const inputElement = document.getElementById(`clarify-${field.key}`);
            if (inputElement) {
                userClarifications[field.key] = inputElement.value;
            }
        });
    }
    return userClarifications;
};

// --- Report Download ---

export const triggerDownload = (blob, filename) => {
    const link = document.createElement('a');
    link.href = window.URL.createObjectURL(blob);
    link.download = filename || DEFAULT_FILENAME;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(link.href);
    showSuccess('Report scaricato con successo!');
};
