"""
EXCEL SHEET RETRIEVAL FLOW - CHUNKS & SQL QUERIES

This document explains how Excel files are processed through chunks 
and SQL queries when you ask a question.

═══════════════════════════════════════════════════════════════════════════════
STEP 1: EXCEL FILE UPLOAD & CHUNKING
═══════════════════════════════════════════════════════════════════════════════

Upload: test_sales.xlsx
  ↓
Extracted Data (in index.py - process_excel function):
  ├─ Sheet: "Sales"
  ├─ Headers: ["Date", "Product", "Quantity", "Price", "Total"]
  ├─ Row 1: {Date: "2024-01-15", Product: "Laptop Computer", Qty: 5, Price: 999.99, Total: 4999.95}
  ├─ Row 2: {Date: "2024-01-16", Product: "Wireless Mouse", Qty: 12, Price: 29.99, Total: 359.88}
  └─ Row 3: {Date: "2024-01-17", Product: "USB-C Hub", Qty: 8, Price: 49.99, Total: 399.92}

CHUNKING STRATEGY (Each Row = 1 Chunk):
  ├─ Chunk 1: Row 1 data stored as Document
  ├─ Chunk 2: Row 2 data stored as Document  
  └─ Chunk 3: Row 3 data stored as Document
  
  Total Chunks: 3 (one chunk per data row)

STORAGE (in PostgreSQL):

  rag_documents table:
  ┌─────┬──────────┬────────┬──────────────────────────────┐
  │ id  │ file_id  │ type   │ content_json                 │
  ├─────┼──────────┼────────┼──────────────────────────────┤
  │ 1   │ abc123   │ xlsx   │ {Row 1 metadata + data}      │
  │ 2   │ abc123   │ xlsx   │ {Row 2 metadata + data}      │
  │ 3   │ abc123   │ xlsx   │ {Row 3 metadata + data}      │
  └─────┴──────────┴────────┴──────────────────────────────┘

  spreadsheet_rows table:
  ┌────┬──────────┬───────────┬──────────┬──────────────────────────────┐
  │ id │ file_id  │ sheet_name│ headers  │ row_data                     │
  ├────┼──────────┼───────────┼──────────┼──────────────────────────────┤
  │ 1  │ abc123   │ Sales     │ [headers]│ {Date: "2024-01-15", ...}    │
  │ 2  │ abc123   │ Sales     │ [headers]│ {Date: "2024-01-16", ...}    │
  │ 3  │ abc123   │ Sales     │ [headers]│ {Date: "2024-01-17", ...}    │
  └────┴──────────┴───────────┴──────────┴──────────────────────────────┘

═══════════════════════════════════════════════════════════════════════════════
STEP 2: QUESTION ASKED - "What was total revenue from Laptop sales?"
═══════════════════════════════════════════════════════════════════════════════

Q&A Request Flow (in app.py - answer_query function):
  
  1. Retrieve documents (chunks) from database
     └─ search_all_files() loads 3 chunks into memory
     └─ These chunks are detected as "structured_docs" (has row_data)
  
  2. Separate into types:
     ├─ text_docs: [] (empty, PDF text documents)
     └─ structured_docs: [chunk1, chunk2, chunk3] (Excel rows)
  
  3. Route to execute_sql_answer() function
     └─ This is the EXCEL-SPECIFIC path (NOT PDF path)

═══════════════════════════════════════════════════════════════════════════════
STEP 3: SQL QUERY GENERATION & EXECUTION
═══════════════════════════════════════════════════════════════════════════════

Inside execute_sql_answer() in app.py:

  A) BUILD CONTEXT FROM CHUNKS
     ─────────────────────────
     Input: 3 chunks (rows 1, 2, 3)
     
     Extract Data:
     {
       "all_rows": [
         {Date: "2024-01-15", Product: "Laptop Computer", Qty: 5, Price: 999.99, Total: 4999.95, source_file: "test_sales.xlsx"},
         {Date: "2024-01-16", Product: "Wireless Mouse", Qty: 12, Price: 29.99, Total: 359.88, source_file: "test_sales.xlsx"},
         {Date: "2024-01-17", Product: "USB-C Hub", Qty: 8, Price: 49.99, Total: 399.92, source_file: "test_sales.xlsx"}
       ],
       "headers": ["Date", "Price", "Product", "Qty", "Total", "source_file", "uploaded_by"]
     }

  B) CREATE IN-MEMORY SQLITE TABLE
     ──────────────────────────────
     CREATE TABLE spreadsheet (
       "Date" TEXT,
       "Price" TEXT,
       "Product" TEXT,
       "Quantity" TEXT,
       "Total" TEXT,
       "source_file" TEXT,
       "uploaded_by" TEXT
     );
     
     INSERT INTO spreadsheet VALUES ('2024-01-15', '999.99', 'Laptop Computer', '5', '4999.95', 'test_sales.xlsx', 'employee@test.com');
     INSERT INTO spreadsheet VALUES ('2024-01-16', '29.99', 'Wireless Mouse', '12', '359.88', 'test_sales.xlsx', 'employee@test.com');
     INSERT INTO spreadsheet VALUES ('2024-01-17', '49.99', 'USB-C Hub', '8', '399.92', 'test_sales.xlsx', 'employee@test.com');

  C) SEND TO GEMINI LLM WITH PROMPT
     ─────────────────────────────
     LLM Receives:
     {
       "schema": "Date, Price, Product, Quantity, Total, source_file, uploaded_by",
       "rows": [row1, row2, row3],
       "question": "What was total revenue from Laptop sales?"
     }
     
     Prompt Template (EXCEL_SQL_PROMPT):
     "You have a spreadsheet with the following schema: [schema]
      Sample rows: [rows]
      Question: [question]
      Generate a valid SQL SELECT query to answer this question."

  D) LLM GENERATES SQL QUERY
     ──────────────────────
     LLM Response:
     "SELECT Product, SUM(Total) as total_revenue 
      FROM spreadsheet 
      WHERE Product = 'Laptop Computer' 
      GROUP BY Product;"

  E) EXECUTE SQL AGAINST IN-MEMORY TABLE
     ────────────────────────────────────
     cursor.execute(sql_query)
     result = cursor.fetchall()
     
     Result:
     [
       {Product: "Laptop Computer", total_revenue: "4999.95"}
     ]

  F) RETURN ANSWER
     ────────────
     {
       "answer": "[{Product: 'Laptop Computer', total_revenue: '4999.95'}]",
       "sql": "SELECT Product, SUM(Total) as total_revenue FROM spreadsheet WHERE Product = 'Laptop Computer' GROUP BY Product;",
       "rows": [{Product: "Laptop Computer", total_revenue: "4999.95"}],
       "files_included": ["test_sales.xlsx"]
     }

═══════════════════════════════════════════════════════════════════════════════
STEP 4: FINAL RESPONSE TO USER
═══════════════════════════════════════════════════════════════════════════════

API Response (/customer/{customer_id}/ask):

{
  "query": "What was total revenue from Laptop sales?",
  "query_type": "structured",
  "answer": "[{Product: 'Laptop Computer', total_revenue: '4999.95'}]",
  "answer_type": "sql_result",
  "retrieved_chunks": 3,
  "sources": ["test_sales.xlsx"],
  "results": [{Product: "Laptop Computer", total_revenue: "4999.95"}],
  "structured_answer": {
    "sql": "SELECT Product, SUM(Total) as total_revenue FROM spreadsheet WHERE Product = 'Laptop Computer' GROUP BY Product;",
    "rows": [{Product: "Laptop Computer", total_revenue: "4999.95"}]
  }
}

═══════════════════════════════════════════════════════════════════════════════
KEY DIFFERENCES: EXCEL vs PDF
═══════════════════════════════════════════════════════════════════════════════

PDF RETRIEVAL:
├─ Process: Text extraction → Chunking (750 chars per chunk) → Vector embeddings
├─ Storage: Chunks stored as JSONB with metadata
├─ Retrieval: Semantic search (FAISS vector similarity)
├─ Answer Method: LLM extracts answer from document text (evidence-based)
└─ Use Case: "What is the price of Laptop?" → LLM finds and cites text

EXCEL RETRIEVAL:
├─ Process: Row extraction → Chunking (each row = 1 chunk) → Stored as JSONB
├─ Storage: Spreadsheet rows in rag_documents + spreadsheet_rows table
├─ Retrieval: LLM generates SQL query
├─ Execution: SQL runs against in-memory SQLite table (joins, aggregates, etc.)
├─ Answer Method: SQL result set (structured data)
└─ Use Case: "What was total revenue?" → LLM generates SUM() query, executes it

═══════════════════════════════════════════════════════════════════════════════
CHUNKS COUNT IN RESPONSES
═══════════════════════════════════════════════════════════════════════════════

Upload Response Shows Chunks:
{
  "file_id": "abc123def",
  "customer_id": 33,
  "status": "uploaded",
  "chunks": 3,              ← Excel file = 3 data rows = 3 chunks
  "file_type": "xlsx"
}

Q&A Response Shows Retrieved Chunks:
{
  "retrieved_chunks": 3,    ← All 3 rows were loaded for SQL execution
  "query_type": "structured",
  "answer_type": "sql_result",
  ...
}

═══════════════════════════════════════════════════════════════════════════════
SUMMARY
═══════════════════════════════════════════════════════════════════════════════

✅ Excel chunking: ROWS (each row = 1 chunk)
✅ SQL Execution: YES, LLM generates then backend executes
✅ Retrieved Chunks Count: Shown in response as "retrieved_chunks"
✅ Answer Source: From SQL result set (structured data), not LLM text extraction
✅ Chunks Used: All retrieved chunks loaded into in-memory SQLite table

The system combines:
1. Chunk-based retrieval (PostgreSQL storage)
2. SQL query generation (Gemini LLM)
3. In-memory SQL execution (SQLite)
4. Structured result return (JSON format)
"""
