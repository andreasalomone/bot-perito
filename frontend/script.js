const form = document.getElementById('frm');
const spinner = document.getElementById('spin');
const statusMessageElement = document.getElementById('status-message');
const fileInput = form.querySelector('input[type="file"][name="files"]');
const submitButton = form.querySelector('button[type="submit"]');
const apiKeyInput = document.getElementById('api_key');
const useRagInput = document.getElementById('use_rag');

// Add client-side validation for damage images count and size
const damageInput = form.querySelector('input[name="damage_imgs"]');
const MAX_DAMAGE_IMAGES = 10;
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

fileInput.addEventListener('change', () => {
  const files = fileInput.files;
  if (files.length > 0) {
    const fileNames = Array.from(files).map(f => f.name).join(', ');
    console.log("General files selected:", fileNames);
  }
});

damageInput.addEventListener('change', () => {
  const files = Array.from(damageInput.files);
  submitButton.disabled = false;

  if (files.length > MAX_DAMAGE_IMAGES) {
    alert(`Puoi caricare al massimo ${MAX_DAMAGE_IMAGES} immagini di danni.`);
    damageInput.value = '';
    submitButton.disabled = true;
    return;
  }
  for (const file of files) {
    if (file.size > MAX_FILE_SIZE) {
      alert(`Il file ${file.name} è troppo grande. La dimensione massima è 10MB.`);
      damageInput.value = '';
      submitButton.disabled = true;
      return;
    }
  }
  // Re-enable the submit button when validations pass
  submitButton.disabled = false;
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  spinner.style.display = 'block';
  statusMessageElement.textContent = 'Inizializzazione...';
  submitButton.disabled = true;

  try {
    const formData = new FormData(form);
    formData.append('use_rag', useRagInput.checked);
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
      try {
        const errorData = await response.json();
        errorMsg = errorData.detail || errorData.message || errorMsg;
      } catch (jsonError) {
        errorMsg = await response.text() || errorMsg;
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
      statusElem.textContent = 'Report generato con successo!';
      console.log('Final Report Data:', data.payload);
      spinnerElem.style.display = 'none';

      alert('Report processato. Scaricamento non implementato in questa versione con status stream.');

    } else if (data.type === 'error') {
      statusElem.textContent = `Errore: ${data.message}`;
      console.error('Pipeline Error:', data.message);
      spinnerElem.style.display = 'none';
    }
  } catch (e) {
    console.warn('Error parsing JSON stream chunk or incomplete JSON:', line, e);
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
