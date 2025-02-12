import os
import time
import json
import logging
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from supabase import create_client, Client
from vapi_client import VAPIClient  # Assuming VAPI client is used for webhook handling

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL and Key must be set in environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

MAX_RETRIES = 3
RETRY_BACKOFF = [60, 300, 900]  # Retry after 1 min, 5 min, 15 min

def log_webhook_failure(project_id: str, endpoint_id: str, request_body: dict, error: str):
    """Log failed webhook attempts in the webhook_logs table."""
    try:
        data = {
            "project_id": project_id,
            "endpoint_id": endpoint_id,
            "status_code": None,
            "request_body": json.dumps(request_body),
            "response_body": None,
            "error": error,
            "created_at": time.strftime('%Y-%m-%d %H:%M:%S')
        }
        supabase.table("webhook_logs").insert(data).execute()
    except Exception as e:
        logger.error(f"Failed to log webhook failure: {str(e)}")

def retry_webhook(request_body: dict, retry_count: int = 0):
    """Retry webhook requests with exponential backoff."""
    if retry_count >= MAX_RETRIES:
        logger.error("Max retries reached for webhook: %s", request_body)
        return
    
    time.sleep(RETRY_BACKOFF[retry_count])  # Apply backoff delay
    try:
        response = VAPIClient.send_webhook(request_body)  # Assume a VAPI client is used
        if response.status_code >= 500:
            logger.warning("Retrying webhook due to server error: %s", response.status_code)
            retry_webhook(request_body, retry_count + 1)
    except Exception as e:
        logger.error("Webhook retry failed: %s", str(e))
        log_webhook_failure(request_body.get("project_id", "unknown"), request_body.get("endpoint_id", "unknown"), request_body, str(e))
        retry_webhook(request_body, retry_count + 1)

@app.post("/vapi/webhook/")
async def vapi_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle incoming webhooks from VAPI."""
    try:
        request_body = await request.json()
        project_id = request_body.get("project_id")
        endpoint_id = request_body.get("endpoint_id")

        if not project_id or not endpoint_id:
            raise HTTPException(status_code=400, detail="Missing project_id or endpoint_id")

        response = VAPIClient.send_webhook(request_body)  # Sending to VAPI

        if response.status_code >= 500:
            logger.warning("Received server error, scheduling retry.")
            background_tasks.add_task(retry_webhook, request_body, 1)
            return {"status": "retrying"}

        return {"status": "ok", "response": response.json()}
    except Exception as e:
        logger.exception("Error processing webhook request")
        log_webhook_failure(request_body.get("project_id", "unknown"), request_body.get("endpoint_id", "unknown"), request_body, str(e))
        return {"status": "failed", "error": str(e)}

@app.post("/vapi/conversation/{client_id}/{project_id}/")
async def start_conversation(client_id: str, project_id: str):
    """Handle live conversations with vector database integration."""
    try:
        documents = supabase.table("documents").select("id").eq("client_id", client_id).eq("project_id", project_id).execute()
        if not documents.data:
            raise HTTPException(status_code=404, detail="No documents found")
        
        document_ids = [doc["id"] for doc in documents.data]
        embeddings = supabase.table("document_embeddings").select("embedding").in_("document_id", document_ids).execute()

        return {"status": "ok", "documents": document_ids, "embeddings": embeddings.data}
    except Exception as e:
        logger.exception("Error starting conversation")
        return {"status": "failed", "error": str(e)}

@app.post("/vapi/call-log/{client_id}/{project_id}/")
async def log_call(client_id: str, project_id: str, request: Request):
    """Log call details in the database after a VAPI call."""
    try:
        call_data = await request.json()
        log_entry = {
            "client_id": client_id,
            "project_id": project_id,
            "call_data": json.dumps(call_data),
            "created_at": time.strftime('%Y-%m-%d %H:%M:%S')
        }
        supabase.table("webhook_logs").insert(log_entry).execute()
        return {"status": "logged"}
    except Exception as e:
        logger.exception("Error logging call")
        return {"status": "failed", "error": str(e)}