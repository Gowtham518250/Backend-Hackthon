import os
import hashlib
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import openpyxl

from index import register_file
from app import answer_query

pdf_path = 'tmp_retrieval_fix.pdf'
excel_path = 'tmp_retrieval_fix.xlsx'

pdf = canvas.Canvas(pdf_path, pagesize=letter)
pdf.setFont('Helvetica', 12)
pdf.drawString(100, 750, 'Sample Product Catalog')
pdf.drawString(100, 720, 'Product 1: Laptop Computer')
pdf.drawString(120, 700, 'Price: $999.99')
pdf.save()

wb = openpyxl.Workbook()
ws = wb.active
ws.title = 'Sales'
ws.append(['Date', 'Product', 'Quantity', 'Price', 'Total'])
ws.append(['2024-01-15', 'Laptop Computer', 5, 999.99, 4999.95])
wb.save(excel_path)

for path, name in [(pdf_path, 'tmp_retrieval_fix.pdf'), (excel_path, 'tmp_retrieval_fix.xlsx')]:
    with open(path, 'rb') as f:
        file_id = hashlib.sha256(f.read()).hexdigest()[:32]
    try:
        register_file(path, file_id, name)
    except Exception as exc:
        print('REGISTER_ERROR', name, exc)

result = answer_query(
    'What is the price of the Laptop Computer and what was the total for Laptop Computer sales?',
    None,
    8,
)
print(result)
assert '999.99' in str(result['answer']) or '4999.95' in str(result['answer'])
assert 'Answer not found' not in str(result['answer'])
