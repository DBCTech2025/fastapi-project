import os
import logging
import httpx
from flask import Flask, request, jsonify

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)

# Supabase configuration (set these as environment variables in Render)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://your-supabase-url.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "your-supabase-key")
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}


def fetch_project_endpoints(project_id):
    """Fetch endpoints for a given project from Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/project_endpoints"
    params = {"select": "id,url", "project_id": f"eq.{project_id}"}
    response = httpx.get(url, headers=SUPABASE_HEADERS, params=params)
    if response.status_code == 200:
        endpoints = response.json()
        logging.info(f"Endpoints fetched for project {project_id}: {endpoints}")
        return endpoints
    else:
        logging.error(f"Failed to fetch endpoints for project {project_id}: {response.text}")
        return []


def log_webhook(payload):
    """Store a log of the webhook call to Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/webhook_logs"
    response = httpx.post(url, headers=SUPABASE_HEADERS, json=payload)
    if response.status_code == 201:
        logging.info("Webhook log stored successfully")
    else:
        logging.warning(f"Failed to store webhook log: {response.text}")


def send_webhook(url, payload):
    """Send the payload to the given webhook URL."""
    try:
        response = httpx.post(url, json=payload)
        if response.status_code == 200:
            logging.info(f"✅ Webhook sent to {url} with status {response.status_code}, response: {response.text}")
        else:
            logging.warning(f"⚠️ Webhook sent but failed with status {response.status_code} to {url}, response: {response.json()}")
        return response
    except Exception as e:
        logging.error(f"Error sending webhook to {url}: {e}")
        return None


@app.route('/vapi/conversation/<conversation_id>/<project_id>/', methods=['POST'])
def process_conversation(conversation_id, project_id):
    # Retrieve the incoming JSON payload
    payload = request.get_json(force=True)

    # Log the incoming webhook storage (if applicable)
    document_id = payload.get("document_id", "unknown")
    logging.info(f"✅ Webhook stored with document_id: {document_id}")

    # Fetch endpoints for the given project
    endpoints = fetch_project_endpoints(project_id)

    # Send the webhook payload to each endpoint
    for endpoint in endpoints:
        endpoint_url = endpoint.get("url")
        if endpoint_url:
            # Create a copy of the payload for this endpoint
            payload_to_send = payload.copy()

            # For endpoints beginning with the specified vapi URL, ensure topK is included.
            if endpoint_url.startswith("https://omsysapi.omaserver.com/index.php/calls/vapi/"):
                if "topK" not in payload_to_send:
                    payload_to_send["topK"] = 2
                    logging.info(f"For endpoint {endpoint_url}, topK not provided; adding topK = 2.")

            logging.info(f"🚀 Sending webhook to: {endpoint_url}")
            response = send_webhook(endpoint_url, payload_to_send)

            # Log the attempt
            log_data = {
                "project_id": project_id,
                "conversation_id": conversation_id,
                "endpoint_url": endpoint_url,
                "response_status": response.status_code if response else "error",
                "response_body": response.text if response else "error"
            }
            log_webhook(log_data)
        else:
            logging.warning("Endpoint URL missing in the fetched endpoints.")

    return jsonify({"status": "success"}), 200


if __name__ == '__main__':
    # When running locally, set debug=True; in production, Render will use gunicorn or similar.
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
