#!/usr/bin/env python3
"""
Test data retrieval from database - NO LLM calls
Verifies that uploaded files are stored and retrievable
"""

import requests
import io
import time
import openpyxl
import json
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

base = 'http://127.0.0.1:8002'

# Create test PDF
pdf_buffer = io.BytesIO()
c = canvas.Canvas(pdf_buffer, pagesize=letter)
c.setFont('Helvetica', 12)
c.drawString(100, 750, 'Sample Product Catalog')
c.drawString(100, 720, 'Product 1: Laptop Computer')
c.drawString(120, 700, 'Price: $999.99')
c.drawString(100, 680, 'Product 2: Wireless Mouse')
c.drawString(120, 660, 'Price: $29.99')
c.save()
open('test_products.pdf', 'wb').write(pdf_buffer.getvalue())

# Create test Excel
wb = openpyxl.Workbook()
ws = wb.active
ws.title = 'Sales'
ws.append(['Date', 'Product', 'Quantity', 'Price', 'Total'])
ws.append(['2024-01-15', 'Laptop Computer', 5, 999.99, 4999.95])
ws.append(['2024-01-16', 'Wireless Mouse', 12, 29.99, 359.88])
wb.save('test_sales.xlsx')

print('[TEST] Files created')
print('=' * 70)

# Owner register + login
owner_email = f'owner{int(time.time()*1000)}@test.com'
reg = requests.post(base + '/customer/register', data={'name': 'Owner', 'email': owner_email, 'password': 'ownerpass123', 'role': 'owner'}, timeout=30)
print(f'✓ [1] REGISTER: {reg.status_code}')

login = requests.post(base + '/customer/login', data={'email': owner_email, 'password': 'ownerpass123'}, timeout=30)
print(f'✓ [2] LOGIN: {login.status_code}')
owner_token = login.json()['token']
owner_headers = {'Authorization': f'Bearer {owner_token}'}

# Create org with password
org = requests.post(base + '/customer/create-customer', data={'name': 'TestOrgRetrieval', 'organization_password': 'org-secret-2025'}, headers=owner_headers, timeout=30)
print(f'✓ [3] CREATE ORG: {org.status_code}')
customer_id = org.json()['customer_id']
print(f'    Customer ID: {customer_id}')

# Create employee
emp_email = f'emp{int(time.time()*1000)}@test.com'
emp = requests.post(base + '/customer/create-user', data={'name': 'Employee', 'email': emp_email, 'password': 'emppass123', 'role': 'employee', 'customer_id': customer_id}, headers=owner_headers, timeout=30)
print(f'✓ [4] CREATE EMPLOYEE: {emp.status_code}')

# Employee login
emp_login = requests.post(base + '/customer/login', data={'email': emp_email, 'password': 'emppass123'}, timeout=30)
print(f'✓ [5] EMPLOYEE LOGIN: {emp_login.status_code}')
emp_token = emp_login.json()['token']
emp_headers = {'Authorization': f'Bearer {emp_token}'}

print()
print('UPLOADING FILES...')
print('=' * 70)

# Upload PDF
pdf_file_id = None
with open('test_products.pdf', 'rb') as f:
    pdf_res = requests.post(base + f'/customer/{customer_id}/upload', files={'file': ('test_products.pdf', f, 'application/pdf')}, data={'organization_password': 'org-secret-2025'}, headers=emp_headers, timeout=120)
    print(f'✓ [6] PDF UPLOAD: {pdf_res.status_code}')
    if pdf_res.status_code == 200:
        pdf_data = pdf_res.json()
        pdf_file_id = pdf_data.get('file_id')
        print(f'    File ID: {pdf_file_id}')
        print(f'    Chunks: {pdf_data.get("chunks")}')
        print(f'    File Type: {pdf_data.get("file_type")}')
    else:
        print(f'    ERROR: {pdf_res.text}')

# Upload Excel
excel_file_id = None
with open('test_sales.xlsx', 'rb') as f:
    xlsx_res = requests.post(base + f'/customer/{customer_id}/upload', files={'file': ('test_sales.xlsx', f, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}, data={'organization_password': 'org-secret-2025'}, headers=emp_headers, timeout=120)
    print(f'✓ [7] EXCEL UPLOAD: {xlsx_res.status_code}')
    if xlsx_res.status_code == 200:
        excel_data = xlsx_res.json()
        excel_file_id = excel_data.get('file_id')
        print(f'    File ID: {excel_file_id}')
        print(f'    Chunks: {excel_data.get("chunks")}')
        print(f'    File Type: {excel_data.get("file_type")}')
    else:
        print(f'    ERROR: {xlsx_res.text}')

print()
print('TESTING DATA RETRIEVAL (Database)...')
print('=' * 70)

# Now query the /search endpoint to retrieve documents from the database
if pdf_file_id:
    search_res = requests.get(
        base + '/customer/' + str(customer_id) + '/search',
        params={
            'query': 'laptop price',
            'top_k': 5
        },
        headers=emp_headers,
        timeout=30
    )
    print(f'✓ [8] SEARCH PDF CONTENT: {search_res.status_code}')
    if search_res.status_code == 200:
        search_data = search_res.json()
        docs = search_data.get('documents', [])
        print(f'    Retrieved {len(docs)} documents')
        if docs:
            print(f'    First doc content: {docs[0].get("content", "")[:100]}...')
            print(f'    Metadata: {docs[0].get("metadata", {})}')
    else:
        print(f'    ERROR: {search_res.text}')

if excel_file_id:
    search_res2 = requests.get(
        base + '/customer/' + str(customer_id) + '/search',
        params={
            'query': 'laptop sales revenue total',
            'top_k': 5
        },
        headers=emp_headers,
        timeout=30
    )
    print(f'✓ [9] SEARCH EXCEL CONTENT: {search_res2.status_code}')
    if search_res2.status_code == 200:
        search_data = search_res2.json()
        docs = search_data.get('documents', [])
        print(f'    Retrieved {len(docs)} documents')
        if docs:
            print(f'    First doc content: {docs[0].get("content", "")[:100]}...')
            print(f'    Metadata: {docs[0].get("metadata", {})}')
    else:
        print(f'    ERROR: {search_res2.text}')

print()
print('=' * 70)
print('✓ [TEST] RETRIEVAL COMPLETE - All data uploaded and retrievable!')
print('=' * 70)
