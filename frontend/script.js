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

// -----------------------------------------------------------------------------
//  Config – keep in sync with backend limits
// -----------------------------------------------------------------------------
const MAX_FILE_SIZE  = 25 * 1024 * 1024;   // 25 MB per file
const MAX_TOTAL_SIZE = 100 * 1024 * 1024;  // 100 MB total

// -----------------------------------------------------------------------------
//  File-input helper
// -----------------------------------------------------------------------------
fileInput.addEventListener('change', validateFiles);

// -----------------------------------------------------------------------------
//  Presign URL helper
// -----------------------------------------------------------------------------
async function getPresignedUrl(filename, contentType, apiKey) {
    const presignApiUrl =
        getApiUrl(PRESIGN_ENDPOINT) +
        `?filename=${encodeURIComponent(filename)}` +
        `&content_type=${encodeURIComponent(contentType)}`;

    updateStatus(`Richiesta URL di upload per ${filename}…`);

    const res = await fetch(presignApiUrl, {
        method: 'POST',
        headers: { 'X-API-Key': apiKey }
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({
            detail: `Errore ${res.status} ottenendo presigned URL per ${filename}`
        }));
        throw new Error(err.detail || `HTTP ${res.status} presign URL`);
    }

    return res.json();   // { key: "...", url: "..." }
}

// -----------------------------------------------------------------------------
//  S3 upload helper  (NEW, robust CORS / error handling)
// -----------------------------------------------------------------------------
async function uploadToS3(presignedUrl, file) {
    updateStatus(`Caricamento ${file.name} su S3…`);

    const res = await fetch(presignedUrl, {
        method: 'PUT',
        mode:   'cors',                               // explicit for clarity
        headers: { 'Content-Type': file.type || 'application/octet-stream' },
        body: file,
    });

    /*  If the bucket’s CORS rule doesn’t include the page’s origin, the
        response is "opaque": res.type === 'opaque', res.status === 0,
        res.ok === false.  We treat that as an error so devs notice. */
    if (!res.ok) {
        let detail = '';
        if (res.type !== 'opaque') {
            detail = await res.text().catch(() => '');
            console.error('S3 error body:', detail);
        }
        throw new Error(
            res.type === 'opaque'
                ? `Upload bloccato dalle CORS per ${file.name}`
                : `Errore ${res.status} durante l'upload di ${file.name}`
        );
    }

    updateStatus(`${file.name} caricato con successo!`);
}

// -----------------------------------------------------------------------------
//  Form submit
// -----------------------------------------------------------------------------
form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!validateFiles()) return;          // re-validate before submit

    disableSubmitButton();
    showSpinner();
    updateStatus('Inizializzazione upload S3…');
    hideClarificationUI();

    const files   = Array.from(fileInput.files);
    const notes   = form.querySelector('#notes_input').value;
    const apiKey  = apiKeyInput.value;

    if (!apiKey) {
        showGeneralError('API Key è richiesta.');
        enableSubmitButton();
        hideSpinner();
        return;
    }

    try {
        // -------------------------------------------------------------
        // 1. Upload all files in parallel
        // -------------------------------------------------------------
        updateStatus(`Preparazione upload di ${files.length} file su S3…`);

        const uploadPromises = files.map(async (file) => {
            try {
                const { url, key } = await getPresignedUrl(file.name, file.type, apiKey);
                await uploadToS3(url, file);
                return key;                              // success → S3 key
            } catch (err) {
                console.error(`Errore caricando ${file.name}:`, err);
                throw new Error(`Fallimento caricando ${file.name}: ${err.message}`);
            }
        });

        const s3Keys = await Promise.all(uploadPromises);

        updateStatus(`${files.length} file caricati su S3. Avvio generazione report…`);

        // -------------------------------------------------------------
        // 2. Call /api/generate
        // -------------------------------------------------------------
        const payload = { s3_keys: s3Keys, notes };
        console.log('Payload being sent to /api/generate:', payload);

        const generateRes = await fetch(getApiUrl(GENERATE_ENDPOINT), {
            method:  'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': apiKey
            },
            body: JSON.stringify(payload)
        });

        if (!generateRes.ok) {
            const err = await generateRes.json().catch(() => ({
                detail: `Errore ${generateRes.status} chiamando /generate`
            }));
            throw new HandledApiError(err.detail || `HTTP ${generateRes.status} /generate`);
        }

        await processStreamResponse(generateRes, handleSubmitClarifications);

    } catch (err) {
        if (!(err instanceof HandledApiError)) {
            showGeneralError(err.message || 'Errore durante upload o generazione.');
        }
        console.error('Errore generale nel submit del form:', err);
        if (!clarificationUIElement.style.display || clarificationUIElement.style.display === 'none') {
            enableSubmitButton();
            hideSpinner();
        }
    }
});

// -----------------------------------------------------------------------------
//  Clarification submit
// -----------------------------------------------------------------------------
async function handleSubmitClarifications(event) {
    const btn = event.target;

    disableSubmitButton();
    showSpinner();
    updateStatus('Invio chiarimenti…');

    try {
        const missing   = JSON.parse(btn.dataset.missingFields || '[]');
        const artifacts = getActiveRequestArtifacts();
        const answers   = getClarificationInputs(missing);

        if (!artifacts) {
            throw new Error('Artefatti della richiesta non trovati.');
        }

        const payload = { clarifications: answers, request_artifacts: artifacts };

        const res = await fetch(getApiUrl(CLARIFY_ENDPOINT), {
            method:  'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': apiKeyInput.value
            },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({
                detail: `Errore ${res.status} chiamando /generate-with-clarifications`
            }));
            throw new HandledApiError(err.detail || `HTTP ${res.status} /generate-with-clarifications`);
        }

        const blob      = await res.blob();
        const cdHeader  = res.headers.get('content-disposition');
        let   filename  = 'report_chiarito.docx';
        if (cdHeader) {
            const parts = cdHeader.split('filename=');
            if (parts.length > 1) filename = parts[1].split(';')[0].replace(/["']/g, '');
        }
        triggerDownload(blob, filename);

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

// -----------------------------------------------------------------------------
//  Initial UI state
// -----------------------------------------------------------------------------
disableSubmitButton();
