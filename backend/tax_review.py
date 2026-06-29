# tax_review.py — AI 신고서 검토 백엔드
# 의존성:
#   pip install anthropic pdfplumber pymupdf pytesseract pillow pydantic
#   시스템: tesseract-ocr (+ tesseract-ocr-kor 언어팩)
#
# 흐름:  PDF → (텍스트 추출 → 없으면 OCR) → 필수 키워드 검증
#        → 길면 chunking → 청크별 Claude 검토 → 결과 병합

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass, field
from typing import Literal

import anthropic
import fitz  # PyMuPDF
import pdfplumber
import pytesseract
from PIL import Image
from pydantic import BaseModel, Field

MODEL = "claude-opus-4-8"
client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 환경변수 사용

DocType = Literal["vat", "corp", "income", "seongsi", "sajup"]


# ─────────────────────────────────────────────────────────────
# 1) PDF 파싱 — 텍스트가 없으면 OCR(Tesseract) 적용
# ─────────────────────────────────────────────────────────────
@dataclass
class PageContent:
    page_no: int
    text: str
    source: Literal["text", "ocr"]
    image_png: bytes | None = None  # Claude 비전 폴백용(저신뢰 페이지)


# 텍스트 레이어가 이 글자 수 미만이면 스캔본으로 보고 OCR
_MIN_CHARS = 40


def extract_pdf_pages(pdf_path: str, *, ocr_lang: str = "kor+eng",
                      render_dpi: int = 220) -> list[PageContent]:
    """페이지별 텍스트를 추출하고, 비어 있으면 Tesseract OCR로 보강한다.
    OCR 신뢰도가 낮으면 페이지 이미지를 함께 담아 Claude 비전으로 재확인한다."""
    pages: list[PageContent] = []

    with pdfplumber.open(pdf_path) as pdf, fitz.open(pdf_path) as doc:
        for i, page in enumerate(pdf.pages):
            text = (page.extract_text() or "").strip()

            if len(text) >= _MIN_CHARS:
                pages.append(PageContent(i + 1, text, "text"))
                continue

            # 텍스트 레이어 없음 → 렌더 후 OCR
            png = _render_page_png(doc, i, render_dpi)
            ocr_text = pytesseract.image_to_string(
                Image.open(io.BytesIO(png)), lang=ocr_lang
            ).strip()

            # OCR도 부실하면 이미지 자체를 첨부(Claude 비전이 직접 판독)
            low_conf = len(ocr_text) < _MIN_CHARS
            pages.append(PageContent(
                page_no=i + 1,
                text=ocr_text,
                source="ocr",
                image_png=png if low_conf else None,
            ))

    return pages


def _render_page_png(doc: "fitz.Document", index: int, dpi: int) -> bytes:
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    return doc[index].get_pixmap(matrix=mat).tobytes("png")


# ─────────────────────────────────────────────────────────────
# 2) 필수 키워드 검증 — 유형별로 신고서가 맞는지/판독됐는지 사전 점검
# ─────────────────────────────────────────────────────────────
# "본문 수치 미확인" 오판을 막는 1차 게이트: 핵심 키워드가 텍스트/OCR에
# 실제로 존재하는지 코드로 먼저 확인한다.
_REQUIRED_KEYWORDS: dict[DocType, list[list[str]]] = {
    # 각 내부 리스트는 OR, 바깥 리스트는 AND (동의어 허용)
    "vat":     [["부가가치세", "부가세"], ["과세표준"], ["매출세액", "매출"], ["매입세액", "매입"]],
    "corp":    [["법인세"], ["과세표준"], ["산출세액"], ["각사업연도소득", "결산"]],
    "income":  [["종합소득세", "소득세"], ["종합소득금액", "소득금액"], ["과세표준"], ["산출세액", "결정세액"]],
    "seongsi": [["성실신고", "성실신고확인"], ["소득금액"], ["산출세액", "결정세액"]],
    "sajup":   [["사업장현황", "현황신고"], ["수입금액", "총수입금액"]],
}


