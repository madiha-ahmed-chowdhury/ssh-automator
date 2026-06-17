import os
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from ssh_runner import run_ssh_command, run_sudo_command

app = FastAPI(title="SSH Automation PoC")

# Read the expected key from the environment (never hardcode it)
API_KEY = os.environ.get("API_KEY")


def verify_api_key(x_api_key: str = Header(None)):
    """Reject any request whose X-API-Key header doesn't match the server key."""
    if not API_KEY:
        # Fail closed: if the server has no key set, refuse everything.
        raise HTTPException(status_code=500, detail="API_KEY not configured on server")
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


class CommandRequest(BaseModel):
    host: str
    username: str
    password: str
    command: str
    port: int = 22


@app.post("/run", dependencies=[Depends(verify_api_key)])          # read-only
def run(req: CommandRequest):
    try:
        return run_ssh_command(
            req.host, req.username, req.password, req.command, req.port
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/configure", dependencies=[Depends(verify_api_key)])    # write
def configure(req: CommandRequest):
    try:
        return run_sudo_command(
            req.host, req.username, req.password, req.command, req.port
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))