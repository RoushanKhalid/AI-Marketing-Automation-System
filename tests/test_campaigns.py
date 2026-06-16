import sys
import os
import re
import asyncio
from datetime import datetime, timedelta
import unittest
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient
from pydantic import ValidationError

# Ensure the app folder is in the path
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from app.config import Config
# Set database path to in-memory for testing
Config.DB_PATH = ":memory:"

from app.models.campaign import CampaignCreate, CampaignRecord
from app.db.campaign_store import CampaignStore
from app.services.text_generator import TextGenerator
from app.services.image_generator import ImageGenerator
from app.services.sms_simulator import SMSSimulator
from app.services.scheduler import Scheduler
from app.api.ws_manager import WebSocketManager
from app.main import app


# ===========================================================================
# 1. Pydantic Models Validation Tests (Requirement 1 & 1.4 & 1.5)
# ===========================================================================

def test_campaign_create_valid():
    """Test CampaignCreate with valid input parameters."""
    valid_data = {
        "campaign_name": "Autumn Promotion",
        "prompt": "Offer 20% discount on all jackets",
        "phone": "+8801712345678",
        "schedule_time": "2026-10-15 14:30:00",
        "status": "pending"
    }
    model = CampaignCreate(**valid_data)
    assert model.campaign_name == "Autumn Promotion"
    assert model.prompt == "Offer 20% discount on all jackets"
    assert model.phone == "+8801712345678"
    assert model.status == "pending"
    assert isinstance(model.schedule_time, datetime)


def test_campaign_create_invalid_blank_fields():
    """Test that blank fields are rejected."""
    invalid_data = {
        "campaign_name": "   ",
        "prompt": "Offer discount",
        "phone": "+8801712345678",
        "schedule_time": "2026-10-15 14:30:00"
    }
    with pytest.raises(ValidationError) as exc_info:
        CampaignCreate(**invalid_data)
    assert "campaign_name must not be blank" in str(exc_info.value)


def test_campaign_create_invalid_phone_formats():
    """Test rejection of non-E.164 phone formats."""
    # Test phone too short (less than 7 digits)
    with pytest.raises(ValidationError):
        CampaignCreate(
            campaign_name="Test",
            prompt="Test prompt",
            phone="+12345",
            schedule_time="2026-10-15 14:30:00"
        )
    # Test phone missing plus sign
    with pytest.raises(ValidationError):
        CampaignCreate(
            campaign_name="Test",
            prompt="Test prompt",
            phone="8801712345678",
            schedule_time="2026-10-15 14:30:00"
        )
    # Test phone too long (more than 15 digits)
    with pytest.raises(ValidationError):
        CampaignCreate(
            campaign_name="Test",
            prompt="Test prompt",
            phone="+1234567890123456",
            schedule_time="2026-10-15 14:30:00"
        )


def test_campaign_create_invalid_date_format():
    """Test that schedule_time must be strictly in YYYY-MM-DD HH:MM:SS format."""
    # Test ISO format (should be rejected as per Requirement 1.4)
    with pytest.raises(ValidationError) as exc_info:
        CampaignCreate(
            campaign_name="Test",
            prompt="Test prompt",
            phone="+8801712345678",
            schedule_time="2026-10-15T14:30:00Z"
        )
    assert "schedule_time must be in the format 'YYYY-MM-DD HH:MM:SS'" in str(exc_info.value)

    # Test random date format
    with pytest.raises(ValidationError) as exc_info:
        CampaignCreate(
            campaign_name="Test",
            prompt="Test prompt",
            phone="+8801712345678",
            schedule_time="15/10/2026 14:30"
        )
    assert "schedule_time must be in the format 'YYYY-MM-DD HH:MM:SS'" in str(exc_info.value)


def test_campaign_create_invalid_status():
    """Test that status must be one of pending, processing, sent, failed."""
    with pytest.raises(ValidationError) as exc_info:
        CampaignCreate(
            campaign_name="Test",
            prompt="Test prompt",
            phone="+8801712345678",
            schedule_time="2026-10-15 14:30:00",
            status="invalid_status"
        )
    assert "Accepted values:" in str(exc_info.value)


# ===========================================================================
# 2. Campaign Store SQLite Persistence Tests (Requirement 2 & 2.9)
# ===========================================================================

