"""Trusted bounded document parser. Receives data through stdin, never a host path."""
import base64
import io
import json
import resource
import sys
import zipfile


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 6))
    if sys.platform != 'darwin':
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024,) * 2)
    payload = json.loads(sys.stdin.buffer.read(3_000_000))
    data = base64.b64decode(payload['data'], validate=True)
    suffix = payload['suffix']
    try:
        if suffix == '.pdf':
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise ValueError('请上传未加密的 PDF。')
            if len(reader.pages) > 40:
                raise ValueError('当前一次最多解析 40 页，请拆分文件。')
            text = '\n\n'.join((page.extract_text() or '')[:30000] for page in reader.pages)[:120000]
        elif suffix == '.docx':
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(item.file_size for item in archive.infolist()) > 20_000_000 or len(archive.infolist()) > 1500:
                    raise ValueError('DOCX 解压内容过大。')
            from docx import Document
            doc = Document(io.BytesIO(data))
            text = '\n'.join([p.text for p in doc.paragraphs] + [' | '.join(cell.text for cell in row.cells) for table in doc.tables for row in table.rows])[:120000]
        else:
            text = data.decode('utf-8-sig')[:120000]
        if not text.strip():
            raise ValueError('未提取到文字。扫描 PDF 或图片需先进行 OCR。')
        print(json.dumps({'text': text}, ensure_ascii=False))
    except Exception:
        print(json.dumps({'error': '文件解析失败：请检查格式、加密状态及页数；扫描件需先进行 OCR。'}))


if __name__ == '__main__':
    main()
