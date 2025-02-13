from fastapi import FastAPI, Request, HTTPException
import requests
import os
import time
from supabase import create_client, Client
import json
import logging

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

@app.post("/vapi/conversation/{client_id}/{project_id}/")
async def vapi_webhook(client_id: str, project_id: str, request: Request):
    try:
        payload = await request.json()
        logger.info(f"📩 Webhook received for project {project_id} with payload: {payload}")
    except json.JSONDecodeError:
        logger.error("❌ Invalid JSON payload received")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 🔍 Fetch document_id from Supabase (FIXED COLUMN NAME ISSUE)
    try:
        logger.info(f"🔍 Querying documents for project_id={project_id}...")
        doc_query = supabase.table("documents")\
            .select("id")\
            .eq("project_id", project_id)\
            .execute()

        if not doc_query.data or len(doc_query.data) == 0:
            logger.error(f"❌ No document found for project_id {project_id}")
            raise HTTPException(status_code=404, detail="No document found for this project")

        document_id = doc_query.data[0]["id"]
    except Exception as e:
        logger.error(f"❌ Supabase query error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    # Store webhook data in Supabase
    try:
        supabase.table("document_embeddings").insert({
            "document_id": document_id,
            "metadata": json.dumps(payload),  # Ensure metadata is JSON serializable
            "project_id": project_id
        }).execute()
        logger.info(f"✅ Webhook stored with document_id: {document_id}")
    except Exception as e:
        logger.error(f"❌ Database error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    # Fetch endpoints
    try:
        endpoints_query = supabase.table("project_endpoints").select("id, url").eq("project_id", project_id).execute()
        endpoints = endpoints_query.data
        logger.info(f"🔍 Endpoints fetched for project {project_id}: {endpoints}")
    except Exception as e:
        logger.error(f"❌ Error fetching endpoints: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching endpoints: {str(e)}")

    if not endpoints:
        logger.warning("⚠️ No endpoints found. Webhook stored but not forwarded.")
        return {"message": "Webhook stored but no endpoints found"}

    # Forward webhook to endpoints
    errors = []
    for endpoint in endpoints:
        endpoint_id = endpoint.get("id")
        endpoint_url = endpoint.get("url")
        if not endpoint_url:
            logger.warning(f"⚠️ Skipping invalid endpoint: {endpoint}")
            continue

        logger.info(f"🚀 Sending webhook to: {endpoint_url}")

        # Only add topK=2 for endpoints with the specified vapi URL prefix.
        if endpoint_url.startswith("https://omsysapi.omaserver.com/index.php/calls/vapi/"):
            modified_payload = payload.copy()
            # If topK is missing or falsy, set it to 2.
            if not modified_payload.get("topK"):
                modified_payload["topK"] = 2
                logger.info(f"Added topK=2 to payload for endpoint {endpoint_url}")
        else:
            modified_payload = payload

        start_time = time.time()
        try:
            response = requests.post(endpoint_url, json=modified_payload, headers={"Content-Type": "application/json"})
            duration_ms = int((time.time() - start_time) * 1000)

            response_body = None
            error_message = None

            try:
                if response.content and "application/json" in response.headers.get("Content-Type", ""):
                    response_body = response.json()
                else:
                    response_body = response.text
            except requests.exceptions.JSONDecodeError:
                response_body = response.text  # Store raw text response instead of failing

            if 200 <= response.status_code < 300:
                logger.info(f"✅ Webhook sent to {endpoint_url} with status {response.status_code}, response: {response_body}")
            else:
                logger.warning(f"⚠️ Webhook sent but failed with status {response.status_code} to {endpoint_url}, response: {response_body}")
                error_message = f"Failed with status {response.status_code}"

            supabase.table("webhook_logs").insert({
                "project_id": project_id,
                "endpoint_id": endpoint_id,
                "status_code": response.status_code,
                "request_body": json.dumps(payload),  # Original payload logged
                "response_body": response_body,
                "error": error_message,
                "duration_ms": duration_ms
            }).execute()

        except requests.exceptions.RequestException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"❌ Error sending to {endpoint_url}: {str(e)}")

            supabase.table("webhook_logs").insert({
                "project_id": project_id,
                "endpoint_id": endpoint_id,
                "status_code": None,
                "request_body": json.dumps(payload),  # Original payload logged
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
