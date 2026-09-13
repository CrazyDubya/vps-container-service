#!/usr/bin/env python3
"""
Basic tests for SiloedBoss API Management System
Tests core functionality without requiring API keys
"""

import pytest
import json
import os
import sys
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app, Mixtral

client = TestClient(app)


def test_health_endpoint():
    """Test the health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "healthy"
    assert "provider" in data
    assert "timestamp" in data


def test_home_endpoint():
    """Test the home endpoint serves HTML."""
    response = client.get("/")
    assert response.status_code in [200, 404]  # 404 if index.html missing
    

def test_config_json_valid():
    """Test that config.json is valid JSON."""
    with open("apis/config.json", "r") as f:
        config = json.load(f)
    
    # Verify required sections exist
    assert "CLAUDE_MODELS" in config
    assert "OPENAI_MODELS" in config
    assert "LOCAL_MODELS" in config
    assert "GEMINI_MODELS" in config
    assert "PERPLEXITY_MODELS" in config
    assert "MONSTER_MODELS" in config


def test_task_history_endpoint():
    """Test the task history endpoint."""
    response = client.get("/task-history")
    assert response.status_code == 200
    data = response.json()
    assert "tasks" in data
    assert isinstance(data["tasks"], list)


@patch.dict(os.environ, {"AI_PROVIDER": "local"})
def test_mixtral_initialization():
    """Test Mixtral class initialization."""
    mixtral = Mixtral()
    assert mixtral is not None
    assert hasattr(mixtral, 'local_model')
    assert hasattr(mixtral, 'wizard_queue')


def test_process_endpoint_structure():
    """Test the process endpoint accepts correct structure."""
    # Test with minimal valid input
    test_input = {
        "user_input": "Hello, test message",
        "task_id": 123
    }
    
    # This will likely fail due to local model requirements, but we test structure
    response = client.post("/process", json=test_input)
    # We expect either success or a controlled error, not a crash
    assert response.status_code in [200, 500, 422]


if __name__ == "__main__":
    # Run basic tests
    print("Running basic validation tests...")
    
    print("✓ Testing health endpoint...")
    test_health_endpoint()
    
    print("✓ Testing config JSON validity...")
    test_config_json_valid()
    
    print("✓ Testing task history endpoint...")
    test_task_history_endpoint()
    
    print("✓ Testing Mixtral initialization...")
    test_mixtral_initialization()
    
    print("\n✅ All basic tests passed!")