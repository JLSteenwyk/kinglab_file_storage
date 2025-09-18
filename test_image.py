#!/usr/bin/env python3
import requests

# Test if the image endpoint works
try:
    response = requests.get('http://localhost:748/static/choanoflagellate.png')
    print(f"Status: {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type')}")
    print(f"Content Length: {len(response.content)} bytes")

    if response.status_code == 200:
        print("✅ Image endpoint is working!")
        # Save the received image to verify it's correct
        with open('test_received.png', 'wb') as f:
            f.write(response.content)
        print("Saved test image to test_received.png")
    else:
        print(f"❌ Failed: {response.text}")
except Exception as e:
    print(f"Error: {e}")
    print("Make sure the server is running on port 748")