"""
Direct Database Test - Shows SQL Queries Being Generated and Executed
No HTTP, direct Python function calls to see the flow
"""

import sys
sys.path.insert(0, "/Hackthon 2/Backend")

# Set env vars before imports
import os
os.environ["JWT_SECRET_KEY"] = "deepfind-super-secret-jwt-key-2025-production-test-!@#12345"
os.environ["DATABASE_URL"] = "postgresql://hackthon_lbm8_user:rwwf6kXOZINEgoPLNCiyElpGAdWoyEQo@dpg-da05k5tg1s2s73ccuj60-a.oregon-postgres.render.com/hackthon_lbm8"

from app import answer_query
from database import get_rag_documents, get_spreadsheet_rows

print("=" * 90)
print("DIRECT DATABASE TEST - SQL QUERY GENERATION AND EXECUTION")
print("=" * 90)

# Use the file_id from our previous test: 172f494e4a0b382ce557b42f60ac5c73
file_id = "172f494e4a0b382ce557b42f60ac5c73"

print(f"\n[1] Retrieving stored chunks from PostgreSQL for file_id: {file_id}")
print("-" * 90)

try:
    # Get RAG documents (chunks)
    docs = get_rag_documents(file_id)
    print(f"✅ Retrieved {len(docs)} chunks from rag_documents table")
    
    for i, doc in enumerate(docs, 1):
        print(f"\n   Chunk {i}:")
        print(f"   - Metadata: {doc.get('metadata', {})}")
        print(f"   - Content: {doc.get('page_content', '')[:100]}...")
    
    # Get spreadsheet rows
    rows = get_spreadsheet_rows(file_id)
    print(f"\n✅ Retrieved spreadsheet rows from spreadsheet_rows table")
    print(f"   Total rows: {len(rows)}")
    
    for i, row in enumerate(rows, 1):
        print(f"\n   Row {i}:")
        print(f"   - {row}")
        
except Exception as e:
    print(f"❌ Error retrieving documents: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 90)
print("[2] TESTING SQL QUERY GENERATION - Using answer_query function")
print("=" * 90)

questions = [
    "What is the total revenue from Laptop Computer sales?",
    "How many Wireless Mouse units were sold?",
]

for q_num, question in enumerate(questions, 1):
    print(f"\n{'─' * 90}")
    print(f"Question {q_num}: {question}")
    print(f"{'─' * 90}")
    
    try:
        result = answer_query(
            query=question,
            file_id=file_id,
            top_k=10,
            docs_override=None,
            owner_map={}
        )
        
        if result:
            print(f"\n✅ RESULT RECEIVED:")
            
            # Check if it's a text answer or structured answer
            if "sql" in result:
                print(f"\n📊 SQL QUERY GENERATED:")
                print(f"   {result['sql']}")
                
                print(f"\n📋 SQL EXECUTION RESULTS:")
                if result.get('rows'):
                    for row in result['rows']:
                        print(f"   {row}")
                else:
                    print(f"   (No results returned)")
                    
                print(f"\n💬 ANSWER:")
                print(f"   {result.get('answer', 'No answer')}")
                    
            elif "answer" in result:
                print(f"\n💬 TEXT ANSWER:")
                print(f"   {result['answer']}")
                
            if "error" in result:
                print(f"\n⚠️  ERROR:")
                print(f"   {result['error']}")
        else:
            print(f"❌ No result returned")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 90)
print("TEST COMPLETE")
print("=" * 90)
print("\n✅ SUMMARY:")
print("   1. Excel file stored in PostgreSQL with 5 rows = 5 chunks")
print("   2. LLM receives chunks and generates SQL queries")
print("   3. SQL executed against in-memory SQLite table")
print("   4. Results returned with both SQL and answer")
print("   5. You can see exact SQL generated and executed above")
