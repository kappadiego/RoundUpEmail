# RoundUpEmail

Un piccolo Feedly personale: legge RSS e URL salvati, deduplica gli articoli, li raggruppa per topic con un LLM e genera una newsletter HTML inviabile via SMTP. Ora include anche una web app privata con workspace multipli, gestione feed, reader essenziale e scheduler giornaliero.

## Setup

```bash
cp .env.example .env
pip install -e .
uvicorn digestor.web:app --reload
```

Apri `http://127.0.0.1:8000` e accedi con `APP_PASSWORD`.

Compila `.env` con `OPENAI_API_KEY`, `APP_PASSWORD` e credenziali SMTP. Se `OPENAI_API_KEY` non e' presente, il digest usa un fallback locale estrattivo utile per testare il flusso.

## Web app

- Login con password condivisa tramite `APP_PASSWORD`.
- Workspace multipli per cliente, industry o dossier editoriale.
- Gestione RSS dalla UI.
- Reader essenziale con articoli letti/salvati e URL singoli da mettere in inbox.
- Digest manuale o automatico, archiviato in HTML.
- Invio email via SMTP, configurabile per Gmail.

## Railway

Collega questa repo a Railway e usa il servizio web generato. La repo include `Procfile` e `railway.json` con start command:

```bash
uvicorn digestor.web:app --host 0.0.0.0 --port ${PORT:-8000}
```

Configura queste variabili:

```bash
OPENAI_API_KEY=...
APP_PASSWORD=...
DATA_DIR=/data
SCHEDULER_ENABLED=true
FETCH_INTERVAL_MINUTES=60
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
SMTP_FROM=...
SMTP_TO=...
```

Monta un volume persistente su `/data`, cosi SQLite e digest HTML sopravvivono ai deploy.

Per Gmail SMTP usa una app password, non la password principale dell'account.

## Flusso giornaliero

La web app avvia uno scheduler interno quando `SCHEDULER_ENABLED=true`:

- scarica i feed a intervallo regolare;
- genera il digest dopo l'orario configurato nel workspace;
- invia la newsletter se Gmail SMTP e' configurato;
- riprova se il digest e' stato generato ma non inviato.

I comandi CLI restano utili per debug/manual run:

```bash
python -m digestor fetch --profile my-client
python -m digestor digest --profile my-client --date today
python -m digestor send --profile my-client --date today
```

Oppure in un solo passaggio:

```bash
python -m digestor run-daily --profile my-client
```

I digest HTML vengono sempre salvati in `digests/<profile>/<date>.html`. Il database SQLite vive in `data/digestor.sqlite`.

## Workspace cliente/industry

La web app salva workspace e feed in SQLite. I vecchi profili YAML restano supportati dai comandi CLI come fallback, ma per l'uso quotidiano conviene gestire tutto dalla UI.

## Comandi

- `add-feed --profile NAME URL`: aggiunge un feed RSS/Atom al profilo.
- `add-url --profile NAME URL`: aggiunge un articolo singolo alla inbox locale.
- `fetch --profile NAME`: scarica feed e URL salvati.
- `digest --profile NAME`: crea il digest HTML e salva il payload in SQLite.
- `send --profile NAME`: invia l'ultimo digest del giorno via SMTP e marca gli articoli come inviati.
- `run-daily --profile NAME`: esegue fetch, digest e send una volta; con `--watch` resta in loop.

## Test

```bash
python -m unittest
```
