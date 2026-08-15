#!/usr/bin/env python3
"""
Test script to debug the multi-role backend with PostgreSQL.
"""

import requests
import json
import time

BASE_URL = "http://127.0.0.1:8000"

def test_e2e():
    """Run full E2E test."""
    
    # Use unique email based on timestamp
    unique_id = int(time.time() * 1000) % 1000000
    test_email = f"test{unique_id}@deepfind.com"
    
    # Step 1: Register
    print("1. Registering owner...")
    resp = requests.post(
        f"{BASE_URL}/customer/register",
        data={
            "name": "Charlie Owner",
            "email": test_email,
            "password": "testpass123",
            "role": "owner"
        }
    )
    print(f"   Status: {resp.status_code}")
    owner = resp.json()
    print(f"   Owner ID: {owner.get('id')}")
    
    # Step 2: Login
    print("\n2. Logging in...")
    resp = requests.post(
        f"{BASE_URL}/customer/login",
        data={
            "email": "charlie@deepfind.com",
            "password": "testpass123"
        }
    )
    print(f"   Status: {resp.status_code}")
    login_resp = resp.json()
    token = login_resp.get("token")
    print(f"   Token (first 30 chars): {token[:30]}...")
    
    # Step 3: Create customer
    print("\n3. Creating customer...")
    headers = {"Authorization": f"Bearer {token}"}
    print(f"   Headers: {headers}")
    resp = requests.post(
        f"{BASE_URL}/customer/create-customer",
        data={"name": "TestCorp"},
        headers=headers
    )
    print(f"   Status: {resp.status_code}")
    print(f"   Response: {resp.text}")
    
    if resp.status_code == 200:
        customer = resp.json()
        print(f"   ✓ Customer ID: {customer.get('customer_id')}")
    else:
        print(f"   ✗ Failed")

if __name__ == "__main__":
    test_e2e()
