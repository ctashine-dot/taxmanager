# api.py — AI 신고서 검토 FastAPI 엔드포인트
# 실행:
#   pip install -r requirements.txt
#   export ANTHROPIC_API_KEY=...
#   uvicorn api:app --host 0.0.0.0 --port 8000
#
# 사용:
#   POST /review   (multipart: file=<PDF>, doc_type=income|vat|corp|seongsi|sajup)
#     → {"data": {...세액·매출·소득...}, "findings": [...], "missing": [...]}

import os
import tempfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from tax_review import DocType, review_tax_return

app = FastAPI(title="신고서 AI 검토 API", version="1.0")

# 브라우저(SPA)에서 직접 호출할 수 있도록 CORS 허용 — 운영 시 도메인 제한 권장
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOW_ORIGINS", "*").split(","),
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

_VALID_TYPES = {"vat", "corp", "income", "seongsi", "sajup"}
_MAX_BYTES = 32 * 1024 * 1024  # 32MB


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/review")
async def review(file: UploadFile = File(...), doc_type: str = Form(...)):
    if doc_type not in _VALID_TYPES:
        raise HTTPException(400, f"doc_type must be one of {sorted(_VALID_TYPES)}")
    if (file.content_type or "").lower() not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(400, "PDF 파일만 업로드 가능합니다")

    data = await file.read()
    if not data:
        raise HTTPException(400, "빈 파일입니다")
    if len(data) > _MAX_BYTES:
        raise HTTPException(413, "파일이 너무 큽니다(32MB 초과)")

    # tax_review는 파일 경로를 받으므로 임시 파일로 저장
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        tmp.write(data)
        tmp.flush()
        tmp.close()
        result = review_tax_return(tmp.name, doc_type)  # type: ignore[arg-type]
    except Exception as e:  # 파싱/AI 오류를 클라이언트가 처리할 수 있게 전달
        raise HTTPException(500, f"검토 실패: {e}")
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    return {
        "data": result.data,
        "findings": [f.model_dump() for f in result.findings],
        "missing": result.validation.missing if result.validation else [],
        "matched": result.validation.matched if result.validation else [],
    }
