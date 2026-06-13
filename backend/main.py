import base64
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from inspector import PatchCoreInspector

app = FastAPI(title="外観検査 API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

inspector = PatchCoreInspector()


@app.get("/health")
def health():
    return {"status": "ok", "fitted": inspector.is_fitted, "threshold": inspector.threshold}


@app.post("/register")
async def register(files: list[UploadFile] = File(...)):
    if len(files) < 5:
        raise HTTPException(400, "最低5枚の良品画像が必要です")
    images = [await f.read() for f in files]
    try:
        return inspector.fit(images)
    except Exception as e:
        raise HTTPException(500, f"学習に失敗しました: {e}")


@app.get("/reference")
def reference():
    if not inspector.reference_image:
        raise HTTPException(404, "参照画像がありません。良品を再登録してください。")
    return {"image_base64": base64.b64encode(inspector.reference_image).decode()}


@app.post("/inspect")
async def inspect(
    file: UploadFile = File(...),
    heat_threshold: float = Form(0.5),
):
    if not inspector.is_fitted:
        raise HTTPException(400, "良品が未登録です")
    data = await file.read()
    return inspector.predict(data, heat_threshold)
