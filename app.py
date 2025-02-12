from fastapi import FastAPI, HTTPException, Request
import logging
import requests
import os
import time
from supabase import create_client, Client
import json

# Initialize FastAPI
app = FastAPI()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Supabase credentials
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL and Key must be set in environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    try:
        body = await request.body()
        if body:
            json_body = json.loads(body)
            logger.info(f"🔍 Incoming request: {json_body}")
        else:
            logger.warning("⚠️ Incoming request has an empty body")
    except json.JSONDecodeError:
        logger.error("❌ Invalid JSON payload received")
        return HTTPException(status_code=400, detail="Invalid JSON payload")
    
    response = await call_next(request)
    return response

@app.post("/vapi/conversation/{conversation_id}/{project_id}/")
async def handle_conversation(conversation_id: str, project_id: str, request: Request):
    try:
        payload = await request.json()
        logger.info(f"📩 Webhook received for project {project_id} with payload: {payload}")
    except json.JSONDecodeError:
        logger.error("❌ Received invalid JSON payload")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Ensure document_id is in the payload
    document_id = payload.get("document_id")
    if not document_id:
        logger.error("❌ Missing 'document_id' in payload")
        logger.info(f"📄 Full payload for debugging: {payload}")
        raise HTTPException(status_code=400, detail="Missing 'document_id' in payload")

    # Store webhook data in Supabase
    try:
        supabase.table("document_embeddings").insert({
            "document_id": document_id,
            "metadata": payload,
            "project_id": project_id
        }).execute()
        logger.info("✅ Stored webhook in 'document_embeddings'")
    except Exception as e:
        logger.error(f"❌ Database error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    # Fetch alternate endpoints
    try:
        endpoints_query = supabase.table("project_endpoints").select("id, url").eq("project_id", project_id).execute()
        endpoints = endpoints_query.data
        logger.info(f"🔍 Fetched endpoints for project {project_id}: {endpoints}")
    except Exception as e:
        logger.error(f"❌ Error fetching endpoints: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching endpoints: {str(e)}")

    if not endpoints:
        logger.warning("⚠️ No alternate endpoints found.")
        return {"message": "Webhook stored but no alternate endpoints found"}

    # Forward webhook to alternate endpoints
    errors = []
    for endpoint in endpoints:
        endpoint_id = endpoint.get("id")
        endpoint_url = endpoint.get("url")
        if not endpoint_url:
            logger.warning(f"⚠️ Skipping invalid endpoint: {endpoint}")
            continue

        start_time = time.time()
        try:
            response = requests.post(endpoint_url, json=payload, headers={"Content-Type": "application/json"})
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(f"🚀 Forwarded webhook to: {endpoint_url}, Status: {response.status_code}")

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
            logger.error(f"❌ Error sending to {endpoint_url}: {str(e)}")

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
        logger.warning(f"⚠️ Webhook stored, but some endpoints failed: {errors}")
        return {"message": "Webhook stored, but some endpoints failed", "errors": errors}

    logger.info("✅ Webhook stored and forwarded successfully")
    return {"message": "Webhook stored and forwarded successfully"}