# Usa un'immagine Python ufficiale. Python 3.11 è quello che usi.
FROM python:3.11-slim

# Impedisce a Python di scrivere file .pyc e bufferizzare stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Imposta la directory di lavoro
WORKDIR /app

# Copia prima il file delle dipendenze per sfruttare il caching di Docker
COPY requirements.txt .

# Installa le dipendenze
# --no-cache-dir riduce la dimensione dell'immagine
# Potresti aver bisogno di dipendenze di sistema per python-magic (libmagic1 su Debian)
RUN apt-get update && apt-get install -y libmagic1 tesseract-ocr tesseract-ocr-ita tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

# Copia il resto del codice dell'applicazione nella directory /app
COPY . .

# La porta su cui Uvicorn ascolterà. Render inietterà la sua $PORT.
# Uvicorn di default usa 8000 se --port non è specificato.
# Esponiamo 8000 per documentazione, ma Render gestirà la mappatura.
EXPOSE 8000

# Comando per avviare l'applicazione.
# app.main:app si riferisce all'oggetto `app` nel file `app/main.py`.
# Render imposta la variabile d'ambiente PORT, Uvicorn la usa se --port non è specificato
# o se usiamo ${PORT}.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
# Alternativa più robusta che rispetta la $PORT di Render:
# CMD sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"
# Il ${PORT:-8000} usa la var d'ambiente PORT se settata, altrimenti defaulta a 8000.
# Per Render, la semplice CMD uvicorn ... --port 8000 funziona perché Render mappa la sua porta pubblica alla 8000 interna.
