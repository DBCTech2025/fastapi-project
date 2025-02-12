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
        logger.info(f"\ud83d\udce9 Webhook received for project {project_id} with payload: {payload}")
    except json.JSONDecodeError:
        logger.error("\u274c Invalid JSON payload received")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Ensure client_id and project_id exist in the correct tables
    doc_query = supabase.table("documents")\
        .select("id")\
        .eq("client_id", client_id)\
        .eq("project_id", project_id)\
        .execute()

    if not doc_query.data or len(doc_query.data) == 0:
        logger.error(f"\u274c No document found for client_id {client_id} and project_id {project_id}")
        raise HTTPException(status_code=404, detail="No document found for this project")

    document_id = doc_query.data[0]["id"]

    # Store webhook data in Supabase
    try:
        supabase.table("document_embeddings").insert({
            "document_id": document_id,
            "metadata": json.dumps(payload),  # Ensure metadata is JSON serializable
            "project_id": project_id
        }).execute()
        logger.info(f"\u2705 Webhook stored with document_id: {document_id}")
    except Exception as e:
        logger.error(f"\u274c Database error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    # Fetch endpoints
    try:
        endpoints_query = supabase.table("project_endpoints").select("id, url").eq("project_id", project_id).execute()
        endpoints = endpoints_query.data
        logger.info(f"\ud83d\udd0d Endpoints fetched for project {project_id}: {endpoints}")
    except Exception as e:
        logger.error(f"\u274c Error fetching endpoints: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching endpoints: {str(e)}")

    if not endpoints:
        logger.warning("\u26a0\ufe0f No endpoints found. Webhook stored but not forwarded.")
        return {"message": "Webhook stored but no endpoints found"}

    # Forward webhook to endpoints
    errors = []
    for endpoint in endpoints:
        endpoint_id = endpoint.get("id")
        endpoint_url = endpoint.get("url")
        if not endpoint_url:
            logger.warning(f"\u26a0\ufe0f Skipping invalid endpoint: {endpoint}")
            continue

        logger.info(f"\ud83d\ude80 Sending webhook to: {endpoint_url}")
        start_time = time.time()
        try:
            response = requests.post(endpoint_url, json=payload, headers={"Content-Type": "application/json"})
            duration_ms = int((time.time() - start_time) * 1000)

            response_body = None
            error_message = None

            try:
                response_body = response.json() if response.content and response.headers.get("Content-Type") == "application/json" else response.text
            except requests.exceptions.JSONDecodeError:
                response_body = response.text  # Store raw text response instead of failing

            if response.status_code >= 200 and response.status_code < 300:
                logger.info(f"\u2705 Webhook sent to {endpoint_url} with status {response.status_code}, response: {response_body}")
            else:
                logger.warning(f"\u26a0\ufe0f Webhook sent but failed with status {response.status_code} to {endpoint_url}, response: {response_body}")
                error_message = f"Failed with status {response.status_code}"

            supabase.table("webhook_logs").insert({
                "project_id": project_id,
                "endpoint_id": endpoint_id,
                "status_code": response.status_code,
                "request_body": json.dumps(payload),  # Ensure payload is JSON serializable
                "response_body": response_body,
                "error": error_message,
                "duration_ms": duration_ms
            }).execute()

        except requests.exceptions.RequestException as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"\u274c Error sending to {endpoint_url}: {str(e)}")

            supabase.table("webhook_logs").insert({
                "project_id": project_id,
                "endpoint_id": endpoint_id,
                "status_code": None,
                "request_body": json.dumps(payload),  # Ensure payload is JSON serializable
                "response_body": None,
                "error": str(e),
                "duration_ms": duration_ms
            }).execute()

            errors.append(f"\u274c Error sending to {endpoint_url}: {str(e)}")

    if errors:
        logger.warning(f"\u26a0\ufe0f Webhook stored, but some endpoints failed: {errors}")
        return {"message": "Webhook stored, but some endpoints failed", "errors": errors}

    logger.info("\u2705 Webhook stored and forwarded successfully")
    return {"message": "Webhook stored and forwarded successfully"}
