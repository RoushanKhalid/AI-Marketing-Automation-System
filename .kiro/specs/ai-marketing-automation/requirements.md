# Requirements Document

## Introduction

This document defines the requirements for an **AI Marketing Automation System** — a Python-based backend service that enables users to create, schedule, and dispatch AI-generated marketing campaigns. The system leverages the Groq API for text generation and Pollinations.AI for image URL generation, stores campaigns in a SQLite database, and exposes all functionality via a FastAPI REST API. SMS delivery is simulated via structured console output.

---

## Glossary

- **System**: The AI Marketing Automation System as a whole.
- **API**: The FastAPI-based HTTP REST interface exposed by the System.
- **Campaign**: A marketing job consisting of a name, a prompt, a target phone number, and a scheduled dispatch time.
- **Campaign_Store**: The SQLite-backed persistence layer responsible for storing and retrieving Campaign records.
- **Text_Generator**: The component that calls the Groq API to produce marketing copy from a Campaign prompt.
- **Image_Generator**: The component that constructs a Pollinations.AI image URL from a Campaign prompt.
- **Scheduler**: The background component that monitors the current time and triggers dispatch for due Campaigns.
- **SMS_Simulator**: The component that prints the formatted marketing message to the console in place of real SMS delivery.
- **Logger**: The application-wide structured logging facility.
- **Prompt**: A natural-language instruction string provided by the user that describes the desired marketing content.
- **Schedule_Time**: A datetime value in `YYYY-MM-DD HH:MM:SS` format representing when a Campaign should be dispatched.
- **Status**: The lifecycle state of a Campaign — one of `pending`, `sent`, or `failed`.

---

## Requirements

---

### Requirement 1: Campaign Data Model

**User Story:** As a developer, I want a well-defined Campaign data model, so that all components share a consistent structure for campaign information.

#### Acceptance Criteria

1. THE System SHALL represent each Campaign with the following fields: `campaign_id` (auto-generated unique integer), `campaign_name` (non-empty string, max 255 characters), `prompt` (non-empty string, max 2000 characters), `phone` (E.164 format: `+` followed by 7–15 digits), `schedule_time` (datetime in `YYYY-MM-DD HH:MM:SS` format), and `status` (one of `pending`, `processing`, `sent`, `failed`).
2. WHEN a Campaign is created without a `status` value, THE System SHALL assign the default status `pending`.
3. IF any required field (`campaign_name`, `prompt`, `phone`, `schedule_time`) is missing or empty, THEN THE System SHALL reject the Campaign and return a validation error that identifies each invalid or missing field by name.
4. IF `schedule_time` is provided in a format other than `YYYY-MM-DD HH:MM:SS`, THEN THE System SHALL reject the Campaign with an error message specifying the required format.
5. IF `status` is provided at creation time with a value other than `pending`, `processing`, `sent`, or `failed`, THEN THE System SHALL reject the Campaign with an error indicating the accepted values.

---

### Requirement 2: Campaign Persistence

**User Story:** As a user, I want campaigns to be stored persistently, so that they survive application restarts and can be retrieved at any time.

#### Acceptance Criteria

1. THE Campaign_Store SHALL use a SQLite database file to persist all Campaign records.
2. WHEN the application starts, THE Campaign_Store SHALL create the campaigns table if it does not already exist.
3. WHEN a valid Campaign is submitted, THE Campaign_Store SHALL insert it and return the system-assigned integer `campaign_id`.
4. WHEN a list of all Campaigns is requested, THE Campaign_Store SHALL return all stored Campaign records ordered by `schedule_time` ascending.
5. WHEN a Campaign is requested by `campaign_id`, THE Campaign_Store SHALL return the matching record.
6. IF no Campaign exists for a given `campaign_id`, THEN THE Campaign_Store SHALL return `null` to the caller.
7. WHEN a Campaign's status is updated, THE Campaign_Store SHALL persist the new status value, which must be one of `pending`, `processing`, `sent`, or `failed`, for that `campaign_id`.
8. IF a status update targets a non-existent `campaign_id`, THEN THE Campaign_Store SHALL raise a not-found exception identifying the missing `campaign_id`.
9. IF an invalid or incomplete Campaign object is passed to the insert operation, THEN THE Campaign_Store SHALL raise a validation exception without writing any partial record to the database.

