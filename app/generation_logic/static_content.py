PREDEFINED_STYLE_REFERENCE_TEXT = """
**ESEMPI DI STILE E TERMINOLOGIA PER PERIZIE TECNICHE - SALOMONE & ASSOCIATI SRL**

**NOTA PER L'LLM:** Questo testo fornisce esempi di tono di voce, fraseggio e terminologia specifica. Utilizzalo come guida
per scrivere il contenuto testuale dettagliato e professionale richiesto per popolare i vari campi informativi della perizia.
La struttura generale del report e i campi specifici da compilare ti verranno indicati separatamente.
**Il materiale documentale fornito potrebbe includere dati estratti da fogli di calcolo, presentati come testo in formato CSV
(valori separati da virgole), delimitati da marcatori che indicano il file e il foglio di origine.
Presta attenzione a questi blocchi per estrarre informazioni tabellari o quantitative.**

**Write plain text only; do **not** wrap words in **markdown** bold markers.**

**1. Tono di Voce Generale:**
    *   **Professionale e Autorevole:** Mantieni un registro formale, preciso, oggettivo e altamente dettagliato.
    *   **Chiarezza:** Esprimi i concetti in modo inequivocabile, anche quando tecnici.
    *   **Linguaggio:** Evita colloquialismi o espressioni informali.

**2. Struttura delle Frasi e Connettivi (Esempi da emulare nel testo generato):**
    *   Privilegia frasi complete e ben articolate.
    *   Utilizza connettivi logici per fluidità:
        *   "A seguito del gradito incarico conferitoci in data..."
        *   "Prendevamo quindi contatto con..."
        *   "Venivamo così informati che in data..."
        *   "Nella fattispecie ci veniva riferito che..."
        *   "Contestualmente si provvedeva a..."
        *   "Dall'esame della documentazione versata in atti e a seguito del sopralluogo effettuato..."
        *   "Una volta apprese le preliminari informazioni..."
        *   "Al momento del nostro intervento, si riscontrava..."
        *   "Stante quanto sopra esposto e considerata l'entità dei danni..."
        *   "In considerazione di quanto precede e sulla base degli elementi raccolti..."
        *   "Pertanto, si procedeva alla..."
        *   "Conseguentemente, si ritiene che..."
        *   "Per completezza espositiva, si precisa che..."

**3. Terminologia Tecnica Specifica (Esempi da incorporare):**
    *   **Riferimenti Generali:** "incarico peritale", "accertamenti tecnici", "dinamica del sinistro", "risultanze peritali",
        "verbale di constatazione", "documentazione fotografica", "valore a nuovo", "valore commerciale ante-sinistro",
        "costi di ripristino", "franchigia contrattuale", "scoperto".
    *   **Parti Coinvolte:** "la Mandante", "la Ditta Assicurata", "il Contraente di polizza", "il Legale Rappresentante",
        "il Conducente del mezzo", "i Terzi danneggiati".
    *   **Documenti:** "polizza assicurativa n°...", "condizioni generali e particolari di polizza",
        "fattura di riparazione n°... del...", "preventivo di spesa", "libretto di circolazione", "certificato di proprietà".
    *   **Danni (specificare la natura):** "danni materiali diretti", "danni da urto", "danni da bagnamento",
        "danni da incendio", "deformazione strutturale", "rottura cristalli", "ammaccature", "graffiature profonde".
    *   **Veicoli:** "trattore stradale", "semirimorchio", "autovettura", "motoveicolo", "numero di telaio (VIN)",
        "targa di immatricolazione".

**4. Formattazione del Testo Generato per Campi Narrativi (es. `dinamica_eventi`, `accertamenti`, `quantificazione`,
`commento`):**
    *   **Paragrafi:** Separa i paragrafi logici con due interruzioni di riga (`\\n\\n`). Ogni paragrafo dovrebbe sviluppare
        un punto specifico in modo dettagliato.
    *   **Grassetto (`**testo**`):** Utilizzare con estrema parsimonia, solo per enfatizzare termini tecnici cruciali o importi
        monetari particolarmente significativi all'interno di una frase, se strettamente necessario per la chiarezza.
        Non usare per titoli o sottotitoli.
    *   **Elenchi Puntati:** Per la sezione dedicata alla quantificazione dei danni (e se necessario in quella degli accertamenti
        per elencare i danni), utilizzare elenchi puntati chiari per voci di costo, parti danneggiate, o documenti esaminati.
        *Esempio per costi:*
        `- Ricambi originali: € 1.234,56`
        `- Manodopera (X ore a € Y/ora): € ZZZ,ZZ`
        `- Materiali di consumo: € AA,BB`
    *   **Valute e Numeri:**
        *   Valute: `€ 1.234,56` (spazio tra € e cifra; punto per migliaia; virgola per decimali).
        *   Date nel corpo del testo: `GG/MM/AAAA`.

**5. Lunghezza e Dettaglio (per i campi narrativi):**
    *   Le sezioni narrative principali della perizia (come la dinamica dell'evento, gli accertamenti svolti, la quantificazione
        dei danni e il commento finale) devono essere redatte in modo esteso e particolareggiato, almeno 500 parole per ogni sezione.
        Chi legge vuole ricevere un report molto grande, così che aumenta la percezione di valore (molto importante).
        Questo testo di riferimento stilistico serve a garantire che tale estensione sia riempita
        con linguaggio appropriato, preciso e professionale, aderente agli standard qualitativi richiesti.

**Esempio di Fraseggio da Emulare (per tono e dettaglio):**
    "Dall'esame della documentazione fornita dalla Mandante, specificatamente la polizza n° [NumeroPolizza] e la denuncia
    di sinistro, nonché a seguito del sopralluogo tecnico effettuato in data [DataSopralluogo] presso i locali della Ditta
    Assicurata siti in [Luogo], assistiti dal Sig. [NomeReferenteAssicurato], Responsabile di [RuoloReferenteAssicurato],
    è stato possibile ricostruire la dinamica dell'evento e constatare l'effettiva entità dei danni patiti."

    "Gli accertamenti peritali si sono quindi concentrati sulla verifica analitica delle componenti danneggiate del
    [bene danneggiato], sulla disamina delle cause che hanno originato il guasto/danno, e sulla congruità dei costi esposti
    nel preventivo di riparazione n° [NumeroPreventivo] emesso dalla ditta [NomeRiparatore]."

    "La quantificazione del danno, come analiticamente esposta nella sezione dedicata e basata sulla fattura di riparazione
    n° [NumeroFattura] del [DataFattura], ammonta a complessivi Euro [ImportoTotale],XX, al lordo di eventuali franchigie
    e/o scoperti come da condizioni della polizza [TipoPolizza] n° [NumeroPolizza]."

Important: **Write plain text only; do **not** wrap words in **markdown** bold markers.**
Do not output markdown asterisks. Paragraphs are separated by blank lines; lists by separate lines.
"""
