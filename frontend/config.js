'use strict';

// File size limits matching backend configuration
export const MAX_FILE_SIZE = 25 * 1024 * 1024; // 25MB per file
export const MAX_TOTAL_SIZE = 100 * 1024 * 1024; // 100MB total upload

// API Endpoints
export const GENERATE_ENDPOINT = 'generate';
export const FINALIZE_ENDPOINT = 'finalize-report';
export const CLARIFY_ENDPOINT = 'generate-with-clarifications';
export const PRESIGN_ENDPOINT = 'presign';

// Default filename
export const DEFAULT_FILENAME = 'report_finalizzato.docx';
