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
        processStreamChunk(line, statusMessageElement, spinner);
      }
    }

  } catch (err) {
    console.error('Errore durante la generazione del report:', err);
    statusMessageElement.textContent = `Fallimento: ${err.message || 'Si è verificato un errore sconosciuto.'}`;
    spinner.style.display = 'block';
  } finally {
    submitButton.disabled = false;
  }
});

function processStreamChunk(line, statusElem, spinnerElem) {
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
      statusElem.textContent = `Errore: ${data.message}`;
      console.error('Pipeline Error:', data.message);
      spinnerElem.style.display = 'none';
    }
  } catch (e) {
    console.warn('Error parsing JSON stream chunk or incomplete JSON:', line, e);
  }
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

// Store artifacts globally for now, as per plan suggestion
window.currentRequestArtifacts = null;
window.currentMissingFields = null; // To be used by handleSubmitClarifications

function displayClarificationUI(missingFields, requestArtifacts) {
  const clarificationUIElement = document.getElementById('clarification-ui');
  if (!clarificationUIElement) {
    console.error('Clarification UI placeholder not found in HTML.');
    return;
  }

  // Store artifacts and missing fields for later submission
  window.currentRequestArtifacts = requestArtifacts;
  window.currentMissingFields = missingFields; // Store for handleSubmitClarifications

  // Clear previous content
  clarificationUIElement.innerHTML = '';

  // Add title
  const title = document.createElement('h2');
  title.textContent = 'Informazioni Mancanti';
  title.style.marginBottom = '1rem';
  clarificationUIElement.appendChild(title);

  const formFragment = document.createDocumentFragment();

  // Iterate through missingFields
  missingFields.forEach(field => {
    const fieldContainer = document.createElement('div');
    fieldContainer.style.marginBottom = '1rem';

    const label = document.createElement('label');
    label.htmlFor = `clarify-${field.key}`;
    label.textContent = `${field.label}: (${field.question})`;
    label.style.display = 'block';
    label.style.marginBottom = '0.25rem';
    fieldContainer.appendChild(label);

    const input = document.createElement('input');
    input.type = 'text';
    input.id = `clarify-${field.key}`;
    input.name = field.key;
    input.style.width = '100%';
    input.style.padding = '0.75rem';
    input.style.border = '1px solid var(--border-color)';
    input.style.borderRadius = '0.5rem';
    input.style.backgroundColor = 'var(--background-color)';
    input.style.color = 'var(--text-color)';
    fieldContainer.appendChild(input);

    formFragment.appendChild(fieldContainer);
  });

  clarificationUIElement.appendChild(formFragment);

  // Create submit button
  const submitClarificationsButton = document.createElement('button');
  submitClarificationsButton.type = 'button';
  submitClarificationsButton.id = 'submit-clarifications';
  submitClarificationsButton.textContent = 'Invia Chiarimenti e Genera Report';
  // Basic styling, can be enhanced via CSS classes
  submitClarificationsButton.style.padding = '0.75rem 1.5rem';
  submitClarificationsButton.style.marginTop = '1rem';
  clarificationUIElement.appendChild(submitClarificationsButton);

  // Add event listener to the new button
  submitClarificationsButton.addEventListener('click', handleSubmitClarifications);

  // Make clarification UI visible
  clarificationUIElement.style.display = 'block';

  // Re-enable main form submit button (if it was disabled - it is in the current code)
  const mainSubmitButton = form.querySelector('button[type="submit"]');
  if (mainSubmitButton) {
    mainSubmitButton.disabled = false;
  }
  statusMessageElement.textContent = 'Compila i campi richiesti per continuare.';
}

async function handleSubmitClarifications() {
  const submitClarificationsButton = document.getElementById('submit-clarifications');
  const clarificationUIElement = document.getElementById('clarification-ui');

  // Display loading spinner (reuse main one)
  spinner.style.display = 'block';
  statusMessageElement.textContent = 'Invio dei chiarimenti e rigenerazione del report...';
  if (submitClarificationsButton) submitClarificationsButton.disabled = true;

  try {
    const userClarifications = {};
    if (window.currentMissingFields && Array.isArray(window.currentMissingFields)) {
      window.currentMissingFields.forEach(field => {
        const inputElement = document.getElementById(`clarify-${field.key}`);
        if (inputElement) {
          userClarifications[field.key] = inputElement.value;
        }
      });
    }

    const payload = {
      clarifications: userClarifications,
      request_artifacts: window.currentRequestArtifacts
    };

    const apiKey = apiKeyInput.value;
    const apiUrl = window.location.hostname === 'localhost'
      ? 'http://localhost:8000/generate-with-clarifications'
      : '/api/generate-with-clarifications';

    const response = await fetch(apiUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey
      },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      let errorMsg = `Errore durante la generazione con chiarimenti: ${response.status}`;
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

    // Expecting DOCX file directly
    const blob = await response.blob();
    const filenameHeader = response.headers.get('content-disposition');
    let filename = 'report_chiarito.docx'; // Default filename
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

    statusMessageElement.textContent = 'Report generato con successo e scaricato!';
    if (clarificationUIElement) clarificationUIElement.style.display = 'none'; // Hide clarification UI

  } catch (err) {
    console.error('Errore durante l\'invio dei chiarimenti:', err);
    statusMessageElement.textContent = `Fallimento: ${err.message || 'Errore sconosciuto.'}`;
    // Keep spinner if error, user might want to see the error message
  } finally {
    spinner.style.display = 'none'; // Hide spinner in both success and error cases, after message is shown
    if (submitClarificationsButton) submitClarificationsButton.disabled = false;
    // Decide if main form submit button should be re-enabled or not based on flow
    const mainSubmitButton = form.querySelector('button[type="submit"]');
    if (mainSubmitButton) mainSubmitButton.disabled = false;
  }
}

apiKeyInput.addEventListener('input', () => {
  if (apiKeyInput.value.trim() !== "") {
    // Potentially enable submit button if all other conditions are met
    // This depends on your full validation logic
  } else {
    // submitButton.disabled = true; // Disable if API key is removed and was the only thing pending
  }
});
