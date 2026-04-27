# Personal Digestor

Un piccolo Feedly personale locale: legge RSS e URL salvati, deduplica gli articoli, li raggruppa per topic con un LLM e genera una newsletter HTML inviabile via SMTP.

## Setup

```bash
cp .env.example .env
cp profiles/example.yaml profiles/my-client.yaml
python -m digestor add-feed --profile my-client https://example.com/feed.xml --title "Example"
python -m digestor add-url --profile my-client https://example.com/article
```

Compila `.env` con `OPENAI_API_KEY` e credenziali SMTP. Se `OPENAI_API_KEY` non e' presente, il comando `digest` usa un fallback locale estrattivo utile per testare il flusso.

## Flusso giornaliero

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

## Profili cliente/industry

Ogni profilo in `profiles/<nome>.yaml` separa feed, keyword, lingua, destinatario e modello. Puoi duplicare un profilo per ogni cliente o industry e lanciare gli stessi comandi cambiando `--profile`.

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