---

### Requirement 3: Marketing Text Generation

**User Story:** As a marketer, I want AI-generated marketing text from my prompt, so that I can produce compelling copy without writing it manually.

#### Acceptance Criteria

1. WHEN a non-empty Prompt of 1–10,000 characters is provided, THE Text_Generator SHALL call the Groq API using the configured `GROQ_API_KEY` and return the generated marketing text as a non-empty string.
2. THE Text_Generator SHALL load `GROQ_API_KEY` from the application environment at startup.
3. IF the Groq API call fails or returns an error response, THEN THE Text_Generator SHALL log the error and raise an exception whose message includes the API error detail.
4. THE Text_Generator SHALL use the Groq-hosted chat completion model `llama3-8b-8192` for all text generation requests.
5. IF the Prompt is empty or exceeds 10,000 characters, THEN THE Text_Generator SHALL raise a validation exception without calling the Groq API.
6. IF `GROQ_API_KEY` is absent or empty at startup, THEN THE Text_Generator SHALL raise a configuration exception before processing any generation request.

---

### Requirement 4: Marketing Image URL Generation

**User Story:** As a marketer, I want an AI-generated image URL from my prompt, so that I can include relevant visuals in my campaigns without needing image editing tools.

#### Acceptance Criteria

1. WHEN a Prompt of 1–500 characters is provided, THE Image_Generator SHALL construct a Pollinations.AI image URL by URL-encoding the Prompt and interpolating it into the template `https://image.pollinations.ai/prompt/{encoded_prompt}`.
2. THE Image_Generator SHALL return the constructed URL as a string without making a live HTTP request at generation time.
3. IF the Prompt is empty or contains only whitespace, THEN THE Image_Generator SHALL raise a validation exception with an error message indicating the prompt must be non-empty and non-whitespace.
4. IF the Prompt exceeds 500 characters, THEN THE Image_Generator SHALL raise a validation exception with an error message indicating the maximum allowed prompt length.

---

### Requirement 5: Campaign Scheduling

**User Story:** As a marketer, I want campaigns to be dispatched automatically at their scheduled time, so that I do not need to manually trigger each send.

#### Acceptance Criteria

1. WHEN the application starts, THE Scheduler SHALL begin polling the Campaign_Store at a regular interval (no longer than 60 seconds) for Campaigns with status `pending` whose `schedule_time` is less than or equal to the current UTC time.
2. WHEN a due Campaign is found, THE Scheduler SHALL immediately update its status to `processing` in the Campaign_Store before invoking the Text_Generator and Image_Generator for that Campaign's Prompt.
3. WHEN the Text_Generator and Image_Generator have returned results, THE Scheduler SHALL pass those results to the SMS_Simulator for dispatch.
4. WHEN the SMS_Simulator accepts the results without error, THE Scheduler SHALL update the Campaign's status to `sent` in the Campaign_Store.
5. IF text generation, image generation, or the SMS_Simulator raises an error, THEN THE Scheduler SHALL update the Campaign's status to `failed` in the Campaign_Store and log an ERROR entry that includes the `campaign_id` and the stage at which the failure occurred.
6. WHILE a Campaign has status `processing`, `sent`, or `failed`, THE Scheduler SHALL not pick it up for processing in any subsequent polling cycle.

---

### Requirement 6: SMS Simulation (Console Output)

**User Story:** As a developer, I want campaign messages printed to the console in a structured format, so that I can verify dispatch behavior without a real SMS gateway.

#### Acceptance Criteria

1. WHEN the SMS_Simulator is invoked for a Campaign send attempt, THE SMS_Simulator SHALL print exactly the following lines to standard output in order:
   - `Sending marketing message to {phone}`
   - `Campaign: {campaign_name}`
   - `Generated Text:`
   - `{generated_text}`
   - `Generated Image:`
   - `{generated_image_url}`
