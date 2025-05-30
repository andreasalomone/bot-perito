'use strict';

import { apiKeyInput, showApiError, triggerDownload, updateStatus } from './ui.js';
import { DEFAULT_FILENAME, FINALIZE_ENDPOINT } from './config.js';

// Custom error class for API errors that have already been shown to the user
export class HandledApiError extends Error {
  constructor(message) {
    super(message);
    this.name = 'HandledApiError';
  }
}

export const getApiUrl = (endpoint) => {
  if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    // Per sviluppo locale, punta al backend FastAPI che esegui localmente
    return `http://localhost:8000/api/${endpoint}`;
  }
  // Per produzione: punta al backend Render
  return `https://aiperito.onrender.com/api/${endpoint}`;
};

const handleApiErrorResponse = async (response) => {
  let errorMsg = `Errore del server: ${response.status}`;
  const responseText = await response.text();
  try {
    const errorData = JSON.parse(responseText.trim());
    if (errorData.details && Array.isArray(errorData.details)) {
      // Format Pydantic errors for better readability
      errorMsg = `Errore di validazione:\n${errorData.details.map(
        err => `  - Campo '${err.loc.join('.') || 'N/A'}': ${err.msg} (input: ${JSON.stringify(err.input)})`
      ).join('\n')}`;
    } else {
      errorMsg = errorData.detail || errorData.message || errorMsg; // Fallback for other errors
    }
  } catch (jsonError) {
    // If parsing fails, use the raw text or the status
    errorMsg = responseText || errorMsg;
    console.warn("Could not parse error response as JSON:", responseText);
  }
  showApiError(errorMsg); // This function is in ui.js and should display the message
  throw new HandledApiError(errorMsg);
};

export const fetchStream = async (endpoint, options) => {
  const apiUrl = getApiUrl(endpoint);
  const response = await fetch(apiUrl, {
    ...options,
    headers: {
      'X-API-Key': apiKeyInput.value,
      ...(options.headers || {}),
    },
  });

  if (response.status === 413) {
    const errorMsg = 'File troppo grande o troppi allegati. Riprova con file più piccoli.';
    showApiError(errorMsg);
    throw new HandledApiError(errorMsg); // Use specialized error
  }

  if (!response.ok) {
    await handleApiErrorResponse(response); // Handles UI update and throws
  }

  return response; // Return the successful response object for stream processing
};


export const finalizeAndDownloadReport = async (finalCtx) => {
  updateStatus('Finalizzazione del report e preparazione download...');
  const apiUrl = getApiUrl(FINALIZE_ENDPOINT);

  try {
    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKeyInput.value
      },
      body: JSON.stringify(finalCtx)
    });

    if (!response.ok) {
      await handleApiErrorResponse(response); // Handles UI update and throws
    }

    const blob = await response.blob();
    const filenameHeader = response.headers.get('content-disposition');
    let filename = DEFAULT_FILENAME;
    if (filenameHeader) {
      const parts = filenameHeader.split('filename=');
      if (parts.length > 1) {
        filename = parts[1].split(';')[0].replace(/["']/g, '');
      }
    }
    triggerDownload(blob, filename);
  } catch (err) {
      // Error already shown by handleApiErrorResponse
      console.error('Errore durante il fetch e download del report finalizzato:', err);
      // Only show error if it's not already handled
      if (!(err instanceof HandledApiError)) {
           showApiError(err.message || 'Errore di rete o finalizzazione');
      }
  }
};
