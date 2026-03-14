#!/usr/bin/env python3
"""
Test script — Verify gpt-oss:20b-cloud access via Ollama Cloud
"""

import requests
import json
from settings import OLLAMA_CLOUD_API_KEY, OLLAMA_CLOUD_HOST, CLASSIFICATION_LLM

print(f"Testing gpt-oss:20b-cloud via Ollama Cloud")
print(f"  Host: {OLLAMA_CLOUD_HOST}")
print(f"  Model: {CLASSIFICATION_LLM}")
print(f"  API Key: {'✓' if OLLAMA_CLOUD_API_KEY else '✗ NOT SET'}")
print()

if not OLLAMA_CLOUD_API_KEY:
    print("❌ OLLAMA_CLOUD_API_KEY not set in .env.local")
    exit(1)

# Test 1: Simple ping
print("Test 1: Checking endpoint connectivity…")
try:
    r = requests.get(f"{OLLAMA_CLOUD_HOST}/api/tags", timeout=5)
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        models = r.json().get("models", [])
        print(f"  ✓ Connected. Available models: {len(models)}")
        for m in models[:3]:
            print(f"    - {m.get('name', 'unknown')}")
    else:
        print(f"  ✗ Unexpected status. Response: {r.text[:200]}")
except Exception as e:
    print(f"  ✗ Connection failed: {e}")
    exit(1)

print()

# Test 2: Simple chat call
print("Test 2: Simple chat call to verify API…")
try:
    payload = {
        "model": CLASSIFICATION_LLM,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Say 'test ok' exactly"},
        ],
        "stream": False,
    }

    print(f"  Calling {CLASSIFICATION_LLM}…")
    print(f"  Payload: {json.dumps(payload, indent=2)}")
    print()

    r = requests.post(
        f"{OLLAMA_CLOUD_HOST}/api/chat",
        headers={
            "Authorization": f"Bearer {OLLAMA_CLOUD_API_KEY}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=120,
    )

    print(f"  Status: {r.status_code}")
    print(f"  Response time: ~{r.elapsed.total_seconds():.1f}s")
    print()

    if r.status_code != 200:
        print(f"  ✗ Unexpected status")
        print(f"  Response: {r.text[:500]}")
        exit(1)

    data = r.json()
    print(f"  Response keys: {list(data.keys())}")

    if "message" in data:
        content = data["message"].get("content", "")
        print(f"  ✓ Message content: {content[:100]}")
    elif "response" in data:
        content = data.get("response", "")
        print(f"  ✓ Response content: {content[:100]}")
    else:
        print(f"  ? Unexpected response format: {json.dumps(data, indent=2)[:500]}")

    print()
    print("✅ Test passed! gpt-oss:20b-cloud is accessible.")

except requests.Timeout:
    print(f"  ✗ Timeout after 120s. Model may be slow to start or unavailable.")
except Exception as e:
    print(f"  ✗ Request failed: {e}")
    exit(1)
