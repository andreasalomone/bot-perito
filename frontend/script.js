const form = document.getElementById('frm');
const spinner = document.getElementById('spin');
const statusMessageElement = document.getElementById('status-message');
const fileInput = form.querySelector('input[type="file"][name="files"]');
const submitButton = form.querySelector('button[type="submit"]');
const apiKeyInput = document.getElementById('api_key');

fileInput.addEventListener('change', () => {
  const files = fileInput.files;
  if (files.length > 0) {
    const fileNames = Array.from(files).map(f => f.name).join(', ');
    console.log("General files selected:", fileNames);
  }
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  spinner.style.display = 'block';
  statusMessageElement.textContent = 'Inizializzazione...';
  submitButton.disabled = true;

  // Hide clarification UI at the start of a new request
  const clarificationUIElement = document.getElementById('clarification-ui');
  if (clarificationUIElement) clarificationUIElement.style.display = 'none';

  try {
    const formData = new FormData(form);
    const apiUrl = window.location.hostname === 'localhost'
      ? 'http://localhost:8000/generate'
      : '/api/generate';
    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: { 'X-API-Key': apiKeyInput.value },
      body: formData
    });

    if (response.status === 413) {
      throw new Error('File troppo grande o troppi allegati. Riprova con file più piccoli.');
    }

    if (!response.ok) {
      let errorMsg = `Errore del server: ${response.status}`;
      const responseText = await response.text(); // Read as text first
      try {
        const errorData = JSON.parse(responseText); // Try to parse the text as JSON
        errorMsg = errorData.detail || errorData.message || errorMsg;
      } catch (jsonError) {
        // If JSON.parse fails, use the responseText if it's not empty, otherwise stick to the initial errorMsg
        errorMsg = responseText || errorMsg;
      }
      throw new Error(errorMsg);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let streamFinishedCorrectly = false; // Initialize local flag

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        if (buffer.trim() !== '') {
          console.warn('Stream ended with unprocessed data in buffer:', buffer);
        }
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      let newlineIndex;

      while ((newlineIndex = buffer.indexOf('\n')) >= 0) {
        const line = buffer.substring(0, newlineIndex).trim();
        buffer = buffer.substring(newlineIndex + 1);

        if (line === '') continue;
        const finished = processStreamChunk(line, statusMessageElement, spinner);
        if (finished) {
            streamFinishedCorrectly = true;
            // Optional: break here if we are certain no more useful data follows 'finished'
            // break;
        }
      }
    } // End of while (true) loop

    // After the loop, check if the stream finished correctly
    if (!streamFinishedCorrectly) {
        // Check if an error message is already displayed or clarification needed
        const clarificationIsVisible = clarificationUIElement && clarificationUIElement.style.display === 'block';
        const isErrorState = statusMessageElement.textContent.startsWith('Errore:') || statusMessageElement.textContent.startsWith('Fallimento:');

        // Only show this error if not already in a final error state or waiting for clarification
        if (!clarificationIsVisible && !isErrorState) {
            console.error('Stream ended without a finished event.');
            statusMessageElement.textContent = 'Errore: La comunicazione con il server è stata interrotta inaspettatamente.';
            spinner.style.display = 'none'; // Ensure spinner is stopped
            if (submitButton) submitButton.disabled = false; // Re-enable submit button
        }
    }

  } catch (err) {
    console.error('Errore durante la generazione del report:', err);
    statusMessageElement.textContent = `Fallimento: ${err.message || 'Si è verificato un errore sconosciuto.'}`;
    spinner.style.display = 'none'; // Ensure spinner is stopped on catch
  } finally {
    // Final cleanup - ensure spinner is off unless clarification is shown
    const clarificationUIElement = document.getElementById('clarification-ui');
    if (!clarificationUIElement || clarificationUIElement.style.display !== 'block') {
         spinner.style.display = 'none';
    }
    // Potentially re-enable button if needed, but error/finish handlers should cover most cases.
    // We might still need to ensure it's enabled if clarification isn't shown.
    if (!clarificationUIElement || clarificationUIElement.style.display !== 'block') {
        if (submitButton) submitButton.disabled = false;
    }
  }
});

