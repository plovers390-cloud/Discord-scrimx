from fastapi import FastAPI

app = FastAPI()

@app.get("/ocr")
async def ocr_endpoint():
    return {"message": "OCR endpoint running"}
from fastapi import FastAPI, Header, HTTPException

app = FastAPI()

FASTAPI_KEY = "mysecret123"

@app.get("/ocr")
async def ocr_endpoint(x_api_key: str = Header(...)):
    if x_api_key != FASTAPI_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return {"status": "ok"}
