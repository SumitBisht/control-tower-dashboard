"""Shrinks a real report (100 MB of photos) to a ~100 KB test fixture by swapping every image for a 1x1 PNG.
Usage: python tests/make_slim.py <big.docx> tests/fixtures/premier_report_slim.docx"""
import base64
import sys
import zipfile

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

src, dst = sys.argv[1:3]
with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
    for item in zi.infolist():
        zo.writestr(item.filename, PNG if item.filename.startswith("word/media/") else zi.read(item.filename))
