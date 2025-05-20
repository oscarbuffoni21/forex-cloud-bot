from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import pandas as pd
from pathlib import Path

app = FastAPI()

# Setup templates folder
templates = Jinja2Templates(directory="templates")

# Serve the dashboard page
@app.get("/", response_class=HTMLResponse)
async def read_dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})

# API endpoint to get trade data
@app.get("/api/trades", response_class=JSONResponse)
async def get_trades():
    file_path = Path("trades.csv")
    if not file_path.exists():
        return JSONResponse(content={"trades": []})

    try:
        df = pd.read_csv(file_path)
        trades = df.to_dict(orient="records")
        return {"trades": trades}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)