function processStreamChunk(line, statusElem, spinnerElem) {
  let processedFinishedEvent = false; // Flag for this chunk
  try {
    const data = JSON.parse(line);
    if (data.type === 'status') {
      statusElem.textContent = data.message;
      console.log('Status Update:', data.message);
    } else if (data.type === 'data') {
      console.log('Final Report Data:', data.payload);
      fetchAndDownloadReport(data.payload, statusElem, spinnerElem);
    } else if (data.type === 'clarification_needed') {
      statusElem.textContent = 'Chiarimenti necessari. Inserisci le informazioni richieste.';
      spinnerElem.style.display = 'none';
      console.log('Clarification Needed:', data.missing_fields);
      console.log('Request Artifacts:', data.request_artifacts);
      displayClarificationUI(data.missing_fields, data.request_artifacts);
    } else if (data.type === 'error') {
      const errorMessage = data.message || 'An unknown error occurred.';
      statusElem.textContent = `Errore: ${errorMessage}`;
      console.error('Pipeline Error:', errorMessage);
      spinnerElem.style.display = 'none'; // Stop spinner on error
      // Re-enable main submit button on error to allow retrying
      const mainSubmitButton = form.querySelector('button[type="submit"]');
      if (mainSubmitButton) mainSubmitButton.disabled = false;
    } else if (data.type === 'finished') {
      // Handle the 'finished' event (e.g., log, potentially hide spinner if not already hidden)
      console.log('Pipeline Finished event received.');
      // Spinner might already be hidden by 'data' or 'error' handling, but ensure it is.
      spinnerElem.style.display = 'none';
      // We set a flag here to indicate the stream finished correctly
      processedFinishedEvent = true; // Set flag when finished event is processed
    }
  } catch (e) {
    console.warn('Error parsing JSON stream chunk or incomplete JSON:', line, e);
  }
  return processedFinishedEvent; // Return the flag
}

async function fetchAndDownloadReport(finalCtx, statusElem, spinnerElem) {
  statusElem.textContent = 'Finalizzazione del report e preparazione download...';
  spinnerElem.style.display = 'block'; // Ensure spinner is visible during this step

  try {
    const apiKey = apiKeyInput.value;
    const apiUrl = window.location.hostname === 'localhost'
      ? 'http://localhost:8000/finalize-report'
      : '/api/finalize-report';

    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey
      },
      body: JSON.stringify(finalCtx)
    });

    if (!response.ok) {
      let errorMsg = `Errore durante la finalizzazione del report: ${response.status}`;
      const responseText = await response.text(); // Read as text first
      try {
        const errorData = JSON.parse(responseText); // Try to parse the text as JSON
        errorMsg = errorData.detail || errorData.message || errorMsg;
      } catch (jsonError) {
        // If JSON.parse fails, use the responseText if it's not empty, otherwise stick to the initial errorMsg
        errorMsg = responseText || errorMsg;
      }
      throw new Error(errorMsg);
    }

    const blob = await response.blob();
    const filenameHeader = response.headers.get('content-disposition');
    let filename = 'report_finalizzato.docx'; // Default filename
    if (filenameHeader) {
      const parts = filenameHeader.split('filename=');
      if (parts.length > 1) {
        filename = parts[1].split(';')[0].replace(/["']/g, '');
      }
    }

    const link = document.createElement('a');
    link.href = window.URL.createObjectURL(blob);
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(link.href);

    statusElem.textContent = 'Report scaricato con successo!';
  } catch (err) {
    console.error('Errore durante il fetch e download del report finalizzato:', err);
    statusElem.textContent = `Fallimento finalizzazione: ${err.message || 'Errore sconosciuto.'}`;
  } finally {
    spinnerElem.style.display = 'none';
    // Re-enable main submit button, as this is an end state for the initial flow
    const mainSubmitButton = form.querySelector('button[type="submit"]');
    if (mainSubmitButton) mainSubmitButton.disabled = false;
  }
}

function displayClarificationUI(missingFields, requestArtifacts) {
  const clarificationUIElement = document.getElementById('clarification-ui');
  if (!clarificationUIElement) {
    console.error('Clarification UI placeholder not found in HTML.');
    return;
  }

  // Clear previous content
  clarificationUIElement.innerHTML = '';

  // Add title
  const title = document.createElement('h2');
  title.textContent = 'Informazioni Mancanti';
  title.classList.add('clarification-title');
  clarificationUIElement.appendChild(title);

  const formFragment = document.createDocumentFragment();

  // Iterate through missingFields
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
  submitClarificationsButton.dataset.requestArtifacts = JSON.stringify(requestArtifacts);
  submitClarificationsButton.dataset.missingFields = JSON.stringify(missingFields);
  submitClarificationsButton.classList.add('clarification-submit-button');

  clarificationUIElement.appendChild(formFragment);
  clarificationUIElement.appendChild(submitClarificationsButton);

  submitClarificationsButton.addEventListener('click', handleSubmitClarifications);

  clarificationUIElement.style.display = 'block';

  if (submitButton) {
    submitButton.disabled = false;
  }
  statusMessageElement.textContent = 'Compila i campi richiesti per continuare.';
}