@pytest.fixture
def store():
    """Initialize a CampaignStore with an in-memory SQLite database."""
    return CampaignStore(db_path=":memory:")


def test_store_create_and_get(store):
    """Test inserting a campaign and retrieving it by ID."""
    campaign = CampaignCreate(
        campaign_name="Store Test",
        prompt="Testing SQLite persistence layer",
        phone="+8801912345678",
        schedule_time="2026-06-20 18:00:00",
        status="pending"
    )
    record = store.create_campaign(campaign)
    assert record.campaign_id is not None
    assert record.status == "pending"

    retrieved = store.get_campaign(record.campaign_id)
    assert retrieved is not None
    assert retrieved.campaign_name == "Store Test"
    assert retrieved.prompt == "Testing SQLite persistence layer"
    assert retrieved.phone == "+8801912345678"
    assert retrieved.status == "pending"


def test_store_get_nonexistent(store):
    """Test that retrieving a non-existent campaign returns None."""
    assert store.get_campaign(9999) is None


def test_store_list_ordered(store):
    """Test listing campaigns is ordered by schedule_time ascending."""
    c1 = CampaignCreate(
        campaign_name="Later Campaign",
        prompt="Scheduled later",
        phone="+8801912345678",
        schedule_time="2026-06-20 18:00:00"
    )
    c2 = CampaignCreate(
        campaign_name="Earlier Campaign",
        prompt="Scheduled earlier",
        phone="+8801912345678",
        schedule_time="2026-06-20 12:00:00"
    )
    store.create_campaign(c1)
    store.create_campaign(c2)

    campaigns = store.list_campaigns()
    assert len(campaigns) == 2
    assert campaigns[0].campaign_name == "Earlier Campaign"
    assert campaigns[1].campaign_name == "Later Campaign"


def test_store_update_status(store):
    """Test updating status works and raises LookupError if ID not found."""
    campaign = CampaignCreate(
        campaign_name="Status Update Test",
        prompt="Checking update",
        phone="+8801912345678",
        schedule_time="2026-06-20 18:00:00"
    )
    record = store.create_campaign(campaign)
    store.update_status(record.campaign_id, "processing")
    
    updated = store.get_campaign(record.campaign_id)
    assert updated.status == "processing"

    with pytest.raises(LookupError):
        store.update_status(9999, "sent")


def test_store_update_dispatch_result(store):
    """Test updating dispatch results persists generated text and image URL."""
    campaign = CampaignCreate(
        campaign_name="Dispatch Result Test",
        prompt="Checking dispatch persistence",
        phone="+8801912345678",
        schedule_time="2026-06-20 18:00:00"
    )
    record = store.create_campaign(campaign)
    store.update_dispatch_result(record.campaign_id, "Generated marketing copy", "http://image.url")

    updated = store.get_campaign(record.campaign_id)
    assert updated.status == "sent"
    assert updated.generated_text == "Generated marketing copy"
    assert updated.image_url == "http://image.url"


def test_store_delete(store):
    """Test deleting a campaign."""
    campaign = CampaignCreate(
        campaign_name="Delete Test",
        prompt="Delete me",
        phone="+8801912345678",
        schedule_time="2026-06-20 18:00:00"
    )
    record = store.create_campaign(campaign)
    deleted = store.delete_campaign(record.campaign_id)
    assert deleted is True
    assert store.get_campaign(record.campaign_id) is None


def test_store_validation_guards(store):
    """Test that CampaignStore raises ValueError if an invalid campaign is passed."""
    # Missing name bypass
    class MalformedCampaign:
        campaign_name = ""
        prompt = "Testing validation"
        phone = "+8801912345678"
        schedule_time = datetime.now()
        status = "pending"

    with pytest.raises(ValueError) as exc:
        store.create_campaign(MalformedCampaign())
    assert "campaign_name" in str(exc.value)

    # Malformed E.164 phone bypass
    class MalformedPhoneCampaign:
        campaign_name = "Valid Name"
        prompt = "Testing validation"
        phone = "12345"
        schedule_time = datetime.now()
        status = "pending"

    with pytest.raises(ValueError) as exc:
        store.create_campaign(MalformedPhoneCampaign())
    assert "phone" in str(exc.value)


# ===========================================================================
# 3. Marketing Text Generation Tests (Requirement 3)
# ===========================================================================