@dataclass
class ValidationResult:
    ok: bool
    matched: list[str]
    missing: list[str]


def validate_required_keywords(full_text: str, doc_type: DocType) -> ValidationResult:
    flat = full_text.replace(" ", "").replace("\n", "")
    matched, missing = [], []
    for group in _REQUIRED_KEYWORDS[doc_type]:
        hit = next((kw for kw in group if kw.replace(" ", "") in flat), None)
        (matched if hit else missing).append(hit or " / ".join(group))
    return ValidationResult(ok=not missing, matched=matched, missing=missing)


# ─────────────────────────────────────────────────────────────
# 3) Chunking — 긴 문서를 토큰 기준으로 분할(페이지 경계 유지)
# ─────────────────────────────────────────────────────────────
@dataclass
class Chunk:
    index: int
    pages: list[PageContent]

    @property
    def text(self) -> str:
        return "\n\n".join(f"[p.{p.page_no}]\n{p.text}" for p in self.pages)


def _count_tokens(text: str) -> int:
    # tiktoken 쓰지 말 것 — Claude 전용 토크나이저로 정확히 계산
    return client.messages.count_tokens(
        model=MODEL, messages=[{"role": "user", "content": text}]
    ).input_tokens


def chunk_pages(pages: list[PageContent], *, max_tokens: int = 12000) -> list[Chunk]:
    """페이지를 토큰 한도 내에서 묶는다. 한 페이지가 한도를 넘으면 단독 청크."""
    chunks: list[Chunk] = []
    cur: list[PageContent] = []
    cur_tok = 0
    for p in pages:
        tok = _count_tokens(p.text) if p.text else 0
        if cur and cur_tok + tok > max_tokens:
            chunks.append(Chunk(len(chunks), cur))
            cur, cur_tok = [], 0
        cur.append(p)
        cur_tok += tok
    if cur:
        chunks.append(Chunk(len(chunks), cur))
    return chunks


# ─────────────────────────────────────────────────────────────
# 4) 청크별 Claude 검토 (구조화 출력 + 스트리밍 + 적응형 사고)
# ─────────────────────────────────────────────────────────────
class Finding(BaseModel):
    level: Literal["error", "warn", "tip", "ok"]
    title: str = Field(description="10자 내외 짧은 제목")
    detail: str = Field(description="핵심만 1~2줄, 숫자·근거 포함")


class ChunkReview(BaseModel):
    revenue: int = 0
    income: int = 0
    tax_base: int = 0          # 과세표준
    total_tax: int = 0         # 결정세액
    pay_tax: int = 0           # 납부할세액
    resident_tax: int = 0      # 지방소득세
    findings: list[Finding] = []

    model_config = {"extra": "forbid"}  # additionalProperties:false


# ★ 오검토 방지용 도메인 규칙을 시스템 프롬프트에 주입
_DOMAIN_RULES = """당신은 대한민국 세무사입니다. 아래 규칙을 반드시 지키십시오.
[판독]
- 제공된 텍스트/이미지에 숫자가 보이면 절대 '본문 수치 미확인/판독 불가'라고 하지 말 것.
  값을 그대로 읽어 추출하고, 못 찾은 항목만 0으로 두되 그것을 finding으로 만들지 말 것.
[세무 규칙 — 흔한 오류]
- 기장세액공제: '간편장부대상자가 복식부기로 기장'한 경우에만 적용. 복식부기의무자는
  대상이 아님 → 복식부기의무자에게 기장세액공제를 권하지 말 것.
- 표준세액공제와 기장세액공제는 중복 적용 불가(유리한 쪽 택일).
- 지방소득세(주민세)는 결정세액의 10%로 별도 신고.
[출력] 오직 JSON 스키마에 맞춰 출력. 추측성 일반론·면책문구 금지, 근거(금액·항목)는 구체적으로."""


