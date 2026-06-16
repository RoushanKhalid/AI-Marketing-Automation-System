# Implementation Plan
## AI Marketing Automation System

**Version:** 1.0  
**Date:** June 16, 2026  
**Stack:** Python · FastAPI · SQLite · Groq API · Pollinations.AI

---

## Project Structure

```
AI Marketing Automation System/
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI app entry point, lifespan hooks
│   ├── config.py             # Env var loading, validation (python-dotenv)
│   ├── logger.py             # Logging setup (console + rotating file)
│   ├── models/
│   │   ├── __init__.py
│   │   └── campaign.py       # Campaign dataclass / Pydantic model
│   ├── db/
│   │   ├── __init__.py
│   │   └── campaign_store.py # CampaignStore class — SQLite CRUD
│   ├── services/
│   │   ├── __init__.py
│   │   ├── text_generator.py  # TextGenerator class — Groq API
│   │   ├── image_generator.py # ImageGenerator class — Pollinations.AI
│   │   ├── sms_simulator.py   # SMSSimulator class — console output
│   │   └── scheduler.py       # Scheduler class — background thread
│   └── api/
│       ├── __init__.py
│       └── routes.py          # FastAPI route handlers
├── docs/
│   ├── PRD.md
│   ├── IMPLEMENTATION_PLAN.md
│   └── README.md
├── campaigns.db               # SQLite DB (auto-created at runtime)
├── app.log                    # Rotating log file (auto-created at runtime)
├── .env                       # GROQ_API_KEY and optional config
├── requirements.txt
└── README.md
```

---

## Technology Choices

| Concern | Choice | Reason |
|---|---|---|
| Web framework | FastAPI | Async, auto-docs (Swagger), Pydantic validation built-in |
| LLM text generation | Groq API (`llama3-8b-8192`) | Free tier, fast inference, key already available |
| Image generation | Pollinations.AI | Completely free, no key needed, URL-based |
| Database | SQLite (`sqlite3` stdlib) | Zero setup, file-based, meets spec requirement |
| Background scheduling | `threading.Thread` | Simple, no extra deps, non-blocking |
| Config management | `python-dotenv` | Standard `.env` loading |
| Logging | `logging` stdlib + `RotatingFileHandler` | No extra deps, meets spec |
| HTTP client (Groq) | `groq` Python SDK | Official, well-maintained |

---

## Phase 1 — Foundation

### Step 1.1: Project Scaffold & Config

**Files:** `app/config.py`, `app/logger.py`, `app/__init__.py`

- Create `Config` class that reads from `.env` using `python-dotenv`
- Expose: `GROQ_API_KEY`, `DB_PATH` (default: `campaigns.db`), `SCHEDULER_INTERVAL_SECONDS` (default: `30`)
- Raise `EnvironmentError` on missing `GROQ_API_KEY`
- Set up `logger.py` with two handlers:
  - `StreamHandler` → stdout
  - `RotatingFileHandler` → `app.log` (max 5MB, 3 backups)
- Format: `%(asctime)s | %(levelname)s | %(name)s | %(message)s`

**Dependencies added to `requirements.txt`:**
```
python-dotenv==1.0.1
groq==0.9.0
fastapi==0.111.0
uvicorn[standard]==0.29.0
```

---

### Step 1.2: Campaign Model

**File:** `app/models/campaign.py`

- Define two representations:
  1. `CampaignCreate` — Pydantic `BaseModel` for API input validation
  2. `CampaignRecord` — Pydantic `BaseModel` for API responses (includes `campaign_id`, `status`)
- Pydantic validators enforce:
  - `campaign_name`: non-empty, max 255 chars
  - `prompt`: non-empty, max 2000 chars
  - `phone`: regex `^\+[0-9]{7,15}$` (E.164)
  - `schedule_time`: parsed as `datetime`, format `YYYY-MM-DD HH:MM:SS`
  - `status`: `Literal["pending", "processing", "sent", "failed"]`

```python
# Sketch
class CampaignCreate(BaseModel):
    campaign_name: str = Field(..., max_length=255)
    prompt: str = Field(..., max_length=2000)
    phone: str = Field(..., pattern=r'^\+[0-9]{7,15}$')
    schedule_time: datetime

class CampaignRecord(CampaignCreate):
    campaign_id: int
    status: Literal["pending", "processing", "sent", "failed"] = "pending"
```

---

### Step 1.3: Campaign Persistence (CampaignStore)

