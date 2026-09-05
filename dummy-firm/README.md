# Dummy firm — Harbour International Chambers

The only firm corpus. It is built from real records, not generated Apex Chambers prose.

Sources:

- PCIJ English PDFs (`data/CD-PCIJ_*.zip`) — one matter per case
- UN Security Council resolutions (`data/CR-UNSC_*.zip`) — one matter per year
- Indian electricity filings in `../docs/` — one matter per proceeding

## Layout

```
dummy-firm/
  files/pcij/<case>/            original PCIJ PDFs
  files/unsc/<year>/            English resolution text
  files/india-energy/<matter>/  copies of docs/ PDFs
  data/                         ingest JSON/JSONL (same names as before)
```

## Build

```bash
cd dummy-firm
python3 scripts/build_corpus.py
```

Do not run a synthetic generator. Apex Chambers template output has been removed.
