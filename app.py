from fastapi import FastAPI, Request
import requests
import os
from supabase import create_client, Client

# Initialize FastAPI
app = FastAPI()

# Supabase credentials
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Ensure credentials exist
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL and Key must be set in environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.post("/vapi/conversation/{client_id}/{project_id}/")
async def vapi_webhook(client_id: str, project_id: str, request: Request):
    payload = await request.json()
    
    # Ensure required fields are present
    document_id = payload.get("document_id")
    if not document_id:
        return {"error": "Missing 'document_id' in payload"}
    
    # Store webhook data in Supabase
    try:
        supabase.table("document_embeddings").insert({
            "document_id": document_id,
            "metadata": payload,
            "project_id": project_id
        }).execute()
    except Exception as e:
        return {"error": f"Database error: {str(e)}"}

    # Fetch alternate endpoints
    try:
        endpoints_query = supabase.table("project_endpoints").select("endpoint_url").eq("project_id", project_id).execute()
        endpoints = endpoints_query.data
    except Exception as e:
        return {"error": f"Error fetching endpoints: {str(e)}"}
    
    if not endpoints:
        return {"message": "Webhook stored but no alternate endpoints found"}

    # Forward webhook to alternate endpoints
    errors = []
    for endpoint in endpoints:
        endpoint_url = endpoint["endpoint_url"]
        try:
            response = requests.post(endpoint_url, json=payload, headers={"Content-Type": "application/json"})
            print(f"Forwarded webhook to: {endpoint_url}, Status: {response.status_code}")
            if response.status_code >= 400:
                errors.append(f"Failed to send to {endpoint_url}: {response.status_code}")
        except Exception as e:
            errors.append(f"Error sending to {endpoint_url}: {str(e)}")
    
    if errors:
        return {"message": "Webhook stored, but some endpoints failed", "errors": errors}
    
    return {"message": "Webhook stored and forwarded successfully"}