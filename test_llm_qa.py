#!/usr/bin/env python3
"""
Test Q&A with LLM - Full end-to-end retrieval and LLM response
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
c.drawString(100, 640, 'Product 3: USB-C Hub')
c.drawString(120, 620, 'Price: $49.99')
c.save()
open('test_products.pdf', 'wb').write(pdf_buffer.getvalue())

# Create test Excel
wb = openpyxl.Workbook()
ws = wb.active
ws.title = 'Sales'
ws.append(['Date', 'Product', 'Quantity', 'Price', 'Total'])
ws.append(['2024-01-15', 'Laptop Computer', 5, 999.99, 4999.95])
ws.append(['2024-01-16', 'Wireless Mouse', 12, 29.99, 359.88])
ws.append(['2024-01-17', 'USB-C Hub', 8, 49.99, 399.92])
wb.save('test_sales.xlsx')

print('[TEST] Files created')
print('=' * 80)

# Owner register + login
owner_email = f'owner{int(time.time()*1000)}@test.com'
reg = requests.post(base + '/customer/register', data={'name': 'Owner', 'email': owner_email, 'password': 'ownerpass123', 'role': 'owner'}, timeout=30)
print(f'[1] REGISTER: {reg.status_code}')

login = requests.post(base + '/customer/login', data={'email': owner_email, 'password': 'ownerpass123'}, timeout=30)
print(f'[2] LOGIN: {login.status_code}')
owner_token = login.json()['token']
owner_headers = {'Authorization': f'Bearer {owner_token}'}

# Create org
org = requests.post(base + '/customer/create-customer', data={'name': 'TestOrgLLM', 'organization_password': 'org-secret-2025'}, headers=owner_headers, timeout=30)
print(f'[3] CREATE ORG: {org.status_code}')
customer_id = org.json()['customer_id']

# Create employee
emp_email = f'emp{int(time.time()*1000)}@test.com'
emp = requests.post(base + '/customer/create-user', data={'name': 'Employee', 'email': emp_email, 'password': 'emppass123', 'role': 'employee', 'customer_id': customer_id}, headers=owner_headers, timeout=30)
print(f'[4] CREATE EMPLOYEE: {emp.status_code}')

# Employee login
emp_login = requests.post(base + '/customer/login', data={'email': emp_email, 'password': 'emppass123'}, timeout=30)
print(f'[5] EMPLOYEE LOGIN: {emp_login.status_code}')
emp_token = emp_login.json()['token']
emp_headers = {'Authorization': f'Bearer {emp_token}'}

print()
print('UPLOADING FILES...')
print('=' * 80)

# Upload PDF
pdf_file_id = None
with open('test_products.pdf', 'rb') as f:
    pdf_res = requests.post(base + f'/customer/{customer_id}/upload', files={'file': ('test_products.pdf', f, 'application/pdf')}, data={'organization_password': 'org-secret-2025'}, headers=emp_headers, timeout=120)
    if pdf_res.status_code == 200:
        pdf_data = pdf_res.json()
        pdf_file_id = pdf_data.get('file_id')
        print(f'[6] PDF UPLOAD: {pdf_res.status_code}')
        print(f'    File ID: {pdf_file_id}')
        print(f'    Chunks: {pdf_data.get("chunks")}')
    else:
        print(f'[6] PDF UPLOAD FAILED: {pdf_res.status_code}')
        print(f'    Error: {pdf_res.text}')

# Upload Excel
excel_file_id = None
with open('test_sales.xlsx', 'rb') as f:
    xlsx_res = requests.post(base + f'/customer/{customer_id}/upload', files={'file': ('test_sales.xlsx', f, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}, data={'organization_password': 'org-secret-2025'}, headers=emp_headers, timeout=120)
    if xlsx_res.status_code == 200:
        excel_data = xlsx_res.json()
        excel_file_id = excel_data.get('file_id')
        print(f'[7] EXCEL UPLOAD: {xlsx_res.status_code}')
        print(f'    File ID: {excel_file_id}')
        print(f'    Chunks: {excel_data.get("chunks")}')
    else:
        print(f'[7] EXCEL UPLOAD FAILED: {xlsx_res.status_code}')
        print(f'    Error: {xlsx_res.text}')

print()
print('TESTING Q&A WITH LLM...')
print('=' * 80)

# Question 1: PDF Question
print('\n[8] QUESTION 1 - PDF Question: "What is the price of Laptop Computer?"')
print('-' * 80)
q1 = requests.post(
    base + f'/customer/{customer_id}/ask',
    data={
        'question': 'What is the price of Laptop Computer?',
        'organization_password': 'org-secret-2025'
    },
    headers=emp_headers,
    timeout=180
)

if q1.status_code == 200:
    resp = q1.json()
    print(f'Status: {q1.status_code} OK')
    print(f'Answer: {resp.get("answer", "NO ANSWER")}')
    print(f'Answer Type: {resp.get("answer_type", "N/A")}')
    print(f'Query Type: {resp.get("query_type", "N/A")}')
    print(f'Retrieved Chunks: {resp.get("retrieved_chunks", 0)}')
    print(f'Sources: {json.dumps(resp.get("sources", []), indent=2)}')
    if resp.get("file_answers"):
        print(f'File Answers: {json.dumps(resp.get("file_answers"), indent=2)}')
else:
    print(f'Status: {q1.status_code} ERROR')
    print(f'Error Response: {q1.text}')
    error_data = q1.json() if q1.headers.get('content-type') == 'application/json' else {}
    if 'RESOURCE_EXHAUSTED' in str(error_data) or '429' in str(q1.status_code):
        print('\n*** GEMINI API QUOTA EXHAUSTED ***')
        print('Please wait for quota reset or upgrade to paid plan at https://ai.google.dev')
    elif error_data.get('error'):
        print(f'Error Details: {error_data.get("error")}')

print()

# Question 2: Excel Question
print('\n[9] QUESTION 2 - EXCEL Question: "What was the total revenue from Laptop Computer sales?"')
print('-' * 80)
q2 = requests.post(
    base + f'/customer/{customer_id}/ask',
    data={
        'question': 'What was the total revenue from Laptop Computer sales?',
        'organization_password': 'org-secret-2025'
    },
    headers=emp_headers,
    timeout=180
)

if q2.status_code == 200:
    resp = q2.json()
    print(f'Status: {q2.status_code} OK')
    print(f'Answer: {resp.get("answer", "NO ANSWER")}')
    print(f'Answer Type: {resp.get("answer_type", "N/A")}')
    print(f'Query Type: {resp.get("query_type", "N/A")}')
    print(f'Retrieved Chunks: {resp.get("retrieved_chunks", 0)}')
    print(f'Sources: {json.dumps(resp.get("sources", []), indent=2)}')
    if resp.get("file_answers"):
        print(f'File Answers: {json.dumps(resp.get("file_answers"), indent=2)}')
    if resp.get("structured_answer"):
        print(f'Structured Answer: {resp.get("structured_answer")}')
else:
    print(f'Status: {q2.status_code} ERROR')
    print(f'Error Response: {q2.text}')
    error_data = q2.json() if q2.headers.get('content-type') == 'application/json' else {}
    if 'RESOURCE_EXHAUSTED' in str(error_data) or '429' in str(q2.status_code):
        print('\n*** GEMINI API QUOTA EXHAUSTED ***')
        print('Please wait for quota reset or upgrade to paid plan at https://ai.google.dev')
    elif error_data.get('error'):
        print(f'Error Details: {error_data.get("error")}')

print()
print('=' * 80)
print('[TEST] COMPLETE')
print('=' * 80)

# Clean up
import os
os.unlink('test_products.pdf')
os.unlink('test_sales.xlsx')
