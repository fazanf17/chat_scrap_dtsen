import streamlit as st
import time
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from google.api_core import exceptions as google_exceptions
import os
import json
import uuid
import hashlib # Untuk membuat hash file
import sys
from dotenv import load_dotenv

# Panggil fungsi load_dotenv() di awal skrip
load_dotenv()

# Matikan telemetry ChromaDB sebelum library di-load
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# Patch juga kalau telemetry tetap nyangkut lewat sentry-sdk
os.environ["DISABLE_SENTRY"] = "True"

# Gunakan sqlite3 versi pysqlite3-binary
try:
    import pysqlite3
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

import chromadb

# (PROMPT_TEMPLATES dan AVAILABLE_MODELS tetap sama)

PROMPT_TEMPLATES = {
    "synthesizer": """Anda adalah asisten AI yang ahli dalam merangkum informasi. Berdasarkan kumpulan informasi berikut, maka rangkum informasi tersebut sehingga menjawab pertanyaan pengguna.
                    Aturan utama:
                    1. Gabungkan informasi yang relevan dan ringkas untuk memberikan jawaban yang padu dan relevan dengan pertanyaan.
                    2. Jawaban harus dalam Bahasa Indonesia yang jelas dan menyesuaikan gaya bahasa pengguna.
                    3. JAWAB SECARA LANGSUNG dan SINGKAT, hindari kalimat pembuka atau penutup yang tidak perlu.
                    4. Batasi jawaban anda tidak lebih dari 200 kata, kecuali diminta.
                        
                        <riwayat_percakapan>
                        {conversation_history}
                        </riwayat_percakapan>
                        
                        <informasi_terkumpul_untuk_pertanyaan_baru>
                        {combined_info}
                        </informasi_terkumpul_untuk_pertanyaan_baru>

                        Pertanyaan Baru Pengguna: {user_question}
                        Jawaban Akhir yang Ringkas:"""
}

AVAILABLE_MODELS = [
    # "models/gemini-2.5-pro",
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-2.0-flash-001",
    "models/gemini-2.0-flash-lite-001",
    "models/gemini-2.0-flash-lite",
    "models/gemini-1.5-flash", 
    "models/gemini-1.5-pro",  
    "models/gemini-1.5-flash-latest"
]


