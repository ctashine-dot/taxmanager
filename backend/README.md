# 신고서 AI 검토 백엔드

현재 앱(`index.html`)은 브라우저에서 Claude를 직접 호출합니다. 이 백엔드는
**OCR·키워드 검증·chunking**이 필요한 검토를 서버에서 처리하기 위한 선택적
구성입니다(브라우저에서는 Tesseract OCR을 쓸 수 없습니다).

## 구성
- `tax_review.py` — 핵심 로직: PDF 텍스트 추출 → 없으면 OCR(Tesseract) →
  부실하면 Claude 비전 첨부 → 필수 키워드 검증 → 토큰 기준 chunking →
  청크별 Claude 검토(`claude-opus-4-8`) → 결과 병합
- `api.py` — FastAPI 엔드포인트(`POST /review`)

## 실행
```bash
# 시스템 패키지(OCR)
sudo apt-get install -y tesseract-ocr tesseract-ocr-kor   # Debian/Ubuntu

pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
uvicorn api:app --host 0.0.0.0 --port 8000
```

## 호출 예
```bash
curl -F "file=@jongso.pdf" -F "doc_type=income" http://localhost:8000/review
```
응답:
```json
{
  "data": {"revenue": 0, "income": 0, "total_tax": 0, "pay_tax": 0, "resident_tax": 0, "tax_base": 0},
  "findings": [{"level": "tip", "title": "...", "detail": "..."}],
  "missing": [],
  "matched": ["종합소득세", "소득금액", "과세표준", "산출세액"]
}
```

`doc_type`: `vat` | `corp` | `income` | `seongsi` | `sajup`
