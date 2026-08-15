#!/usr/bin/env python3
"""Simple Q&A test using existing files"""

import requests
import json

base = 'http://127.0.0.1:8002'

# Use customer_id from previous test (33)
customer_id = 33
org_password = 'org-secret-2025'

# Token from earlier test - use dummy token for this test
# Let's just test the endpoint exists and see the error
question = "What is the price of Laptop Computer?"

print(f"Testing Q&A endpoint with customer_id={customer_id}")
print(f"Question: {question}")
print("=" * 80)

try:
    response = requests.post(
        f'{base}/customer/{customer_id}/ask',
        data={
            'question': question,
            'organization_password': org_password
        },
        timeout=180
    )
    
    print(f"Status Code: {response.status_code}")
    print(f"Response Headers: {dict(response.headers)}")
    print(f"Response Body:\n{json.dumps(response.json(), indent=2) if response.headers.get('content-type') == 'application/json' else response.text}")
    
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
