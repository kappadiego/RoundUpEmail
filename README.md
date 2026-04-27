# RoundUpEmail

Un piccolo Feedly personale: legge RSS e URL salvati, deduplica gli articoli, li raggruppa per topic con un LLM e genera una newsletter HTML inviabile via SMTP. Ora include anche una web app privata con workspace multipli, gestione feed, reader essenziale e scheduler giornaliero.

## Setup

```bash
cp .env.example .env
pip install -e .
python -m digestor.run_web
```

Apri `http://127.0.0.1:8000` e accedi con `APP_PASSWORD`.

Compila `.env` con `APP_PASSWORD`. `OPENAI_API_KEY` e SMTP possono restare vuoti durante il primo test: il digest usa un fallback locale e l'invio email resta disabilitato finche SMTP non e' configurato.

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
python -m digestor.run_web
```

Per un primo test configura solo:

```bash
APP_PASSWORD=una-password-tua
DATA_DIR=/data
SCHEDULER_ENABLED=false
```

Poi, quando vuoi attivare summary LLM e invio email, aggiungi:

```bash
OPENAI_API_KEY=...
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

La web app avvia uno scheduler interno quando `SCHEDULER_ENABLED=true`. Per i primi test lascia `SCHEDULER_ENABLED=false`, poi abilitalo quando SMTP e volume persistente sono pronti:

- scarica i feed a intervallo regolare;
- genera il digest dopo l'orario configurato nel workspace;
- invia la newsletter se Gmail SMTP e' configurato;
- se SMTP non e' configurato, genera il digest ma salta l'invio.

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

I digest HTML vengono salvati sotto `DATA_DIR/digests/<profile>/<date>.html`. Il database SQLite vive in `DATA_DIR/digestor.sqlite`.

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
