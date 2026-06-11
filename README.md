# AssetCues Asset Analysis API

Backend for the [AssetCues asset analysis](https://github.com/assetcues26/assetcuesassetanalysis) frontend.

Production-ready FastAPI service that accepts **1–10 photos** of the same physical asset (different angles) and returns exhaustive damage analysis, an asset valuation range, and **token usage + cost** via a single Google Gemini call (`gemini-3.1-flash-lite`).

## Two autopilot endpoints

Both take the same input (1–10 image files) and return the same schema. Upload images, get the full analysis — no separate conversion step.

| Endpoint | How it sends to Gemini | media_resolution | Detail vs cost |
|---|---|---|---|
| `POST /v1/assets/analyze/collage` | merges images into **one labeled collage** → 1 image | `high` | cheaper, less per-angle detail |
| `POST /v1/assets/analyze/multi` | sends **each image as a separate part** in one call | `high` per image | best per-angle detail |

## Features

- **All-angles analysis**: every image is inspected; damage in any angle is reported with its image index
- **Exhaustive damage list**: `damage_items[]` with location, type, severity, and `seen_in_image`
- **Valuation**: as-is range + like-new reference + confidence + disclaimer (₹ and $)
- **Token usage + cost**: `token_usage` and `cost` (USD + INR) from Gemini `usage_metadata`
- **Live FX**: USD→INR fetched live (cached 1h) with safe fallback
- **Observability**: Structured JSON logs, Prometheus metrics at `/metrics`

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements-dev.txt
copy .env.example .env     # Set GEMINI_API_KEY

# LAN + local (required for other devices on same Wi‑Fi)
python serve.py
# or: .\run.ps1

# Local-only (other devices CANNOT connect — do not use for Wi‑Fi sharing)
# uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for interactive API documentation.

### Use from other devices on the same Wi‑Fi

1. Start the server with **`.\run.ps1`** (binds `0.0.0.0`, not only `127.0.0.1`).
2. On the PC, open http://localhost:8000/ — the JSON shows **`lan_base_url`** (e.g. `http://192.168.1.42:8000`).
3. On phones/tablets on the same network, use that URL in the UI or Swagger: `http://<your-pc-ip>:8000/docs`.
4. **Windows Firewall:** if requests fail, allow **Python** or **port 8000** for private networks when prompted.
5. In your UI JavaScript, set the API base to the LAN URL, not `localhost`:
   ```javascript
   const API_BASE = "http://192.168.1.42:8000"; // your PC's Wi‑Fi IP from GET /
   ```
6. CORS is already `allow_origins=["*"]`, so browsers on other devices can call the API.

### UI contract (file uploads only — no base64)

```javascript
const form = new FormData();
for (const file of files) form.append("images", file); // 1-10 files

// pick one endpoint:
const res = await fetch(`${API_BASE}/v1/assets/analyze/multi`, { method: "POST", body: form });
// or: `${API_BASE}/v1/assets/analyze/collage`
const data = await res.json();
```

Output is **clean, grouped JSON** (enforced via Gemini structured output / `response_schema`):

```jsonc
{
  "request_id": "…",
  "status": "success",
  "processing_time_ms": 4200,
  "analysis_method": "multi_image",
  "images_analyzed": 3,
  "review_required": false,
  "asset": {
    "name": "Dell Latitude 5420 laptop",
    "category": "Laptop",
    "type": "Business ultrabook",
    "brand": "Dell", "model": "Latitude 5420",
    "color": "Black", "material": "Aluminium and plastic",
    "estimated_dimensions": "~32 x 21 x 2 cm",
    "estimated_age": "~2021, 3-4 years",
    "quantity": 1, "serial_number": null,
    "asset_tag_number": "1234567890123456",
    "specifications": ["Intel Core i7", "16GB RAM"],
    "accessories": ["power adapter"],
    "distinguishing_features": ["Dell logo on lid"],
    "description": "…"
  },
  "condition": {
    "grade": "Fair", "overall_score": 62, "summary": "…",
    "cosmetic_condition": "…", "structural_condition": "…",
    "functional_status": "Appears functional",
    "cleanliness": "Lightly soiled", "wear_level": "Moderate",
    "usability": "Usable, minor repair advised",
    "repair_recommendation": "Buff lid, clean chassis.",
    "estimated_remaining_life": "2-4 years with normal use",
    "missing_parts": [], "functional_issues": ["bent hinge restricts opening"],
    "positive_aspects": ["screen intact", "all keys present"],
    "has_damage": true, "damage_count": 2,
    "damage_by_severity": { "minor": 1, "moderate": 1, "severe": 0 },
    "damage_items": [
      { "location": "Top lid rear-left", "type": "dent", "severity": "moderate",
        "seen_in_image": 2, "detail": "~1cm dent on rear-left corner.",
        "affects_function": false, "repair_action": "Reshape or replace lid panel." }
    ]
  },
  "identifiers": {
    "asset_tag_number": "1234567890123456",
    "asset_tag_number_raw": "1234567890123456",
    "tag_readable": true,
    "tag_position": "Base panel, Image 3",
    "tag_detection_reasoning": "…",
    "visible_labels": ["Dell", "Latitude 5420"]
  },
  "valuation": {
    "as_is":            { "usd": { "min": 120, "max": 180 }, "inr": { "min": 12000, "max": 18000 } },
    "like_new_reference": { "usd": { "min": 260, "max": 320 }, "inr": { "min": 26000, "max": 32000 } },
    "currency_note": "INR converted at 1 USD = 100 INR.",
    "confidence": 0.45, "assumptions": "…", "disclaimer": "…"
  },
  "confidence": { "overall": 0.81, "asset_name": 0.9, "asset_condition": 0.8, "asset_description": 0.85, "asset_tag_number": 0.7, "valuation": 0.45 },
  "token_usage": { "input_tokens": 8000, "output_tokens": 2000, "total_tokens": 10000,
                   "image_tokens": 6720, "text_tokens": 1280,
                   "images_sent_to_gemini": 3, "per_image_token_budget": 1120, "estimated_image_tokens": 3360 },
  "cost": { "model": "gemini-3.1-flash-lite", "total_cost_usd": 0.005, "total_cost_inr": 0.5,
            "usd_to_inr": 100.0, "fx_source": "fixed_rate", "fx_is_fallback": false }
}
```

### "Refused to connect" from phone

| Check | Fix |
|--------|-----|
| Server only on `127.0.0.1` | Stop uvicorn (Ctrl+C). Run `python serve.py` |
| Wrong URL on phone | Use `http://192.168.x.x:8000` from `GET /` on the PC — not `localhost` |
| Windows Firewall | Run **`scripts\open-firewall.ps1`** as Administrator |
| Wi‑Fi is "Public" | Settings → Network → Wi‑Fi → your network → **Private** |
| Guest Wi‑Fi | Router guest networks often block device-to-device; use main Wi‑Fi |

Verify on the PC after starting with `python serve.py`:

```powershell
netstat -an | findstr ":8000"
```

Must show **`0.0.0.0:8000`** LISTENING. If you only see **`127.0.0.1:8000`**, LAN will not work.

## API Endpoints (Swagger: http://localhost:8000/docs)

| Endpoint | Purpose |
|---|---|
| `POST /v1/assets/analyze/collage` | 1–10 images → merge to one collage → Gemini → analysis + cost |
| `POST /v1/assets/analyze/multi` | 1–10 images → separate parts → Gemini → analysis + cost |
| `GET /v1/health` | Health check |
| `GET /metrics` | Prometheus metrics |

**Response schema:** field reference and dummy JSON (no base64) — [docs/response-schema.md](docs/response-schema.md), [collage example](docs/examples/collage-response-dummy.json), [multi example](docs/examples/multi-response-dummy.json).

### Swagger upload

1. Open **/docs**
2. Expand **Analysis** → `POST /v1/assets/analyze/multi` (or `/collage`)
3. Click **Try it out**
4. For **images**, click **Add item** once per photo (1–10)
5. Execute — JSON includes asset, `damage_items`, `valuation`, `token_usage`, `cost`

## API Usage (curl)

```bash
# Multi-image (separate parts) — best per-angle detail
curl -X POST "http://localhost:8000/v1/assets/analyze/multi" \
  -F "images=@front.jpg" \
  -F "images=@back.jpg" \
  -F "images=@left.jpg"

# Collage (merged into one image)
curl -X POST "http://localhost:8000/v1/assets/analyze/collage" \
  -F "images=@front.jpg" \
  -F "images=@back.jpg"
```

### Cost (gemini-3.1-flash-lite)

Input (text/image/video) **$0.25 / 1M tokens**, output **$1.50 / 1M tokens**. Images bill as input tokens via `media_resolution` (high = 1120 tokens/image). Each response includes a `cost` block in USD **and** INR (live FX). Typical 5–10 image analysis ≈ **$0.005–0.01 (~₹0.4–0.9)**.

## Deploy to Vercel

1. Push this repo to GitHub (see below).
2. Import project in [Vercel](https://vercel.com) → **Add New Project** → select `assetcues26/assetcuesassetanalysis-api`.
3. **Environment variables** (Project → Settings → Environment Variables):
   - `GEMINI_API_KEY` — required
   - `GEMINI_MODEL` — e.g. `gemini-3.1-flash-lite`
   - Other keys from [`.env.example`](.env.example) as needed
4. Deploy. API base URL: `https://<your-project>.vercel.app`

**Note:** the analysis endpoints can take 20–60 seconds. In Vercel → Project → Settings → Functions, set **Max Duration** (e.g. 60s) and **Memory** (max 2048 MB on Hobby). If requests time out, use Docker/Railway/Render instead.

**Deploy uses** `pyproject.toml` → `[tool.vercel] entrypoint = "app.main:app"`. Do not add `api/index.py` in `vercel.json` `functions` — that causes build errors on current Vercel CLI.

```bash
# CLI deploy (after npm i -g vercel)
vercel link
vercel env add GEMINI_API_KEY
vercel --prod
```

## GitHub

```bash
git remote add origin https://github.com/assetcues26/assetcuesassetanalysis-api.git
git branch -M main
git push -u origin main
```

Never commit `.env` — it is in `.gitignore`.

## Docker

```bash
docker compose up --build
```

## Configuration

See [.env.example](.env.example) for all settings.

| Setting | Default | Purpose |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | Gemini model |
| `MAX_IMAGES` | 10 | Max images per request |
| `MAX_IMAGE_SIZE_MB` | 15 | Per-file upload limit |
| `MAX_PREPROCESS_EDGE_PX` | 2048 | Max longest edge before Gemini |
| `MEDIA_RESOLUTION_COLLAGE` / `MEDIA_RESOLUTION_MULTI` | `high` | Detail vs cost (low/medium/high) |
| `GEMINI_INPUT_USD_PER_1M` / `GEMINI_OUTPUT_USD_PER_1M` | 0.25 / 1.50 | Pricing for cost calc |
| `FX_ENABLED` / `USD_TO_INR_FALLBACK` | true / 86.0 | Live USD→INR + fallback |
| `USD_TO_GBP_FALLBACK` | 0.79 | Fallback USD→GBP when FX API unavailable |
| `MULTI_MARKET_ENABLED` | true | When `false`, all requests use India (`IN`) — instant rollback |

### Multi-region valuation (IN / US / GB)

Send `market_region` (`IN`, `US`, or `GB`) on analyze endpoints, or omit it to use the server default `MARKET_REGION` env (`IN` | `US` | `GB`). Cross-device capture sessions store the laptop’s region at QR creation. Responses include `valuation.*.display` and `analysis_policy.display_currency`. India clients reading `valuation.as_is.inr` remain compatible.

**Frontend default:** set `VITE_DEFAULT_MARKET_REGION` on Vercel for the initial market picker value (user choice persists in `localStorage`).

**Production rollback:** set `MULTI_MARKET_ENABLED=false` on the backend (Vercel env). No database migration required.

### Prompts

All Gemini instructions live in [`app/prompts/analysis.txt`](app/prompts/analysis.txt): all-angles inspection, exhaustive damage enumeration, asset identification, barcode OCR, and valuation.

## Development

```bash
pytest
```

## License

MIT
