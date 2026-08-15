#!/usr/bin/env python3
"""
Final end-to-end test: PDF + Excel upload and Q&A
"""

import requests
import io
import time
import openpyxl
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
print('=' * 60)

# Owner register + login
owner_email = f'owner{int(time.time()*1000)}@test.com'
reg = requests.post(base + '/customer/register', data={'name': 'Owner', 'email': owner_email, 'password': 'ownerpass123', 'role': 'owner'}, timeout=30)
print(f'[1] REGISTER: {reg.status_code}')

login = requests.post(base + '/customer/login', data={'email': owner_email, 'password': 'ownerpass123'}, timeout=30)
print(f'[2] LOGIN: {login.status_code}')
owner_token = login.json()['token']
owner_headers = {'Authorization': f'Bearer {owner_token}'}

# Create org with password
org = requests.post(base + '/customer/create-customer', data={'name': 'TestOrg', 'organization_password': 'org-secret-2025'}, headers=owner_headers, timeout=30)
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
print('=' * 60)

# Upload PDF
with open('test_products.pdf', 'rb') as f:
    pdf_res = requests.post(base + f'/customer/{customer_id}/upload', files={'file': ('test_products.pdf', f, 'application/pdf')}, data={'organization_password': 'org-secret-2025'}, headers=emp_headers, timeout=120)
    print(f'[6] PDF UPLOAD: {pdf_res.status_code}')
    if pdf_res.status_code == 200:
        print(f'    File ID: {pdf_res.json().get("file_id")}')
        print(f'    Chunks: {pdf_res.json().get("chunks")}')

# Upload Excel
with open('test_sales.xlsx', 'rb') as f:
    xlsx_res = requests.post(base + f'/customer/{customer_id}/upload', files={'file': ('test_sales.xlsx', f, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}, data={'organization_password': 'org-secret-2025'}, headers=emp_headers, timeout=120)
    print(f'[7] EXCEL UPLOAD: {xlsx_res.status_code}')
    if xlsx_res.status_code == 200:
        print(f'    File ID: {xlsx_res.json().get("file_id")}')
        print(f'    Chunks: {xlsx_res.json().get("chunks")}')

print()
print('ASKING QUESTIONS...')
print('=' * 60)

# Ask question about PDF
q1 = requests.post(base + f'/customer/{customer_id}/ask', data={'question': 'What is the price of Laptop Computer?', 'organization_password': 'org-secret-2025'}, headers=emp_headers, timeout=120)
print(f'[8] QUESTION 1 (PDF): {q1.status_code}')
if q1.status_code == 200:
    resp = q1.json()
    print(f'    Answer: {resp.get("answer", "NO ANSWER")}')
    print(f'    Retrieved chunks: {resp.get("retrieved_chunks", 0)}')
    print(f'    Sources: {resp.get("sources", [])}')
    if resp.get("file_answers"):
        print(f'    File Answers: {resp.get("file_answers")}')
else:
    print(f'    ERROR: {q1.text}')

print()

# Ask question about Excel/Sales
q2 = requests.post(base + f'/customer/{customer_id}/ask', data={'question': 'What was the total revenue from Laptop Computer sales?', 'organization_password': 'org-secret-2025'}, headers=emp_headers, timeout=120)
print(f'[9] QUESTION 2 (EXCEL): {q2.status_code}')
if q2.status_code == 200:
    resp = q2.json()
    print(f'    Answer: {resp.get("answer", "NO ANSWER")}')
    print(f'    Retrieved chunks: {resp.get("retrieved_chunks", 0)}')
    print(f'    Sources: {resp.get("sources", [])}')
    if resp.get("file_answers"):
        print(f'    File Answers: {resp.get("file_answers")}')
else:
    print(f'    ERROR: {q2.text}')

print()
print('=' * 60)
print('[TEST] COMPLETE')
