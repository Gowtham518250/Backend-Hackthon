import io
import time

import openpyxl
import requests
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

BASE_URL = 'http://127.0.0.1:8001'


def create_sample_files():
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
    with open('verify_products.pdf', 'wb') as f:
        f.write(pdf_buffer.getvalue())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Sales'
    ws.append(['Date', 'Product', 'Quantity', 'Price', 'Total'])
    ws.append(['2024-01-15', 'Laptop Computer', 5, 999.99, 4999.95])
    ws.append(['2024-01-16', 'Wireless Mouse', 12, 29.99, 359.88])
    ws.append(['2024-01-17', 'USB-C Hub', 8, 49.99, 399.92])
    wb.save('verify_sales.xlsx')


def run_flow():
    create_sample_files()
    owner_email = f'owner{int(time.time()*1000)}@test.com'
    employee_email = f'employee{int(time.time()*1000)}@test.com'

    reg = requests.post(
        BASE_URL + '/customer/register',
        data={'name': 'Owner Test', 'email': owner_email, 'password': 'ownerpass123', 'role': 'owner'},
        timeout=30,
    )
    print('REGISTER', reg.status_code, reg.text)
    owner_token = requests.post(
        BASE_URL + '/customer/login',
        data={'email': owner_email, 'password': 'ownerpass123'},
        timeout=30,
    ).json()['token']
    owner_headers = {'Authorization': f'Bearer {owner_token}'}

    org = requests.post(
        BASE_URL + '/customer/create-customer',
        data={'name': 'OrgA', 'organization_password': 'org-secret-2025'},
        headers=owner_headers,
        timeout=30,
    )
    print('ORG', org.status_code, org.text)
    customer_id = org.json()['customer_id']

    create_emp = requests.post(
        BASE_URL + '/customer/create-user',
        data={'name': 'Emp', 'email': employee_email, 'password': 'emppass123', 'role': 'employee', 'customer_id': customer_id},
        headers=owner_headers,
        timeout=30,
    )
    print('CREATE_EMP', create_emp.status_code, create_emp.text)

    emp_token = requests.post(
        BASE_URL + '/customer/login',
        data={'email': employee_email, 'password': 'emppass123'},
        timeout=30,
    ).json()['token']
    emp_headers = {'Authorization': f'Bearer {emp_token}'}

    with open('verify_products.pdf', 'rb') as f:
        pdf_resp = requests.post(
            BASE_URL + f'/customer/{customer_id}/upload',
            files={'file': ('verify_products.pdf', f, 'application/pdf')},
            data={'organization_password': 'org-secret-2025'},
            headers=emp_headers,
            timeout=120,
        )
        print('PDF_UPLOAD', pdf_resp.status_code, pdf_resp.text)

    with open('verify_sales.xlsx', 'rb') as f:
        xlsx_resp = requests.post(
            BASE_URL + f'/customer/{customer_id}/upload',
            files={'file': ('verify_sales.xlsx', f, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
            data={'organization_password': 'org-secret-2025'},
            headers=emp_headers,
            timeout=120,
        )
        print('XLSX_UPLOAD', xlsx_resp.status_code, xlsx_resp.text)

    ask = requests.post(
        BASE_URL + f'/customer/{customer_id}/ask',
        data={'question': 'What is the price of the Laptop Computer and what was the total for Laptop Computer sales?', 'organization_password': 'org-secret-2025'},
        headers=emp_headers,
        timeout=120,
    )
    print('ASK', ask.status_code, ask.text)


if __name__ == '__main__':
    run_flow()
