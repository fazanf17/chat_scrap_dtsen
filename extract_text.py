import sys
from PyPDF2 import PdfReader
import re
import os
import subprocess
import json

if len(sys.argv) != 3:
    print("Usage: python extract_text.py input.pdf output.txt")
    sys.exit(1)

input_pdf = sys.argv[1]
output_txt = sys.argv[2]

def merge_lines(text):
    lines = text.splitlines()
    merged = []
    buffer = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:  # kalau baris kosong → flush buffer
            if buffer:
                merged.append(buffer.strip())
                buffer = ""
            merged.append("")  # simpan baris kosong sebagai pemisah paragraf
            continue

        # Cek apakah baris sebelumnya kemungkinan masih nyambung
        if buffer and not re.search(r'[.!?]$', buffer) and not re.match(r'^\W', stripped):
            buffer += " " + stripped  # lanjutkan
        else:
            if buffer:
                merged.append(buffer.strip())
            buffer = stripped

    # Tambahkan sisa buffer terakhir
    if buffer:
        merged.append(buffer.strip())

    return "\n".join(merged)



# Ambil path folder script ini
current_dir = os.path.dirname(os.path.abspath(__file__))

try:
    reader = PdfReader(input_pdf)
    all_text = ""
    for page in reader.pages:
        page_text = page.extract_text() or ""
        processed = merge_lines(page_text)
        all_text += processed + "\n"

    with open(output_txt, "w", encoding="utf-8") as f:
        f.write(all_text)

    print("success")

    # Path absolut ke update-txt.py
    # update_script = os.path.join(current_dir, "update-txt.py")

    # Jalankan update-txt.py pakai Python yang sama
    # subprocess.run([sys.executable, update_script], check=True)
    # print("✅ update-txt.py berhasil dijalankan")

except Exception as e:
    print("error:", str(e))
    


# try:
#     reader = PdfReader(input_pdf)
#     all_text = ""
#     for page in reader.pages:
#         page_text = page.extract_text() or ""
#         processed = merge_lines(page_text)
#         all_text += processed + "\n"

#     with open(output_txt, "w", encoding="utf-8") as f:
#         f.write(all_text)

#     print("success")
# except Exception as e:
#     print("error:", str(e))