'use strict';

import { apiKeyInput, showApiError, triggerDownload, updateStatus } from './ui.js';
import { DEFAULT_FILENAME } from './config.js';

const getApiUrl = (endpoint) => {
  return window.location.hostname === 'localhost'
    ? `http://localhost:8000/${endpoint}`
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
  throw new Error(errorMsg); // Re-throw for main handler catch block
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
    throw new Error(errorMsg); // Re-throw
  }

  if (!response.ok) {
    await handleApiErrorResponse(response); // Handles UI update and throws
  }

  return response; // Return the successful response object for stream processing
};


export const finalizeAndDownloadReport = async (finalCtx) => {
  updateStatus('Finalizzazione del report e preparazione download...');
  const apiUrl = getApiUrl('finalize-report'); // Use constant

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
      // Error already shown by handleApiErrorResponse or fetch error
      console.error('Errore durante il fetch e download del report finalizzato:', err);
      // No need to call showApiError again if handleApiErrorResponse was called
      // If fetch itself failed, err might be a TypeError, show a general error
      if (!(err instanceof Error && err.message.startsWith('Errore del server:'))) {
           showApiError(err.message || 'Errore di rete o finalizzazione');
      }
  }
};
