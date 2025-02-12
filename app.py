from fastapi import FastAPI, Request
import os
from supabase import create_client, Client

# Load environment variables
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Connect to Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

@app.post("/vapi/conversation/{client_id}/{project_id}/")
async def vapi_webhook(client_id: str, project_id: str, request: Request):
    data = await request.json()  # Get the incoming JSON data

    # Find a document_id for this project (TEMP SOLUTION: Get 1 document)
    document_query = supabase.table("documents").select("id").eq("project_id", project_id).limit(1).execute()

    if not document_query.data or len(document_query.data) == 0:
        return {"error": "No document found for this project"}

    document_id = document_query.data[0]["id"]  # Get document ID

    # Store the webhook data in Supabase
    response = supabase.table("document_embeddings").insert({
        "document_id": document_id,  # Use document_id instead of project_id
        "metadata": data  # Store webhook data in metadata
    }).execute()

    return {
        "message": f"Webhook received and stored for client {client_id} and project {project_id}",
        "document_id": document_id
    }
