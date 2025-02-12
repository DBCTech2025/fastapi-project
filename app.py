from fastapi import FastAPI, Request
import requests
import os
import time
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
    print(f"📩 Webhook received for project {project_id} with payload: {payload}")

    # Ensure required fields are present
    document_id = payload.get("document_id")
    if not document_id:
        print("❌ Error: Missing 'document_id' in payload")
        return {"error": "Missing 'document_id' in payload"}

    # Store webhook data in Supabase
    try:
        supabase.table("document_embeddings").insert({
            "document_id": document_id,
            "metadata": payload,
            "project_id": project_id
        }).execute()
        print("✅ Stored webhook in 'document_embeddings'")
    except Exception as e:
        print(f"❌ Database error: {str(e)}")
        return {"error": f"Database error: {str(e)}"}

    # Fetch alternate endpoints
    try:
        endpoints_query = supabase.table("project_endpoints").select("id, url").eq("project_id", project_id).execute()
        endpoints = endpoints_query.data
        print(f"🔍 Fetched endpoints for project {project_id}: {endpoints}")
    except Exception as e:
        print(f"❌ Error fetching endpoints: {str(e)}")
        return {"error": f"Error fetching endpoints: {str(e)}"}

    if not endpoints:
        print("⚠️ No alternate endpoints found.")
        return {"message": "Webhook stored but no alternate endpoints found"}

    # Forward webhook to alternate endpoints
    errors = []
    for endpoint in endpoints:
        endpoint_id = endpoint.get("id")
        endpoint_url = endpoint.get("url")
        if not endpoint_url:
            print(f"⚠️ Skipping invalid endpoint: {endpoint}")
            continue

        start_time = time.time()
        try:
            response = requests.post(endpoint_url, json=payload, headers={"Content-Type": "application/json"})
            duration_ms = int((time.time() - start_time) * 1000)
            print(f"🚀 Forwarded webhook to: {endpoint_url}, Status: {response.status_code}")

            # Store log in Supabase
            supabase.table("webhook_logs").insert({
                "project_id": project_id,
                "endpoint_id": endpoint_id,
                "status_code": response.status_code,
                "request_body": payload,
                "response_body": response.json() if response.content else None,
                "error": None,
                "duration_ms": duration_ms
            }).execute()

            if response.status_code >= 400:
                errors.append(f"❌ Failed to send to {endpoint_url}: {response.status_code}")
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            print(f"❌ Error sending to {endpoint_url}: {str(e)}")

            # Store failure log in Supabase
            supabase.table("webhook_logs").insert({
                "project_id": project_id,
                "endpoint_id": endpoint_id,
                "status_code": None,
                "request_body": payload,
                "response_body": None,
                "error": str(e),
                "duration_ms": duration_ms
            }).execute()
            errors.append(f"❌ Error sending to {endpoint_url}: {str(e)}")

    if errors:
        print(f"⚠️ Webhook stored, but some endpoints failed: {errors}")
        return {"message": "Webhook stored, but some endpoints failed", "errors": errors}

    print("✅ Webhook stored and forwarded successfully")
    return {"message": "Webhook stored and forwarded successfully"}