**File:** `app/db/campaign_store.py`

- `CampaignStore` class wraps `sqlite3`
- `__init__(db_path)` → opens connection, calls `_create_table()`
- Methods:

| Method | Signature | Behaviour |
|---|---|---|
| `create_campaign` | `(campaign: CampaignCreate) -> CampaignRecord` | INSERT, return with `campaign_id` |
| `get_campaign` | `(campaign_id: int) -> CampaignRecord \| None` | SELECT by id, return None if missing |
| `list_campaigns` | `() -> list[CampaignRecord]` | SELECT all ORDER BY schedule_time ASC |
| `update_status` | `(campaign_id: int, status: str) -> None` | UPDATE status, raise if not found |
| `get_due_campaigns` | `() -> list[CampaignRecord]` | SELECT WHERE status='pending' AND schedule_time <= NOW() |

- Use parameterized queries throughout (no string interpolation)
- Use `threading.Lock` for thread-safe writes (shared between API and Scheduler)

---

## Phase 2 — AI Services

### Step 2.1: TextGenerator

**File:** `app/services/text_generator.py`

- `TextGenerator` class
- `__init__()` → loads `GROQ_API_KEY` from config, initializes `groq.Groq` client
- `generate(prompt: str) -> str`:
  - Validates prompt (non-empty, ≤ 10,000 chars) — raises `ValueError` otherwise
  - Calls `client.chat.completions.create()` with:
    - `model="llama-3.1-8b-instant"`
    - System message: `"You are a creative marketing copywriter. Write compelling, concise marketing text."`
    - User message: the prompt
  - Returns `response.choices[0].message.content`
  - Wraps Groq errors in `RuntimeError` with API detail included

```python
# Sketch
def generate(self, prompt: str) -> str:
    if not prompt or len(prompt) > 10000:
        raise ValueError("Prompt must be 1–10,000 characters")
    logger.info(f"Generating text for prompt: {prompt[:80]}...")
    response = self.client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[
            {"role": "system", "content": "You are a creative marketing copywriter..."},
            {"role": "user", "content": prompt},
        ]
    )
    return response.choices[0].message.content
```

---

### Step 2.2: ImageGenerator

**File:** `app/services/image_generator.py`

- `ImageGenerator` class — no external deps beyond `urllib.parse` (stdlib)
- `generate(prompt: str) -> str`:
  - Validates: non-empty, non-whitespace, ≤ 500 chars
  - URL-encodes prompt using `urllib.parse.quote_plus`
  - Returns `f"https://image.pollinations.ai/prompt/{encoded}"`
  - No HTTP request made — URL is returned directly

```python
# Sketch
BASE_URL = "https://image.pollinations.ai/prompt/{}"

def generate(self, prompt: str) -> str:
    if not prompt or not prompt.strip():
        raise ValueError("Prompt must be non-empty and non-whitespace")
    if len(prompt) > 500:
        raise ValueError("Prompt must not exceed 500 characters")
    encoded = urllib.parse.quote_plus(prompt.strip())
    url = BASE_URL.format(encoded)
    logger.debug(f"Generated image URL: {url}")
    return url
```

---

### Step 2.3: SMSSimulator

**File:** `app/services/sms_simulator.py`

- `SMSSimulator` class
- `send(campaign: CampaignRecord, generated_text: str, image_url: str) -> None`:
  - Validates `generated_text` and `image_url` are non-empty, raises `ValueError` if not
  - Prints the exact format required by the spec
  - Logs INFO with `campaign_id`, `campaign_name`, `phone`

```
Sending marketing message to {phone}
Campaign: {campaign_name}
Generated Text:
{generated_text}
Generated Image:
{image_url}
```

---

## Phase 3 — Scheduler

### Step 3.1: Scheduler

**File:** `app/services/scheduler.py`

- `Scheduler` class
- `__init__(store, text_gen, image_gen, sms_sim, interval_seconds)`
- `start()` → launches `threading.Thread(target=self._run, daemon=True)`
- `_run()` → infinite loop with `time.sleep(interval_seconds)`:

```
loop:
  campaigns = store.get_due_campaigns()   # status=pending, schedule_time <= now
  for campaign in campaigns:
      store.update_status(campaign.campaign_id, "processing")   # lock it
      try:
          text = text_gen.generate(campaign.prompt)
          image = image_gen.generate(campaign.prompt)
          sms_sim.send(campaign, text, image)
          store.update_status(campaign.campaign_id, "sent")
          logger.info(f"Campaign {campaign.campaign_id} sent successfully")
      except Exception as e:
          store.update_status(campaign.campaign_id, "failed")
          logger.error(f"Campaign {campaign.campaign_id} failed at [...]: {e}")
  sleep(interval_seconds)
```