async function handleSubmitClarifications(event) {
  const submitClarificationsButton = event.target;
  const clarificationUIElement = document.getElementById('clarification-ui');

  // Display loading spinner (reuse main one)
  spinner.style.display = 'block';
  statusMessageElement.textContent = 'Inviazione chiarimenti...';
  submitButton.disabled = true;

  try {
    const userClarifications = {};
    // Retrieve missingFields from the button's dataset
    const missingFields = JSON.parse(submitClarificationsButton.dataset.missingFields || '[]');

    if (missingFields && Array.isArray(missingFields)) {
      missingFields.forEach(field => {
        const inputElement = document.getElementById(`clarify-${field.key}`);
        if (inputElement) {
          userClarifications[field.key] = inputElement.value;
        }
      });
    }

    const payload = {
      clarifications: userClarifications,
      // Retrieve requestArtifacts from the button's dataset
      request_artifacts: JSON.parse(submitClarificationsButton.dataset.requestArtifacts || 'null')
    };

    const apiKey = apiKeyInput.value;
    const apiUrl = window.location.hostname === 'localhost'
      ? 'http://localhost:8000/generate-with-clarifications'
      : '/api/generate-with-clarifications';
    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: { 'X-API-Key': apiKey },
      body: JSON.stringify(payload)
    });

    if (response.status === 413) {
      throw new Error('File troppo grande o troppi allegati. Riprova con file più piccoli.');
    }

    if (!response.ok) {
      let errorMsg = `Errore del server: ${response.status}`;
      const responseText = await response.text(); // Read as text first
      try {
        const errorData = JSON.parse(responseText); // Try to parse the text as JSON
        errorMsg = errorData.detail || errorData.message || errorMsg;
      } catch (jsonError) {
        // If JSON.parse fails, use the responseText if it's not empty, otherwise stick to the initial errorMsg
        errorMsg = responseText || errorMsg;
      }
      throw new Error(errorMsg);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let streamFinishedCorrectly = false; // Initialize local flag

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        if (buffer.trim() !== '') {
          console.warn('Stream ended with unprocessed data in buffer:', buffer);
        }
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      let newlineIndex;

      while ((newlineIndex = buffer.indexOf('\n')) >= 0) {
        const line = buffer.substring(0, newlineIndex).trim();
        buffer = buffer.substring(newlineIndex + 1);

        if (line === '') continue;
        const finished = processStreamChunk(line, statusMessageElement, spinner);
        if (finished) {
            streamFinishedCorrectly = true;
            // Optional: break here if we are certain no more useful data follows 'finished'
            // break;
        }
      }
    } // End of while (true) loop

    // After the loop, check if the stream finished correctly
    if (!streamFinishedCorrectly) {
        // Check if an error message is already displayed or clarification needed
        const clarificationIsVisible = clarificationUIElement && clarificationUIElement.style.display === 'block';
        const isErrorState = statusMessageElement.textContent.startsWith('Errore:') || statusMessageElement.textContent.startsWith('Fallimento:');

        // Only show this error if not already in a final error state or waiting for clarification
        if (!clarificationIsVisible && !isErrorState) {
            console.error('Stream ended without a finished event.');
            statusMessageElement.textContent = 'Errore: La comunicazione con il server è stata interrotta inaspettatamente.';
            spinner.style.display = 'none'; // Ensure spinner is stopped
            if (submitButton) submitButton.disabled = false; // Re-enable submit button
        }
    }

  } catch (err) {
    console.error('Errore durante la generazione del report:', err);
    statusMessageElement.textContent = `Fallimento: ${err.message || 'Si è verificato un errore sconosciuto.'}`;
    spinner.style.display = 'none'; // Ensure spinner is stopped on catch
  } finally {
    // Final cleanup - ensure spinner is off unless clarification is shown
    const clarificationUIElement = document.getElementById('clarification-ui');
    if (!clarificationUIElement || clarificationUIElement.style.display !== 'block') {
         spinner.style.display = 'none';
    }
    // Potentially re-enable button if needed, but error/finish handlers should cover most cases.
    // We might still need to ensure it's enabled if clarification isn't shown.
    if (!clarificationUIElement || clarificationUIElement.style.display !== 'block') {
        if (submitButton) submitButton.disabled = false;
    }
  }
}
