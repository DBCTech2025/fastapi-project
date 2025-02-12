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

# Create Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.post("/vapi/conversation/{client_id}/{project_id}/")
async def vapi_webhook(client_id: str, project_id: str, request: Request):
    payload = await request.json()
    
    # Ensure required fields are present
    document_id = payload.get("document_id")
    if not document_id:
        return {"error": "❌ Missing 'document_id' in payload"}

    print(f"📩 Webhook received for project {project_id} with payload: {payload}")

    # ✅ Step 1: Store webhook data in Supabase
    try:
        response = supabase.table("document_embeddings").insert({
            "document_id": document_id,
            "metadata": payload,
            "project_id": project_id
        }).execute()
        print(f"✅ Stored webhook in 'document_embeddings' for document {document_id}. DB Response: {response.data}")
    except Exception as e:
        print(f"❌ Database Error: {str(e)}")
        return {"error": f"Database error: {str(e)}"}

    # ✅ Step 2: Fetch alternate endpoints from "project_endpoints"
    try:
        endpoints_query = supabase.table("project_endpoints").select("url").eq("project_id", project_id).execute()
        endpoints = endpoints_query.data or []
        print(f"🔍 Fetched endpoints for project {project_id}: {endpoints}")
    except Exception as e:
        print(f"❌ Error fetching endpoints: {str(e)}")
        return {"error": f"Error fetching endpoints: {str(e)}"}
    
    if not endpoints:
        print("❌ No alternate endpoints found for this project.")
        return {"message": "Webhook stored but no alternate endpoints found"}

    # ✅ Step 3: Forward webhook to alternate endpoints
    errors = []
    for endpoint in endpoints:
        endpoint_url = endpoint.get("url")  # ✅ Ensure correct column name
        if not endpoint_url:
            print(f"⚠️ Skipping invalid endpoint entry: {endpoint}")
            continue  # Skip invalid entries

        try:
            response = requests.post(endpoint_url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
            print(f"🚀 Forwarded webhook to: {endpoint_url}, Status: {response.status_code}, Response: {response.text}")
            if response.status_code >= 400:
                errors.append(f"⚠️ Failed to send to {endpoint_url}: {response.status_code} - {response.text}")
        except Exception as e:
            errors.append(f"❌ Error sending to {endpoint_url}: {str(e)}")

    # ✅ Step 4: Return results
    if errors:
        print(f"⚠️ Some endpoints failed: {errors}")
        return {"message": "Webhook stored, but some endpoints failed", "errors": errors}
    
    print("✅ Webhook successfully forwarded to all endpoints.")
    return {"message": "Webhook stored and forwarded successfully"}