- `get_due_campaigns()` only returns `pending` campaigns, so `processing`/`sent`/`failed` are naturally excluded from re-pickup.

---

## Phase 4 — REST API

### Step 4.1: Route Handlers

**File:** `app/api/routes.py`

| Method | Path | Handler | Response |
|---|---|---|---|
| `POST` | `/campaigns` | `create_campaign` | `201 CampaignRecord` |
| `GET` | `/campaigns` | `list_campaigns` | `200 list[CampaignRecord]` |
| `GET` | `/campaigns/{campaign_id}` | `get_campaign` | `200 CampaignRecord` / `404` |
| `GET` | `/health` | `health_check` | `200 {"status": "ok"}` |

- FastAPI's Pydantic validation handles `422` automatically for bad input.
- `get_campaign` returns `HTTPException(404)` when `store.get_campaign()` returns `None`.
- Global exception handler catches unhandled exceptions → `500` + logs full traceback.

---

### Step 4.2: App Entry Point

**File:** `app/main.py`

- Creates FastAPI app with `lifespan` context manager
- On startup:
  1. Load config (raises if `GROQ_API_KEY` missing)
  2. Initialize logger
  3. Initialize `CampaignStore`
  4. Initialize `TextGenerator`, `ImageGenerator`, `SMSSimulator`
  5. Initialize and start `Scheduler`
- Registers `routes.router`
- Registers global `500` exception handler

---

## Phase 5 — Finalization

### Step 5.1: requirements.txt

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
groq==0.9.0
python-dotenv==1.0.1
pydantic==2.7.1
```

### Step 5.2: README.md

Covers:
- Prerequisites (Python 3.10+)
- Installation steps
- `.env` configuration
- How to run (`uvicorn app.main:app --reload`)
- API usage examples (curl / Swagger UI at `/docs`)
- How the scheduler works
- How to verify SMS simulation output

---

## Implementation Order (Dependency-Safe)

```
Step 1.1  Config + Logger          (no deps)
Step 1.2  Campaign Model           (no deps)
Step 1.3  CampaignStore            (depends on: model)
Step 2.1  TextGenerator            (depends on: config)
Step 2.2  ImageGenerator           (depends on: nothing)
Step 2.3  SMSSimulator             (depends on: model)
Step 3.1  Scheduler                (depends on: store, generators, simulator)
Step 4.1  Route Handlers           (depends on: store, model)
Step 4.2  main.py                  (depends on: all of the above)
Step 5.1  requirements.txt         (finalize versions)
Step 5.2  README.md                (document everything)
```

---

## API Reference (Quick View)

### POST /campaigns
```json
// Request
{
  "campaign_name": "AI Course Launch",
  "prompt": "Promote our new AI course for beginners",
  "phone": "+8801913828774",
  "schedule_time": "2026-06-17 10:00:00"
}

// Response 201
{
  "campaign_id": 1,
  "campaign_name": "AI Course Launch",
  "prompt": "Promote our new AI course for beginners",
  "phone": "+8801913828774",
  "schedule_time": "2026-06-17T10:00:00",
  "status": "pending"
}
```

### GET /campaigns
```json
// Response 200
[
  { "campaign_id": 1, "campaign_name": "...", "status": "pending", ... },
  { "campaign_id": 2, "campaign_name": "...", "status": "sent", ... }
]
```

### GET /campaigns/{id}
```json
// Response 200
{ "campaign_id": 1, "campaign_name": "...", "status": "sent", ... }

// Response 404
{ "detail": "Campaign with id 99 not found" }
```

### GET /health
```json
{ "status": "ok" }
```

---

## Risk & Mitigation

| Risk | Mitigation |
|---|---|
| Groq API rate limit | Model `llama3-8b-8192` has generous free-tier limits; prompt validation keeps requests lean |
| Scheduler race condition (same campaign picked twice) | `processing` status set atomically before generation begins |
| SQLite concurrent writes | `threading.Lock` shared between API and Scheduler |
| Pollinations.AI URL not resolving | URL is returned as-is; no HTTP call at generation time — works offline |
| App restart losing `processing` campaigns | On startup, campaigns stuck in `processing` can optionally be reset to `pending` (enhancement) |