@patch("app.services.text_generator.Groq")
def test_text_generator_valid(mock_groq_class):
    """Test successful text generation calling Groq with llama-3.1-8b-instant."""
    mock_client = MagicMock()
    mock_groq_class.return_value = mock_client
    
    # Setup mock chat completion response
    mock_message = MagicMock()
    mock_message.content = "Buy our shiny new widget now!"
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    generator = TextGenerator()
    result = generator.generate("Promote our new widget")
    
    assert result == "Buy our shiny new widget now!"
    # Verify the model specified in Requirement 3.4 is used
    mock_client.chat.completions.create.assert_called_once()
    kwargs = mock_client.chat.completions.create.call_args[1]
    assert kwargs["model"] == "llama-3.1-8b-instant"


def test_text_generator_invalid_prompt_lengths():
    """Test ValueError raised on empty prompt or prompt > 10,000 chars."""
    generator = TextGenerator()
    
    # Test empty prompt
    with pytest.raises(ValueError):
        generator.generate("")
        
    # Test prompt exceeding 10,000 characters
    long_prompt = "a" * 10001
    with pytest.raises(ValueError):
        generator.generate(long_prompt)


# ===========================================================================
# 4. Marketing Image URL Generation Tests (Requirement 4)
# ===========================================================================

def test_image_generator_valid():
    """Test image generator URL output and URL encoding."""
    generator = ImageGenerator()
    url = generator.generate("Cute puppies playing in autumn leaves")
    assert url == "https://image.pollinations.ai/prompt/Cute+puppies+playing+in+autumn+leaves"


def test_image_generator_invalid_prompts():
    """Test validation errors for empty, whitespace, or excessively long prompts."""
    generator = ImageGenerator()
    
    # Test empty prompt
    with pytest.raises(ValueError) as exc:
        generator.generate("")
    assert "non-empty" in str(exc.value)
    
    # Test whitespace prompt
    with pytest.raises(ValueError) as exc:
        generator.generate("   ")
    assert "non-empty" in str(exc.value)
    
    # Test prompt exceeding 500 characters
    long_prompt = "a" * 501
    with pytest.raises(ValueError) as exc:
        generator.generate(long_prompt)
    assert "exceed" in str(exc.value)


# ===========================================================================
# 5. SMS Simulator Tests (Requirement 6)
# ===========================================================================

def test_sms_simulator_console_output(capsys):
    """Test console output matches expected SMS format exactly."""
    simulator = SMSSimulator()
    campaign = CampaignRecord(
        campaign_id=1,
        campaign_name="Spring Campaign",
        prompt="Spring Sale",
        phone="+8801912345678",
        schedule_time=datetime.now(),
        status="processing"
    )
    
    simulator.send(campaign, "Buy flowers!", "https://image.url/flowers")
    
    captured = capsys.readouterr()
    expected_lines = [
        "Sending marketing message to +8801912345678",
        "Campaign: Spring Campaign",
        "Generated Text:",
        "Buy flowers!",
        "Generated Image:",
        "https://image.url/flowers"
    ]
    # Check that all lines are printed in order
    output_lines = captured.out.strip().splitlines()
    assert output_lines == expected_lines


def test_sms_simulator_invalid_inputs():
    """Test ValueError raised if generated text or image url is empty."""
    simulator = SMSSimulator()
    campaign = CampaignRecord(
        campaign_id=1,
        campaign_name="Spring Campaign",
        prompt="Spring Sale",
        phone="+8801912345678",
        schedule_time=datetime.now(),
        status="processing"
    )
    
    with pytest.raises(ValueError):
        simulator.send(campaign, "", "http://valid.url")
        
    with pytest.raises(ValueError):
        simulator.send(campaign, "Valid text", "")


# ===========================================================================
# 6. Campaign Scheduling & Workflow Tests (Requirement 5)
# ===========================================================================

