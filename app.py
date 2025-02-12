from fastapi import FastAPI, Request, HTTPException
import os
import json
import uuid
from supabase import create_client, Client

# Load environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Validate environment variables
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set.")

# Connect to Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

@app.post("/vapi/conversation/{client_id}/{project_id}/")
async def vapi_webhook(client_id: str, project_id: str, request: Request):
    try:
        data = await request.json()  
        print("Received data:", data)

        # Validate document_id
        document_id = data.get("document_id")
        if not document_id:
            print("Error: document_id is missing")
            raise HTTPException(status_code=400, detail="document_id is required")

        try:
            uuid.UUID(document_id)  # Check if it's a valid UUID
        except ValueError:
            print("Error: Invalid UUID format")
            raise HTTPException(status_code=400, detail="Invalid document_id format")

        # Check if document exists
        project_query = supabase.table("documents").select("project_id").eq("id", document_id).execute()
        print("Query result:", project_query.data)

        if not project_query.data:
            print("Error: Document not found")
            raise HTTPException(status_code=404, detail="Document not found")

        # Insert data into document_embeddings (without client_id)
        insert_data = {
            "document_id": document_id,
            "metadata": json.dumps(data),
            "project_id": project_id  # Ensure project_id is included
        }

        insert_response = supabase.table("document_embeddings").insert(insert_data).execute()
        print("Insert Response:", insert_response)

        return {"message": f"Webhook received and stored for client {client_id} and project {project_id}"}

    except Exception as e:
        print("Internal Server Error:", str(e))
        return {"error": str(e)}
