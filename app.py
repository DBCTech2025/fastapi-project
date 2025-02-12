from fastapi import FastAPI

app = FastAPI()

@app.post("/vapi/conversation/{client_id}/{project_id}/")
def process_conversation(client_id: str, project_id: str):
    return {"message": f"Received for client {client_id} and project {project_id}"}