def test_scheduler_workflow():
    """Test scheduler loop picks up pending due campaigns, updates states,
    and runs them through generator services successfully."""
    store = CampaignStore(db_path=":memory:")
    
    # Add a campaign scheduled in the past (due)
    due_campaign = CampaignCreate(
        campaign_name="Due Campaign",
        prompt="Send immediately",
        phone="+8801912345678",
        schedule_time=(datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    )
    record = store.create_campaign(due_campaign)

    # Add a campaign scheduled in the future (not due)
    future_campaign = CampaignCreate(
        campaign_name="Future Campaign",
        prompt="Send later",
        phone="+8801912345678",
        schedule_time=(datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    )
    store.create_campaign(future_campaign)

    # Set up mock services
    text_generator = MagicMock()
    text_generator.generate.return_value = "Generative copy"
    image_generator = MagicMock()
    image_generator.generate.return_value = "https://image.url"
    sms_simulator = MagicMock()

    scheduler = Scheduler(
        store=store,
        text_generator=text_generator,
        image_generator=image_generator,
        sms_simulator=sms_simulator,
        interval_seconds=1
    )

    # Force processing of due campaigns
    scheduler._process_due_campaigns()

    # Verify due campaign was dispatched
    text_generator.generate.assert_called_once_with("Send immediately")
    image_generator.generate.assert_called_once_with("Send immediately")
    sms_simulator.send.assert_called_once()
    
    # Verify DB states
    due_record = store.get_campaign(record.campaign_id)
    assert due_record.status == "sent"
    assert due_record.generated_text == "Generative copy"
    assert due_record.image_url == "https://image.url"

    # Future campaign should remain pending
    all_records = store.list_campaigns()
    future_record = [r for r in all_records if r.campaign_name == "Future Campaign"][0]
    assert future_record.status == "pending"


def test_scheduler_failure_handling():
    """Test scheduler updates status to failed and logs error on service exception."""
    store = CampaignStore(db_path=":memory:")
    
    due_campaign = CampaignCreate(
        campaign_name="Failure Test Campaign",
        prompt="Trigger failure",
        phone="+8801912345678",
        schedule_time=(datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    )
    record = store.create_campaign(due_campaign)

    # Service raises exception
    text_generator = MagicMock()
    text_generator.generate.side_effect = RuntimeError("Groq API Timeout")
    image_generator = MagicMock()
    sms_simulator = MagicMock()

    scheduler = Scheduler(
        store=store,
        text_generator=text_generator,
        image_generator=image_generator,
        sms_simulator=sms_simulator,
        interval_seconds=1
    )

    scheduler._process_due_campaigns()

    # Status should transition to 'failed'
    updated = store.get_campaign(record.campaign_id)
    assert updated.status == "failed"


# ===========================================================================
# 7. REST API Integration Tests (Requirement 7)
# ===========================================================================

@pytest.fixture
def client():
    """Test client for FastAPI app with a clean in-memory database."""
    # We patch CampaignStore inside the app state lifespan, or directly override state
    store = CampaignStore(db_path=":memory:")
    app.state.store = store
    
    # Mock WebSocketManager to avoid starting event loop task failures
    ws_manager = MagicMock()
    app.state.ws_manager = ws_manager
    
    # Mock services on main app state
    app.state.scheduler = MagicMock()

    with TestClient(app) as test_client:
        yield test_client


def test_api_health_check(client):
    """Test GET /health returns 200 and ok status."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_api_campaign_crud(client):
    """Test POST, GET, and GET by ID endpoints of campaigns API."""
    # 1. Create a campaign
    payload = {
        "campaign_name": "API Launch Campaign",
        "prompt": "Announce rest api launch",
        "phone": "+8801912345678",
        "schedule_time": "2026-06-25 10:00:00"
    }
    res = client.post("/campaigns", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["campaign_id"] is not None
    assert data["status"] == "pending"
    assert data["campaign_name"] == "API Launch Campaign"

    campaign_id = data["campaign_id"]

    # 2. Get the campaign by ID
    res = client.get(f"/campaigns/{campaign_id}")
    assert res.status_code == 200
    assert res.json()["campaign_name"] == "API Launch Campaign"

    # 3. List campaigns
    res = client.get("/campaigns")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["campaign_id"] == campaign_id


def test_api_get_campaign_nonexistent(client):
    """Test that GET by nonexistent ID returns 404."""
    res = client.get("/campaigns/9999")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_api_create_campaign_invalid(client):
    """Test that POST invalid payload returns 422 validation error."""
    # Invalid phone and missing prompt
    payload = {
        "campaign_name": "Invalid API Campaign",
        "phone": "01712",
        "schedule_time": "2026-06-25 10:00:00"
    }
    res = client.post("/campaigns", json=payload)
    assert res.status_code == 422
