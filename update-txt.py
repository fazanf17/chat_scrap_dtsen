import os
import json

# Path
txt_dir = os.path.abspath("../bahan-chatbot/txt")
output_file = os.path.abspath("../ai-backend/source-chatbot.txt")
meta_file = os.path.abspath("../ai-backend//source-chatbot.txt.meta")

# Ambil daftar file .txt (urut biar konsisten)
current_files = sorted([f for f in os.listdir(txt_dir) if f.endswith(".txt")])

# Fungsi baca metadata lama
def read_meta():
    if os.path.exists(meta_file):
        with open(meta_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

# Fungsi simpan metadata baru
def save_meta(files_list):
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(files_list, f)

# Bandingkan dengan metadata lama
old_meta = read_meta()

if old_meta == current_files and os.path.exists(output_file):
    print("Tidak ada perubahan file. Menggunakan source-chatbot.txt yang lama.")
else:
    print("Perubahan terdeteksi. Menggabungkan ulang semua file...")
    combined_text = ""
    for filename in current_files:
        file_path = os.path.join(txt_dir, filename)
        with open(file_path, "r", encoding="utf-8") as f:
            combined_text += f.read().strip() + "\n\n"
    # Simpan file gabungan
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(combined_text.strip())
    # Simpan metadata baru
    save_meta(current_files)
    print("File gabungan berhasil dibuat:", output_file)
