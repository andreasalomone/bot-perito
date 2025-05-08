const form = document.getElementById('frm');
const spinner = document.getElementById('spin');
const fileInput = form.querySelector('input[type="file"]');
const submitButton = form.querySelector('button[type="submit"]');
const apiKeyInput = document.getElementById('api_key');

fileInput.addEventListener('change', () => {
  const files = fileInput.files;
  if (files.length > 0) {
    const fileNames = Array.from(files).map(f => f.name).join(', ');
    fileInput.title = fileNames;
  }
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  spinner.style.display = 'block';
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
