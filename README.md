# USM Progress Dashboard

Streamlit dashboard that reads live progress data from [Google Sheets](https://docs.google.com/spreadsheets/d/1-0DFZT-jrzdUkEfjS1v0S2Z13qSEjRcEGp5b6DbFp1o/edit). Deploy free on [Streamlit Community Cloud](https://streamlit.io/cloud) with a public GitHub repo.

## Features

- **Dashboard** — campus cards with overall progress %; click a campus for detail
- **Campus detail** — multi-line chart of each activity’s % over time
- **Overall data** — project-wide percentages by date
- **Daily history** — plan-before-work and after-work updates with photos (view: public; add: admin only)

## How you update data

1. **Progress** — edit the main Google Sheet yourself (same as today). The app refreshes every 5 minutes.
2. **Daily history** — either add rows in a **Daily History** tab, or use the admin form in the app (requires service account; see below).

## Google Sheet setup

### 1. Share for reading (required)

Share the spreadsheet: **Anyone with the link → Viewer**.

### 2. Sheet tabs (campuses)

Your spreadsheet has **one tab per campus**, plus an overall summary tab:

| Tab | Campus | GID |
|-----|--------|-----|
| **INDUK** | Induk campus | `1128960310` |
| **NIBONG TEBAL** | Nibong Tebal campus | `1224245491` |
| **BERTAM** | Bertam campus | `129329596` |
| **BUKIT JAMBUL** | Bukit Jambul campus | `1957109182` |
| **KUBANG KERIAN** | Kubang Kerian campus | `602849075` |

Each tab is one campus — including **INDUK**. The app loads all of them equally.

### 3. Daily History tab (optional)

Create a tab named **Daily History** with header row:

| Date | Campus | Type | Title | Description | Image_URLs |
|------|--------|------|-------|-------------|------------|

- **Image_URLs**: comma-separated links (e.g. Google Drive “anyone with link” URLs)
- Copy the tab GID from the URL (`#gid=...`) and set `HISTORY_GID` in `config.py`

## Run locally

```bash
cd streamlit-sheets-app
pip install -r requirements.txt
streamlit run app.py
```

Optional local secrets:

```bash
mkdir .streamlit
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
# Edit admin_password
```

## Deploy on Streamlit Cloud (free)

1. Push this folder to a **public GitHub** repository
2. Go to [share.streamlit.io](https://share.streamlit.io) → **New app**
3. Select your repo, main file: `app.py`
4. In **Advanced settings → Secrets**, paste:

```toml
admin_password = "choose-a-strong-password"

[gcp_service_account]
# ... only if you want admin form to write history to the sheet
```

5. Deploy

### Admin writes to Google Sheet

To let the **Admin — add entry** form append rows automatically:

1. [Google Cloud Console](https://console.cloud.google.com/) → create project → enable **Google Sheets API**
2. Create a **service account** → download JSON key
3. Share your Google Sheet with the service account email (**Editor**)
4. Add the JSON fields under `[gcp_service_account]` in Streamlit secrets

Without a service account, you can still add history rows manually in the **Daily History** tab.

## Campus configuration

Edit `config.py` to:

- Add or update sheet tabs in `SHEET_TABS` (run `python scripts/discover_tabs.py` to list GIDs)
- Change icons in `CAMPUS_ICONS`

## Project structure

```
streamlit-sheets-app/
├── app.py                 # Main Streamlit app
├── config.py              # Sheet ID, campuses, activities
├── requirements.txt
├── lib/
│   ├── sheets_client.py   # Google Sheets read/write
│   ├── data_parser.py     # Parse your sheet layout
│   └── auth.py            # Admin password gate
└── .streamlit/
    ├── config.toml
    └── secrets.toml.example
```

## Notes

- Photos are stored as **URLs** (Google Drive recommended), not uploaded files — Streamlit Cloud has no persistent disk.
- Keep `admin_password` in secrets only; never commit it to GitHub.
- Service account JSON is also secrets-only.
