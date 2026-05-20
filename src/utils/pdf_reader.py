"""비밀번호 걸린 PDF 파일 복호화 및 텍스트/표 추출 (건강보험공단 PDF 대응)"""
import os
import sys
import fitz  # PyMuPDF

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.detach(), encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.detach(), encoding="utf-8")


def decrypt_pdf(pdf_path: str, password: str, save_path: str = None) -> str:
    """비밀번호로 PDF 복호화 후 비밀번호 없는 복사본 저장."""
    doc = fitz.open(pdf_path)
    if doc.is_encrypted:
        if not doc.authenticate(password):
            raise ValueError("비밀번호가 틀렸습니다.")

    if save_path is None:
        base, ext = os.path.splitext(pdf_path)
        save_path = f"{base}_복호화{ext}"

    doc.save(save_path)
    doc.close()
    print(f"복호화 완료: {save_path}")
    return save_path


def postprocess_pdf(pdf_path: str, password: str) -> tuple:
    """다운로드 후 후처리: PDF 복호화(원본 대체) + 텍스트 파일 저장.

    Args:
        pdf_path: 다운로드된 PDF 경로
        password: PDF 비밀번호

    Returns:
        (decrypted_pdf_path, text_file_path)
    """
    # 1) 임시 파일에 복호화 후 원본 대체
    base, ext = os.path.splitext(pdf_path)
    tmp_path = f"{base}_tmp{ext}"

    doc = fitz.open(pdf_path)
    if doc.is_encrypted:
        if not doc.authenticate(password):
            raise ValueError("비밀번호가 틀렸습니다.")
    doc.save(tmp_path)
    doc.close()

    os.replace(tmp_path, pdf_path)
    print(f"[1/2] PDF 복호화 완료 (원본 대체): {pdf_path}")

    # 2) 텍스트 추출 후 .txt 저장
    text_file = f"{base}.txt"
    doc = fitz.open(pdf_path)
    with open(text_file, "w", encoding="utf-8") as f:
        for i, page in enumerate(doc):
            f.write(page.get_text())
    doc.close()
    print(f"[2/2] 텍스트 파일 저장: {text_file}")

    return pdf_path, text_file


def extract_text(pdf_path: str, password: str = None) -> str:
    """PDF에서 전체 텍스트 추출."""
    doc = fitz.open(pdf_path)
    if doc.is_encrypted:
        if not doc.authenticate(password):
            raise ValueError("비밀번호가 틀렸습니다.")

    full_text = ""
    for i, page in enumerate(doc):
        full_text += f"\n--- 페이지 {i + 1} ---\n"
        full_text += page.get_text()

    doc.close()
    return full_text


def extract_tables(pdf_path: str, password: str = None) -> list:
    """PDF에서 표 데이터 추출 (각 페이지별)."""
    doc = fitz.open(pdf_path)
    if doc.is_encrypted:
        if not doc.authenticate(password):
            raise ValueError("비밀번호가 틀렸습니다.")

    all_tables = []
    for i, page in enumerate(doc):
        tabs = page.find_tables()
        if tabs.tables:
            for table in tabs.tables:
                all_tables.append({
                    "page": i + 1,
                    "data": table.extract(),
                })

    doc.close()
    return all_tables


def extract_nhis_payment(pdf_path: str, password: str = None) -> dict:
    """건강보험 납부확인서 PDF에서 핵심 정보를 파싱.

    Returns:
        {
            "name": "이시용",
            "birth": "1988.07.18.",
            "company": "주식회사 쿠키로켓",
            "payer_number": "81080963706",
            "period": "2026년 01월 ~ 2026년 12월",
            "monthly": [ {"month": "1월", "health": 85400, "longterm": 11220, ...}, ... ],
            "total_health": -222670,
            "total_longterm": -28730,
            "total_amount": -251400,
            "issue_number": "11-20260512-0815640",
            "issue_date": "2026년 05월 12일",
        }
    """
    doc = fitz.open(pdf_path)
    if doc.is_encrypted:
        if not doc.authenticate(password):
            raise ValueError("비밀번호가 틀렸습니다.")

    page = doc[0]
    tabs = page.find_tables()

    result = {}
    if not tabs.tables:
        doc.close()
        return result

    data = tabs.tables[0].extract()

    for row in data:
        clean = [str(c).strip() if c else "" for c in row]
        joined = " ".join(clean)
        if "가입자 성명" in joined:
            for c in clean:
                if c and c not in ("가입자 성명", ""):
                    result["name"] = c
                    break
        elif "생년월일" in joined:
            for c in clean:
                if c and "." in c and len(c) >= 8:
                    result["birth"] = c
                    break
        elif "사업장 명칭" in joined:
            for c in clean:
                if c and c not in ("사업장 명칭", ""):
                    result["company"] = c
                    break
        elif "납부자번호" in joined:
            for c in clean:
                if c and c.isdigit() and len(c) >= 8:
                    result["payer_number"] = c
                    break

    monthly = []
    for row in data:
        clean = [str(c).strip() if c else "" for c in row]
        first = clean[0]
        if first and first.endswith("월") and first[0].isdigit():
            month = first
            # 고지금액: 건강보험료, 장기요양보험료 (인덱스 1, 3)
            # 납부금액: 건강보험료, 장기요양보험료 (인덱스 6, 8)
            def parse_amount(s):
                return int(s.replace(",", "").replace(" ", "")) if s and s not in ("", "0") else 0

            monthly.append({
                "month": month,
                "billed_health": parse_amount(clean[1]) if len(clean) > 1 else 0,
                "billed_longterm": parse_amount(clean[3]) if len(clean) > 3 else 0,
                "paid_health": parse_amount(clean[6]) if len(clean) > 6 else 0,
                "paid_longterm": parse_amount(clean[8]) if len(clean) > 8 else 0,
            })

    if monthly:
        result["monthly"] = monthly

    for row in data:
        clean = [str(c).strip() if c else "" for c in row]
        first = clean[0]
        if first == "합계":
            def parse_amount(s):
                return int(s.replace(",", "").replace(" ", "")) if s and s not in ("", "0") else 0
            result["total_health"] = parse_amount(clean[1]) if len(clean) > 1 else 0
            result["total_longterm"] = parse_amount(clean[3]) if len(clean) > 3 else 0
        elif first == "납부총액":
            for c in clean:
                c = c.replace(",", "").strip()
                if c.lstrip("-").isdigit():
                    result["total_amount"] = int(c)
                    break
        elif "발급번호" in first:
            for c in clean:
                if c and "-" in c and any(ch.isdigit() for ch in c):
                    result["issue_number"] = c.strip()
                    break

    # 텍스트에서 발급일 추출
    text = page.get_text()
    for line in text.split("\n"):
        line = line.strip()
        if line and "년" in line and "월" in line and "일" in line and "2026" in line and "납부" not in line:
            result["issue_date"] = line
            break

    doc.close()
    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python pdf_reader.py <pdf파일경로> <비밀번호> [--text|--tables|--decrypt|--nhis]")
        sys.exit(1)

    pdf_file = sys.argv[1]
    pwd = sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else "--text"

    if mode == "--decrypt":
        decrypt_pdf(pdf_file, pwd)
    elif mode == "--tables":
        tables = extract_tables(pdf_file, pwd)
        for t in tables:
            print(f"\n=== 페이지 {t['page']} ===")
            for row in t["data"]:
                print(" | ".join(str(c) if c else "" for c in row))
    elif mode == "--nhis":
        import json
        info = extract_nhis_payment(pdf_file, pwd)
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        text = extract_text(pdf_file, pwd)
        print(text)
