from fastapi import FastAPI, Request
import os
from supabase import create_client, Client

# Load environment variables for Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Connect to Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Initialize FastAPI app
app = FastAPI()

@app.post("/vapi/conversation/{client_id}/{project_id}/")
async def vapi_webhook(client_id: str, project_id: str, request: Request):
    data = await request.json()  # Get the incoming JSON data

    # Retrieve project_id from documents table using document_id
    document_id = data.get("document_id")
    if not document_id:
        return {"error": "Missing document_id in request"}

    project_query = supabase.table("documents").select("project_id").eq("id", document_id).execute()
    project_data = project_query.data

    if not project_data:
        return {"error": f"No project found for document_id {document_id}"}

    resolved_project_id = project_data[0]["project_id"]

    # Insert into document_embeddings with the correct project_id
    response = supabase.table("document_embeddings").insert({
        "document_id": document_id,
        "project_id": resolved_project_id,  # Ensure we store project_id
        "client_id": client_id,
        "data": data
    }).execute()

    return {
        "message": f"Webhook received and stored for client {client_id} and project {resolved_project_id}",
        "document_id": document_id
    }