# ======== Chatbot dengan Arsitektur Final (Vector RAG + Fallback) ========
class VectorRAGChatbot:
    def __init__(self, model_names: list, generation_config: dict, safety_settings: dict):
        # (Seluruh isi __init__ tetap sama seperti versi sebelumnya)
        self.generation_config = generation_config
        self.safety_settings = safety_settings
        self.history_path = "history.json"
        self.cache_path = "cache.json"
        self.model_names = model_names
        self.models = self._initialize_models()
        self.current_model_index = 0
        self.db_client = chromadb.PersistentClient(path="./chroma_db")
        self.collection = self.db_client.get_or_create_collection(name="dokumen_utama")
        self.history = self._load_from_json(self.history_path, default=[])
        self.qa_cache = self._load_from_json(self.cache_path, default={})
        if self.models:
            print(f"✅ VectorRAGChatbot berhasil diinisialisasi dengan model utama: '{self.get_current_model().model_name}'")
        else:
            print("❌ Gagal memuat model.")

    # (... Semua fungsi helper seperti _load_from_json, _get_embedding, _initialize_models, dll tetap sama ...)
    # --- Fungsi Helper untuk JSON ---
    def _load_from_json(self, filepath: str, default=None):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    def _save_to_json(self, filepath: str, data):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    # --- Fungsi Helper untuk Embedding ---
    def _get_embedding(self, text: str, task_type: str):
        return genai.embed_content(
            model="models/text-embedding-004", content=text, task_type=task_type
        )["embedding"]

    # --- Fungsi Helper untuk Model Fallback ---
    def _initialize_models(self) -> list:
        models = []
        for name in self.model_names:
            try:
                model = genai.GenerativeModel(
                    model_name=name,
                    generation_config=self.generation_config,
                    safety_settings=self.safety_settings
                )
                models.append(model)
            except Exception as e:
                print(f"⚠️ Peringatan: Gagal memuat model '{name}'. Error: {e}")
        return models

    def get_current_model(self):
        if not self.models: return None
        return self.models[self.current_model_index]

    def _switch_to_next_model(self) -> bool:
        next_index = self.current_model_index + 1
        if next_index < len(self.models):
            self.current_model_index = next_index
            print(f"🔄 Beralih ke model fallback: {self.get_current_model().model_name}")
            return True
        else:
            print("❌ Semua model fallback telah dicoba dan gagal.")
            return False

    def _call_model(self, prompt: str, model) -> str:
        try:
            response = model.generate_content(prompt)
            return response.text if response.parts else "❌ Respons diblokir oleh filter keamanan."
        except Exception as e:
            print(f"🔴 Gagal dengan model '{model.model_name}': {e}")
            raise e

    def _call_model_with_fallback(self, prompt: str) -> str:
        if not self.models: return "❌ Tidak ada model yang bisa digunakan."
        try:
            current_model = self.get_current_model()
            print(f"🧠 Mencoba menghasilkan jawaban dengan: {current_model.model_name}...")
            return self._call_model(prompt, current_model)
        except Exception:
            if self._switch_to_next_model():
                return self._call_model_with_fallback(prompt) # Coba lagi rekursif
            else:
                return "Maaf, semua model sedang mengalami gangguan atau limit. Silakan coba lagi nanti."

    # Di dalam kelas VectorRAGChatbot

    def _is_context_dependent(self, question: str) -> bool:
        """
        Mendeteksi apakah pertanyaan kemungkinan besar bergantung pada konteks.
        Ini adalah pendekatan heuristik sederhana menggunakan kata kunci.
        """
        question = question.lower().strip()
        # Daftar kata kunci yang menandakan ketergantungan pada konteks
        CONTEXT_KEYWORDS = [
            "itu", "tadi", "sebelumnya", "lagi dong", 
            "bagaimana dengan", "kenapa begitu", "maksudnya apa",
            "lebih lanjut", "detailnya"
        ]
        
        # Juga anggap pertanyaan yang sangat pendek sebagai context-dependent
        if len(question.split()) <= 3:
            return True
            
        for keyword in CONTEXT_KEYWORDS:
            if keyword in question:
                print(f"   -> Pertanyaan terdeteksi bergantung pada konteks (keyword: '{keyword}')")
                return True
        return False
    
    # --- TAHAP 1: INDEXING (FUNGSI UTAMA YANG DIMODIFIKASI) ---
    def setup_vector_db(self, folder_path: str):
        """
        Mengindeks semua file .txt dari folder secara cerdas.
        Hanya memproses file yang baru atau yang isinya berubah.
        """
        print(f"🔍 Memulai pemeriksaan dan indexing untuk folder: '{folder_path}'")
        if not os.path.isdir(folder_path):
            print(f"❌ Folder tidak ditemukan di '{folder_path}'")
            return

        # 1. Dapatkan status file saat ini di folder
        current_files = {}
        for filename in os.listdir(folder_path):
            if filename.endswith(".txt"):
                file_path = os.path.join(folder_path, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    current_files[filename] = hashlib.md5(content.encode()).hexdigest()

        # 2. Dapatkan status file yang sudah ada di database
        indexed_files = {}
        if self.collection.count() > 0:
            metadata = self.collection.get(include=["metadatas"])['metadatas']
            for meta in metadata:
                if 'source_file' in meta and 'file_hash' in meta:
                    indexed_files[meta['source_file']] = meta['file_hash']
        
        # 3. Tentukan file yang perlu di-update, ditambah, atau dihapus
        files_to_add = {f: h for f, h in current_files.items() if f not in indexed_files or indexed_files[f] != h}
        files_to_remove = [f for f in indexed_files if f not in current_files]

        # 4. Proses penghapusan file lama dari DB
        if files_to_remove:
            for filename in files_to_remove:
                print(f"🗑️ Menghapus file lama dari DB: '{filename}'")
                self.collection.delete(where={"source_file": filename})

        # 5. Proses penambahan/pembaruan file di DB
        if files_to_add:
            for filename, file_hash in files_to_add.items():
                print(f"➕ Mengindeks file baru atau yang diperbarui: '{filename}'")
                
                # Hapus entri lama jika ini adalah pembaruan
                if filename in indexed_files:
                    self.collection.delete(where={"source_file": filename})

                file_path = os.path.join(folder_path, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    source_text = f.read()

                # Chunking
                chunks = [source_text[i:i+2048] for i in range(0, len(source_text), 1848)]
                
                # Proses embedding dan penyimpanan per chunk
                embeddings, metadatas, ids = [], [], []
                for chunk in chunks:
                    embeddings.append(self._get_embedding(chunk, "RETRIEVAL_DOCUMENT"))
                    metadatas.append({'source_file': filename, 'file_hash': file_hash})
                    ids.append(str(uuid.uuid4()))
                
                if embeddings:
                    self.collection.add(embeddings=embeddings, documents=chunks, metadatas=metadatas, ids=ids)
                    print(f"   -> {len(chunks)} chunk untuk '{filename}' berhasil diindeks.")
        
        if not files_to_add and not files_to_remove:
            print("✅ Database sudah sinkron. Tidak ada file yang perlu diupdate.")
        else:
            print("✅ Proses sinkronisasi database selesai.")


    # --- TAHAP 2: RETRIEVAL & GENERATION ---
    # (Fungsi get_response tidak perlu diubah, karena ia sudah mengambil dari collection yang ter-update)

    def get_response(self, user_question: str) -> str:
        """
        Menjawab pertanyaan dengan alur hibrida: membedakan pertanyaan mandiri dan 
        pertanyaan yang bergantung pada konteks untuk manajemen cache yang cerdas.
        """
        print(f"\n🤖 Memproses pertanyaan baru: '{user_question}'")
        
        # --- LANGKAH 1: DETEKSI SIFAT PERTANYAAN ---
        is_dependent = self._is_context_dependent(user_question)
        normalized_question = user_question.lower().strip()

        # --- JALUR A: PERTANYAAN MANDIRI (MENGGUNAKAN CACHE) ---
        if not is_dependent:
            # Cek cache sederhana terlebih dahulu
            if normalized_question in self.qa_cache:
                print(f"✅ Mengambil jawaban dari cache sederhana untuk: '{user_question}'")
                cached_answer = self.qa_cache[normalized_question]
                self.history.append((user_question, cached_answer))
                self._save_to_json(self.history_path, self.history)
                return cached_answer
        
        # --- LANGKAH 2: PROSES RAG (Retrieval & Generation) ---
        # Proses ini sama untuk kedua jalur, namun hasilnya akan diperlakukan berbeda.
        try:
            print(f"✅ Collection name: {self.collection.name}")
            print(f"📦 Document count: {self.collection.count()}")
            print(f"Berhasil retrieval dari Vector DB!")

            question_embedding = self._get_embedding(user_question, "RETRIEVAL_QUERY")
            results = self.collection.query(
                query_embeddings=[question_embedding], n_results=3
            )
            retrieved_chunks = results['documents'][0]
            # print(retrieved_chunks)
        except Exception as e:
            print(f"❌ Gagal saat retrieval dari Vector DB: {e}")
            return "Maaf, terjadi masalah saat mencari informasi di dalam dokumen."

        if not retrieved_chunks:
            return "Maaf, informasi yang relevan tidak ditemukan di dalam dokumen."

        retrieved_context = "\n\n---\n\n".join(retrieved_chunks)
        history_str = "\n".join([f"Pengguna: {q}\nAsisten: {a}" for q, a in self.history])
        if not history_str:
            history_str = "Tidak ada riwayat percakapan sebelumnya."

        synthesis_prompt = PROMPT_TEMPLATES["synthesizer"].format(
            conversation_history=history_str,
            combined_info=retrieved_context,
            user_question=user_question
        )

        print("   L Menghasilkan jawaban akhir dengan mekanisme fallback...")
        self.current_model_index = 0
        final_answer = self._call_model_with_fallback(synthesis_prompt)
        
        # --- LANGKAH 3: MANAJEMEN PENYIMPANAN CERDAS ---
        INVALID_ANSWER_PREFIXES = ("Maaf,", "❌")
        is_valid_answer = not any(final_answer.strip().startswith(p) for p in INVALID_ANSWER_PREFIXES)

        # Selalu simpan ke riwayat percakapan jika jawaban valid
        if is_valid_answer:
            self.history.append((user_question, final_answer))
            if len(self.history) > 10: self.history.pop(0)
            self._save_to_json(self.history_path, self.history)

            # HANYA simpan ke cache jika pertanyaan adalah mandiri (standalone)
            if not is_dependent:
                print("   L Jawaban valid & mandiri. Menyimpan ke cache...")
                self.qa_cache[normalized_question] = final_answer
                self._save_to_json(self.cache_path, self.qa_cache)
            else:
                print("   L Jawaban valid & bergantung konteks. TIDAK disimpan ke cache.")
        else:
            print(f"   L Jawaban tidak valid ('{final_answer}'). Tidak disimpan ke mana pun.")

        return final_answer


# Akses API_KEY menggunakan os.getenv()
API_KEY = os.getenv("API_KEY")

def init_model():
    try:
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY", API_KEY))
        print("✅ API Key configured!")
    except Exception as e:
        print(f"❌ Gagal mengkonfigurasi API Key: {e}")
        return None

    my_generation_config = {
        "temperature": 0.5, 
        "max_output_tokens": 4096, 
        "top_p": 0.6
    }
    my_safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
    }

    return my_generation_config, my_safety_settings


def init_chatbot():
    my_generation_config, my_safety_settings = init_model()
    if not my_generation_config:
        return None

    chatbot = VectorRAGChatbot(
        model_names=AVAILABLE_MODELS, 
        generation_config=my_generation_config,
        safety_settings=my_safety_settings
    )
    
    # Tentukan folder yang berisi dokumen sumber Anda
    source_folder_path = "bahan-chatbot/txt/"
    chatbot.setup_vector_db(source_folder_path)

    return chatbot


if __name__ == "__main__":
    chatbot = init_chatbot()
