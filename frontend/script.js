const form = document.getElementById('frm');
const spinner = document.getElementById('spin');
const fileInput = form.querySelector('input[type="file"]');
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
    fileInput.title = fileNames;
  }
});

damageInput.addEventListener('change', () => {
  const files = Array.from(damageInput.files);
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
      throw new Error('File troppo grande o troppi allegati');
    }

    if (!response.ok) {
      throw new Error(await response.text());
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'report.docx';
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert(err.message || 'Si è verificato un errore durante la generazione del report');
  } finally {
    spinner.style.display = 'none';
    submitButton.disabled = false;
  }
});