2. WHEN the SMS_Simulator is invoked, THE SMS_Simulator SHALL emit a log entry at INFO level that includes the `campaign_id`, `campaign_name`, and `phone` for the simulated send.
3. IF `generated_text` or `generated_image_url` is `None` or empty when the SMS_Simulator is invoked, THEN THE SMS_Simulator SHALL raise a ValueError before printing any output.

---

### Requirement 7: REST API — Campaign Management

**User Story:** As an API consumer, I want HTTP endpoints to create, list, and inspect campaigns, so that I can integrate the system with other tools or frontends.

#### Acceptance Criteria

1. THE API SHALL expose a `POST /campaigns` endpoint that accepts a JSON body with `campaign_name`, `prompt`, `phone`, and `schedule_time`, creates a Campaign, and returns the created Campaign record including its `campaign_id` and `status`.
2. THE API SHALL expose a `GET /campaigns` endpoint that returns an array of all Campaign records.
3. THE API SHALL expose a `GET /campaigns/{campaign_id}` endpoint that returns the Campaign record for the given `campaign_id`.
4. IF a `POST /campaigns` request contains invalid or missing fields, THEN THE API SHALL return HTTP 422 with a descriptive error body.
5. IF a `GET /campaigns/{campaign_id}` request references a non-existent `campaign_id`, THEN THE API SHALL return HTTP 404 with a descriptive error body.
6. THE API SHALL expose a `GET /health` endpoint that returns HTTP 200 with a JSON body `{"status": "ok"}`.

---

### Requirement 8: Logging

**User Story:** As a developer, I want structured application logs, so that I can trace execution and diagnose issues in production.

#### Acceptance Criteria

1. THE Logger SHALL emit log entries at the following levels: DEBUG, INFO, WARNING, and ERROR.
2. WHEN any component performs a significant action (campaign creation, text generation call, image URL construction, scheduler poll, dispatch, status update), THE Logger SHALL emit an INFO or DEBUG entry describing the action and its key parameters.
3. WHEN any component encounters an error condition, THE Logger SHALL emit an ERROR entry including the error message and the relevant `campaign_id` or Prompt where applicable.
4. THE Logger SHALL write all entries to both the console (stdout) and a rotating log file named `app.log` in the application root directory.
5. THE Logger SHALL include a timestamp, log level, and module name in every log entry.

---

### Requirement 9: Configuration and Environment

**User Story:** As a developer, I want all sensitive credentials and tunable parameters loaded from environment variables, so that the application is portable and secrets are not hard-coded.

#### Acceptance Criteria

1. THE System SHALL load `GROQ_API_KEY` from a `.env` file or environment variable at startup using `python-dotenv`.
2. IF `GROQ_API_KEY` is absent or empty at startup, THEN THE System SHALL log an ERROR and raise a configuration exception before accepting any requests.
3. THE System SHALL allow the SQLite database file path to be configured via an environment variable `DB_PATH`, defaulting to `campaigns.db` in the application root if not set.
4. THE System SHALL allow the Scheduler polling interval to be configured via an environment variable `SCHEDULER_INTERVAL_SECONDS`, defaulting to `30` if not set.

---

### Requirement 10: Code Quality and Project Structure

**User Story:** As a developer, I want a clean, well-organized codebase with clear module boundaries, so that the project is easy to maintain and extend.

#### Acceptance Criteria

1. THE System SHALL be implemented using object-oriented Python with distinct classes for each major component: `Campaign` (model), `CampaignStore` (persistence), `TextGenerator`, `ImageGenerator`, `Scheduler`, `SMSSimulator`, and the FastAPI application entrypoint.
2. THE System SHALL include a `requirements.txt` listing all dependencies with pinned versions.
3. THE System SHALL include a `README.md` with instructions to install dependencies, configure the `.env` file, and run the application.
4. IF an unhandled exception propagates to the API layer, THEN THE API SHALL return HTTP 500 with a generic error message and log the full traceback.
