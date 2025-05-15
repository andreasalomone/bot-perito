'use strict';

import {
    form,
    fileInput,
    spinner,
    statusMessageElement,
    submitButton,
    apiKeyInput,
    clarificationUIElement,
    validateFiles,
    disableSubmitButton,
    enableSubmitButton,
    showSpinner,
    hideSpinner,
    updateStatus,
    showGeneralError,
    hideClarificationUI,
    getClarificationInputs,
    getActiveRequestArtifacts,
    triggerDownload
} from './ui.js';

import {
    fetchStream,
    HandledApiError,
    getApiUrl
} from './api.js';

import {
    processStreamResponse
} from './stream.js';

import {
    GENERATE_ENDPOINT,
    CLARIFY_ENDPOINT,
    PRESIGN_ENDPOINT
} from './config.js';

// File size limits matching backend configuration
const MAX_FILE_SIZE = 25 * 1024 * 1024; // 25MB per file
const MAX_TOTAL_SIZE = 100 * 1024 * 1024; // 100MB total upload

// --- Event Listeners ---

fileInput.addEventListener('change', validateFiles);

async function getPresignedUrl(filename, contentType, apiKey) {
    const presignApiUrl = getApiUrl(PRESIGN_ENDPOINT) + `?filename=${encodeURIComponent(filename)}&content_type=${encodeURIComponent(contentType)}`;
    updateStatus(`Richiesta URL di upload per ${filename}...`);
    const response = await fetch(presignApiUrl, {
        method: 'POST',
        headers: {
            'X-API-Key': apiKey,
        }
    });
    if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: `Errore ${response.status} ottenendo presigned URL per ${filename}` }));
        throw new Error(errorData.detail || `Errore HTTP ${response.status} per presigned URL`);
    }
    return response.json(); // Aspettati { key: "...", url: "..." }
}

async function uploadToS3(presignedUrl, file) {
    updateStatus(`Caricamento ${file.name} su S3...`);
    const response = await fetch(presignedUrl, {
        method: 'PUT',
        headers: {
            'Content-Type': file.type, // Questo DEVE corrispondere al content_type usato per generare l'URL
        },
        body: file,
    });
    if (!response.ok) {
        // S3 potrebbe ritornare XML per errori, quindi non tentare JSON.parse
        const errorText = await response.text();
        console.error("S3 Upload Error Response Text:", errorText);
        throw new Error(`Errore ${response.status} durante l'upload di ${file.name} su S3.`);
    }
    updateStatus(`${file.name} caricato con successo!`);
}

form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateFiles()) return; // Re-validate before submit

    disableSubmitButton();
    showSpinner();
    updateStatus('Inizializzazione upload S3...');
    hideClarificationUI();

    const files = Array.from(fileInput.files);
    const notes = form.querySelector('#notes_input').value;
    const apiKey = apiKeyInput.value;

    if (!apiKey) {
        showGeneralError("API Key è richiesta.");
        enableSubmitButton();
        hideSpinner();
        return;
    }

    try {
        // 1. Parallelizza l'ottenimento di URL presigned e l'upload a S3
        updateStatus(`Preparazione upload di ${files.length} file su S3...`);

        // Realizziamo gli upload in parallelo per migliorare le prestazioni
        const uploadPromises = files.map(async (file) => {
            try {
                // Ogni file otterrà il proprio URL presigned e poi verrà caricato
                const presignData = await getPresignedUrl(file.name, file.type, apiKey);
                await uploadToS3(presignData.url, file);
                return presignData.key; // Restituisci la chiave S3 per i file caricati con successo
            } catch (error) {
                console.error(`Errore caricando ${file.name}:`, error);
                throw new Error(`Fallimento caricando ${file.name}: ${error.message}`);
            }
        });

        // Attendi che tutti gli upload siano completati
        const s3Keys = await Promise.all(uploadPromises);

        updateStatus(`${files.length} file caricati su S3. Avvio generazione report...`);

        // 2. Chiama /api/generate con le chiavi S3
        const generatePayload = {
            s3_keys: s3Keys,
            notes: notes,
        };

        console.log("Payload being sent to /api/generate:", generatePayload);

        const generateApiUrl = getApiUrl(GENERATE_ENDPOINT);
        const generateResponse = await fetch(generateApiUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': apiKey,
            },
            body: JSON.stringify(generatePayload),
        });

        if (!generateResponse.ok) {
             const errorData = await generateResponse.json().catch(() => ({ detail: `Errore ${generateResponse.status} chiamando /generate` }));
             throw new HandledApiError(errorData.detail || `Errore HTTP ${generateResponse.status} per /generate`);
        }

        // Processa la stream response come prima
        await processStreamResponse(generateResponse, handleSubmitClarifications);

    } catch (err) {
        if (!(err instanceof HandledApiError)) {
            showGeneralError(err.message || 'Errore durante il processo di upload o generazione.');
        }
        console.error('Errore generale nel submit del form:', err);
        if (!clarificationUIElement.style.display || clarificationUIElement.style.display === 'none') {
            enableSubmitButton();
            hideSpinner();
        }
    }
});

// handleSubmitClarifications rimane quasi uguale, ma deve usare getApiUrl()
async function handleSubmitClarifications(event) {
    const submitClarificationsButton = event.target;

    disableSubmitButton(); // Disable main button
    showSpinner();
    updateStatus('Invio chiarimenti...');

    try {
        const missingFields = JSON.parse(submitClarificationsButton.dataset.missingFields || '[]');
        const requestArtifacts = getActiveRequestArtifacts();
        const userClarifications = getClarificationInputs(missingFields);

        if (!requestArtifacts) {
            throw new Error("Artefatti della richiesta non trovati. Impossibile procedere con i chiarimenti.");
        }

        const payload = {
            clarifications: userClarifications,
            request_artifacts: requestArtifacts
        };

        const clarifyApiUrl = getApiUrl(CLARIFY_ENDPOINT);
        const response = await fetch(clarifyApiUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': apiKeyInput.value
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: `Errore ${response.status} chiamando /generate-with-clarifications` }));
            throw new HandledApiError(errorData.detail || `Errore HTTP ${response.status} per /generate-with-clarifications`);
        }

        // /generate-with-clarifications ritorna direttamente il DOCX, quindi dobbiamo scaricare il file direttamente
        const blob = await response.blob();
        const filenameHeader = response.headers.get('content-disposition');
        let filename = 'report_chiarito.docx'; // Default
        if (filenameHeader) {
            const parts = filenameHeader.split('filename=');
            if (parts.length > 1) {
                filename = parts[1].split(';')[0].replace(/["']/g, '');
            }
        }
        triggerDownload(blob, filename);

        // Dopo il download:
        hideClarificationUI();
        enableSubmitButton();
        hideSpinner();
        updateStatus('Report con chiarimenti generato e scaricato.');

    } catch (err) {
        if (!(err instanceof HandledApiError)) {
            showGeneralError(err.message || 'Errore durante la generazione con chiarimenti.');
        }
        console.error('Errore durante la generazione con chiarimenti:', err);
        enableSubmitButton();
        hideSpinner();
    }
}

// Initial state setup
disableSubmitButton(); // Disable button initially until files are selected/validated
