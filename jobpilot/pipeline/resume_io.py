"""简历文件读取：PDF / DOCX / TXT → 纯文本。

单独拆出来的原因：
- 抽文本和抽字段是两件事，前者可以换 OCR，后者可以换模型
- 扫描版 PDF 抽出来是空文本，必须显式报错，不能静默返回空
"""

from __future__ import annotations

from pathlib import Path


class ResumeReadError(Exception):
    """读不出文本时抛出，调用方必须处理，不允许静默返回空。"""


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(p.extract_text() or "") for p in reader.pages]
    return "\n".join(pages).strip()


def _read_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text.strip())
    return "\n".join(parts).strip()


def read_text(path: str | Path) -> str:
    """读取简历文件，返回纯文本。

    Raises:
        ResumeReadError: 文件不存在、格式不支持、或抽不出文字（扫描件）。
    """
    p = Path(path)
    if not p.exists():
        raise ResumeReadError(f"文件不存在：{p}")

    suffix = p.suffix.lower()
    try:
        if suffix == ".pdf":
            text = _read_pdf(p)
        elif suffix == ".docx":
            text = _read_docx(p)
        elif suffix in (".txt", ".md"):
            text = p.read_text(encoding="utf-8", errors="ignore").strip()
        else:
            raise ResumeReadError(f"不支持的文件格式：{suffix}（支持 pdf / docx / txt）")
    except ResumeReadError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ResumeReadError(f"解析失败（{suffix}）：{exc}") from exc

    if len(text) < 50:
        raise ResumeReadError(
            f"只抽出 {len(text)} 个字符，可能是扫描版 PDF（整页图片）。"
            "请换成可复制文本的 PDF，或先用 OCR 转换。"
        )
    return text
