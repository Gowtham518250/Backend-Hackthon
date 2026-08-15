#!/usr/bin/env python3
"""
Direct database test - Shows uploaded files without LLM calls
Queries PostgreSQL directly to verify RAG documents are stored
"""

import requests
import io
import time
import openpyxl
import json
import psycopg2
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

base = 'http://127.0.0.1:8002'

# Get database URL from env
import os
db_url = os.getenv('DATABASE_URL', 'postgresql://hackthon_lbm8_user:rwwf6kXOZINEgoPLNCiyElpGAdWoyEQo@dpg-da05k5tg1s2s73ccuj60-a.oregon-postgres.render.com/hackthon_lbm8')

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
print(f'[1] REGISTER: {reg.status_code}')

login = requests.post(base + '/customer/login', data={'email': owner_email, 'password': 'ownerpass123'}, timeout=30)
print(f'[2] LOGIN: {login.status_code}')
owner_token = login.json()['token']
owner_headers = {'Authorization': f'Bearer {owner_token}'}

# Create org with password
org = requests.post(base + '/customer/create-customer', data={'name': 'TestOrgDB', 'organization_password': 'org-secret-2025'}, headers=owner_headers, timeout=30)
print(f'[3] CREATE ORG: {org.status_code}')
customer_id = org.json()['customer_id']
print(f'    Customer ID: {customer_id}')

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
print('=' * 70)

# Upload PDF
pdf_file_id = None
with open('test_products.pdf', 'rb') as f:
    pdf_res = requests.post(base + f'/customer/{customer_id}/upload', files={'file': ('test_products.pdf', f, 'application/pdf')}, data={'organization_password': 'org-secret-2025'}, headers=emp_headers, timeout=120)
    print(f'[6] PDF UPLOAD: {pdf_res.status_code}')
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
    print(f'[7] EXCEL UPLOAD: {xlsx_res.status_code}')
    if xlsx_res.status_code == 200:
        excel_data = xlsx_res.json()
        excel_file_id = excel_data.get('file_id')
        print(f'    File ID: {excel_file_id}')
        print(f'    Chunks: {excel_data.get("chunks")}')
        print(f'    File Type: {excel_data.get("file_type")}')
    else:
        print(f'    ERROR: {xlsx_res.text}')

print()
print('QUERYING DATABASE DIRECTLY...')
print('=' * 70)

try:
    # Connect to PostgreSQL
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    if pdf_file_id:
        print(f'[8] PDF DOCUMENT CHUNKS (file_id: {pdf_file_id}):')
        cur.execute(
            'SELECT id, file_name, file_type, content_json FROM rag_documents WHERE file_id = %s LIMIT 5',
            (pdf_file_id,)
        )
        docs = cur.fetchall()
        print(f'    Found {len(docs)} chunks in database')
        for i, (doc_id, file_name, file_type, content_json) in enumerate(docs, 1):
            print(f'\n    ===== CHUNK {i} =====')
            print(f'    File: {file_name} ({file_type})')
            print(f'    Full Retrieved Content:')
            print(f'    {json.dumps(content_json, indent=6)}')
        print()
    
    if excel_file_id:
        print(f'[9] EXCEL SPREADSHEET ROWS (file_id: {excel_file_id}):')
        cur.execute(
            'SELECT id, sheet_name, headers, row_data FROM spreadsheet_rows WHERE file_id = %s LIMIT 5',
            (excel_file_id,)
        )
        rows = cur.fetchall()
        print(f'    Found {len(rows)} rows in database')
        for i, (row_id, sheet_name, headers, row_data) in enumerate(rows, 1):
            print(f'\n    ===== ROW {i} =====')
            print(f'    Sheet: {sheet_name}')
            print(f'    Headers: {json.dumps(headers, indent=6)}')
            print(f'    Row Data: {json.dumps(row_data, indent=6)}')
        print()
    
    # Summary stats
    print('[10] DATABASE SUMMARY:')
    cur.execute(f'SELECT COUNT(*) FROM rag_documents WHERE file_id IN (%s, %s)', (pdf_file_id or '', excel_file_id or ''))
    total_chunks = cur.fetchone()[0]
    print(f'    Total RAG document chunks: {total_chunks}')
    
    cur.execute(f'SELECT COUNT(*) FROM spreadsheet_rows WHERE file_id IN (%s, %s)', (pdf_file_id or '', excel_file_id or ''))
    total_rows = cur.fetchone()[0]
    print(f'    Total spreadsheet rows: {total_rows}')
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f'    ERROR connecting to database: {e}')

print()
print('=' * 70)
print('[TEST] COMPLETE - All files uploaded and stored in PostgreSQL!')
print('=' * 70)

# Clean up test files
Path('test_products.pdf').unlink(missing_ok=True)
Path('test_sales.xlsx').unlink(missing_ok=True)