def review_chunk(chunk: Chunk, doc_type: DocType) -> ChunkReview:
    content = _build_chunk_content(chunk, doc_type)
    # 긴 입력/추론 → 스트리밍으로 타임아웃 방지, 적응형 사고로 정확도 확보
    with client.messages.stream(
        model=MODEL,
        max_tokens=8000,
        system=_DOMAIN_RULES,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": ChunkReview.model_json_schema()},
        },
        messages=[{"role": "user", "content": content}],
    ) as stream:
        msg = stream.get_final_message()

    if msg.stop_reason == "refusal":          # 안전 분류기 거절 처리
        return ChunkReview(findings=[Finding(level="warn", title="검토 거절",
                                             detail="안전 정책으로 분석이 거절됨")])
    raw = next(b.text for b in msg.content if b.type == "text")
    return ChunkReview.model_validate_json(raw)


def _build_chunk_content(chunk: Chunk, doc_type: DocType) -> list[dict]:
    blocks: list[dict] = []
    # 저신뢰 페이지는 이미지로도 첨부(비전 판독)
    for p in chunk.pages:
        if p.image_png:
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png",
                           "data": base64.standard_b64encode(p.image_png).decode()},
            })
    blocks.append({"type": "text", "text":
        f"[신고서 유형: {doc_type}] 아래 신고서 본문을 검토하고 핵심 수치와 "
        f"검토의견(findings)을 추출하라.\n\n{chunk.text}"})
    return blocks


# ─────────────────────────────────────────────────────────────
# 5) 결과 병합 — 청크별 추출값/findings 통합
# ─────────────────────────────────────────────────────────────
@dataclass
class FinalReview:
    data: dict[str, int] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    validation: ValidationResult | None = None


def merge_results(reviews: list[ChunkReview]) -> FinalReview:
    # 세액·과세표준 등은 보통 마지막(종합) 페이지에 한 번 → 최댓값/최초 유효값 채택.
    # 매출·소득은 사업장 합산이 필요한 경우가 있으나, 단일 신고서면 최댓값이 안전.
    fields = ["revenue", "income", "tax_base", "total_tax", "pay_tax", "resident_tax"]
    data = {f: max((getattr(r, f) for r in reviews), default=0) for f in fields}
    if not data["resident_tax"] and data["total_tax"]:
        data["resident_tax"] = round(data["total_tax"] * 0.1)

    # findings 중복 제거(레벨+제목 기준)
    seen, findings = set(), []
    for r in reviews:
        for f in r.findings:
            key = (f.level, f.title)
            if key not in seen:
                seen.add(key)
                findings.append(f)
    order = {"error": 0, "warn": 1, "tip": 2, "ok": 3}
    findings.sort(key=lambda f: order[f.level])
    return FinalReview(data=data, findings=findings)


# ─────────────────────────────────────────────────────────────
# 6) 오케스트레이션
# ─────────────────────────────────────────────────────────────
def review_tax_return(pdf_path: str, doc_type: DocType) -> FinalReview:
    pages = extract_pdf_pages(pdf_path)
    full_text = "\n".join(p.text for p in pages)

    validation = validate_required_keywords(full_text, doc_type)
    # 키워드가 통째로 비면 잘못된 파일/유형일 가능성 — 검토 전에 사용자에게 알림
    if not validation.matched:
        return FinalReview(validation=validation, findings=[Finding(
            level="error", title="신고서 인식 실패",
            detail=f"'{doc_type}' 신고서의 핵심 항목을 찾지 못했습니다. 파일/유형을 확인하세요.")])

    chunks = chunk_pages(pages)
    reviews = [review_chunk(c, doc_type) for c in chunks]
    result = merge_results(reviews)
    result.validation = validation
    return result


if __name__ == "__main__":
    out = review_tax_return("sample_jongso.pdf", "income")
    print(json.dumps({"data": out.data,
                      "missing": out.validation.missing if out.validation else [],
                      "findings": [f.model_dump() for f in out.findings]},
                     ensure_ascii=False, indent=2))
