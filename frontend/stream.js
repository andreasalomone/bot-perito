'use strict';

import {
    hideSpinner,
    updateStatus,
    showApiError,
    showStreamError,
    displayClarificationUI,
    clarificationUIElement, // Import for checking visibility
    isErrorActive,
    isClarificationUIVisible
} from './ui.js';
import { finalizeAndDownloadReport } from './api.js';

// Processes a single line (chunk) from the stream
const processStreamChunk = (line, clarificationSubmitHandler) => {
  let processedFinishedEvent = false;
  try {
    const data = JSON.parse(line);
    switch (data.type) {
      case 'status':
        updateStatus(data.message);
        break;
      case 'data':
        // Process data without logging full payload
        finalizeAndDownloadReport(data.payload);
        break;
      case 'clarification_needed':
        updateStatus('Chiarimenti necessari...'); // Update status before showing UI
        displayClarificationUI(data.missing_fields, data.request_artifacts, clarificationSubmitHandler);
        break;
      case 'error':
        showApiError(data.message); // Use specific error handler
        break;
      case 'finished':
        console.log('Pipeline Finished event received.');
        // Don't hide spinner here, let the final success/error handle it
        processedFinishedEvent = true;
        break;
      default:
        console.warn('Unknown stream event type:', data.type);
    }
  } catch (e) {
    console.warn('Error parsing JSON stream chunk or incomplete JSON:', line, e);
    // Optional: Show a generic stream error here if parsing fails repeatedly?
  }
  return processedFinishedEvent;
};

// Reads and processes the entire stream
export const processStreamResponse = async (response, clarificationSubmitHandler) => {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let streamFinishedCorrectly = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      if (buffer.trim() !== '') {
        console.warn('Stream ended with unprocessed data in buffer:', buffer);
      }
      break; // Exit loop when stream is done
    }

    buffer += decoder.decode(value, { stream: true });
    let newlineIndex;

    while ((newlineIndex = buffer.indexOf('\n')) >= 0) {
      const line = buffer.substring(0, newlineIndex).trim();
      buffer = buffer.substring(newlineIndex + 1);

      if (line === '') continue;

      // Pass the clarification handler down
      const finished = processStreamChunk(line, clarificationSubmitHandler);
      if (finished) {
        streamFinishedCorrectly = true;
        // Don't break the loop; allow stream to close naturally
      }
    }
  } // End of while loop

  // Check if the stream finished without a 'finished' event
  if (!streamFinishedCorrectly) {
      checkStreamFinishedState();
  }
};

const checkStreamFinishedState = () => {
    // Only show this error if not already in a final error state or waiting for clarification
    if (!isClarificationUIVisible && !isErrorActive) {
        showStreamError('La comunicazione con il server è stata interrotta inaspettatamente.');
    }
};
