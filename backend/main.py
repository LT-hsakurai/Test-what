import os
import anthropic
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from inspector import PatchCoreInspector

app = FastAPI(title="外観検査 API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

inspector = PatchCoreInspector()


@app.get("/health")
def health():
    return {"status": "ok", "fitted": inspector.is_fitted, "threshold": inspector.threshold}


@app.post("/register")
async def register(
    files: list[UploadFile] = File(...),
    roi_x: float = Form(0.0),
    roi_y: float = Form(0.0),
    roi_w: float = Form(1.0),
    roi_h: float = Form(1.0),
):
    if len(files) < 5:
        raise HTTPException(400, "最低5枚の良品画像が必要です")
    images = [await f.read() for f in files]
    return inspector.fit(images, (roi_x, roi_y, roi_w, roi_h))


@app.post("/inspect")
async def inspect(
    file: UploadFile = File(...),
    match_tolerance: float = Form(0.35),
):
    if not inspector.is_fitted:
        raise HTTPException(400, "良品が未登録です")
    data = await file.read()
    return inspector.predict(data, match_threshold=match_tolerance)


class ExplainRequest(BaseModel):
    image_base64: str
    normalized_score: float
    judgment: str


@app.post("/explain")
async def explain(req: ExplainRequest):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(500, "ANTHROPIC_API_KEY が未設定です")

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": req.image_base64},
                },
                {
                    "type": "text",
                    "text": (
                        f"製品外観検査の異常スコアが良品基準の {req.normalized_score:.1f} 倍でした（判定: {req.judgment}）。\n"
                        "この画像を見て、欠陥の種類・位置・深刻度を3〜4文で日本語で説明してください。"
                    ),
                },
            ],
        }],
    )
    return {"explanation": msg.content[0].text}
