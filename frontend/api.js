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
  return window.location.hostname === 'localhost'
    ? `http://localhost:8000/api/${endpoint}`
    : `/api/${endpoint}`;
};

const handleApiErrorResponse = async (response) => {
  let errorMsg = `Errore del server: ${response.status}`;
  const responseText = await response.text();
  try {
    const errorData = JSON.parse(responseText);
    errorMsg = errorData.detail || errorData.message || errorMsg;
  } catch (jsonError) {
    errorMsg = responseText || errorMsg;
  }
  showApiError(errorMsg);
  throw new HandledApiError(errorMsg); // Throw specialized error
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
