import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import time
import os
import json
import re
import mysql.connector
from dotenv import load_dotenv

# Panggil load_dotenv() sekali di awal skrip
load_dotenv()

def safe_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"[ERROR] {func.__name__} gagal: {e}")
        return pd.DataFrame(columns=["Tanggal", "Nama Media", "Judul", "Link"])

def get_search_results_antaranews(keyword, max_pages, retries, timeout):
    base_url = f"https://lampung.antaranews.com/search?q={keyword}&page="

    # List penampung data
    tanggal_list = []
    nama_media_list = []
    judul_list = []
    link_list = []

    for page in range(1, max_pages + 1):
        url = base_url + str(page)
        response = None

        # --- Bagian request dengan retry ---
        for attempt in range(retries):
            try:
                response = requests.get(url, timeout=timeout)
                response.raise_for_status()
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                print(f"[Page {page}] Attempt {attempt+1} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    print(f"[Page {page}] Gagal total. Skip halaman ini.")
                    response = None
            except requests.RequestException as e:
                print(f"[Page {page}] Request fatal: {e}")
                response = None
                break

        if response is None:
            continue  # langsung skip halaman ini

        # --- Parsing HTML ---
        try:
            soup = BeautifulSoup(response.content, 'html.parser')
            col_md8 = soup.find('div', class_='col-md-8')

            if not col_md8:
                print(f"[Page {page}] Struktur HTML tidak sesuai, skip.")
                continue

            h3_tags = col_md8.find_all('h3', limit=10)
            p_tags = col_md8.find_all('p', limit=10)

            for h3, p in zip(h3_tags, p_tags):
                link = h3.find('a', href=True)
                if not link or 'berita' not in link['href']:
                    continue

                tautan = link['href']
                judul = link.get('title', link.get_text(strip=True))

                span = p.find('span')
                if span:
                    tanggal_text = span.get_text(strip=True)
                    try:
                        if "jam" in tanggal_text.lower():
                            tanggal_format = (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d")
                        else:
                            tanggal_text_clean = re.sub(r'Wib.*', '', tanggal_text, flags=re.IGNORECASE).strip()
                            dt = datetime.strptime(tanggal_text_clean, "%d %B %Y %H:%M")
                            tanggal_format = dt.strftime("%Y-%m-%d")
                    except Exception:
                        tanggal_format = None
                else:
                    tanggal_format = None

                # Append ke list
                tanggal_list.append(tanggal_format)
                nama_media_list.append("Antara News")
                judul_list.append(judul)
                link_list.append(tautan)

            # --- Pagination cek ---
            pagination = soup.find('ul', class_='pagination pagination-sm')
            if not pagination:
                break
            next_page = None
            for a_tag in pagination.find_all('a'):
                if a_tag.get('aria-label') == 'Next':
                    next_page = a_tag.get('href')
                    break
            if not next_page:
                break

        except Exception as e:
            print(f"[Page {page}] Parsing error: {e}")
            continue

    # --- DataFrame hasil ---
    df = pd.DataFrame({
        'Tanggal': tanggal_list,
        'Nama Media': nama_media_list,
        'Judul': judul_list,
        'Link': link_list
    }, columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])

    return df

def get_search_results_viva(keyword, max_pages, retries, timeout):
    base_url = "https://lampung.viva.co.id/search?q={keyword}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/115.0 Safari/537.36"
        ),
        "Accept-Language": "id,en;q=0.9",
        "Referer": "https://lampung.viva.co.id/"
    }

    bulan_map = {
        "Januari": "01", "Februari": "02", "Maret": "03", "April": "04",
        "Mei": "05", "Juni": "06", "Juli": "07", "Agustus": "08",
        "September": "09", "Oktober": "10", "November": "11", "Desember": "12"
    }

    tanggal_list, nama_media_list, judul_list, link_list = [], [], [], []

    for page in range(1, max_pages + 1):
        url = base_url.format(keyword=keyword)

        response = None
        # --- Request dengan retry ---
        for attempt in range(retries):
            try:
                response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)

                if response.status_code == 200:
                    break
                elif response.status_code == 404:
                    print(f"[Page {page}] Tidak ada hasil untuk keyword ini (404). URL: {url}")
                    response = None
                    break
                else:
                    print(f"[Page {page}] Status code {response.status_code}, skip. URL: {url}")
                    response = None
                    break

            except (requests.ConnectionError, requests.Timeout) as e:
                print(f"[Page {page}] Attempt {attempt+1} gagal: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    print(f"[Page {page}] Skip halaman ini (gagal total).")
                    response = None

        if response is None:
            continue  # skip halaman ini

        # Debugging: cek apakah URL berubah karena redirect
        if response.url != url:
            print(f"[Page {page}] Redirected ke {response.url}")

        # --- Parsing HTML ---
        try:
            soup = BeautifulSoup(response.text, 'html.parser')
            container = soup.find("div", class_="column-big-container")

            if not container:
                print(f"[Page {page}] Struktur HTML tidak sesuai, skip.")
                continue

            articles = container.find_all("div", class_="article-list-row")
            if not articles:
                print(f"[Page {page}] Tidak ada artikel ditemukan.")
                continue

            for article in articles:
                info = article.find("div", class_="article-list-info content_center")
                if not info:
                    continue

                # Ambil href
                a_tag = info.find("a")
                href = a_tag.get("href") if a_tag else None

                # Ambil judul
                h2_tag = info.find("h2")
                judul = h2_tag.get_text(strip=True) if h2_tag else None

                # Ambil tanggal
                tanggal_format = None
                date_div = info.find("div", class_="article-list-date content_center")
                if date_div:
                    tanggal_text = date_div.get_text(strip=True)
                    try:
                        tanggal_only = tanggal_text.split("|")[0].strip()
                        tgl_parts = tanggal_only.split()
                        if len(tgl_parts) == 3:
                            day = tgl_parts[0].zfill(2)
                            month = bulan_map.get(tgl_parts[1], "01")
                            year = tgl_parts[2]
                            tanggal_format = f"{year}-{month}-{day}"
                    except Exception:
                        tanggal_format = None

                # Append ke list
                tanggal_list.append(tanggal_format)
                nama_media_list.append("Viva Lampung")
                judul_list.append(judul)
                link_list.append(href)

        except Exception as e:
            print(f"[Page {page}] Parsing error: {e}")
            continue

    # --- DataFrame hasil ---
    df = pd.DataFrame({
        'Tanggal': tanggal_list,
        'Nama Media': nama_media_list,
        'Judul': judul_list,
        'Link': link_list
    }, columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])

    return df

def get_search_results_lampungpost(keyword, max_pages, retries, timeout):
    base_url = f"https://lampost.co/page/{{}}/?s={keyword}"

    # List penampung data
    tanggal_list = []
    nama_media_list = []
    judul_list = []
    link_list = []

    for page in range(1, max_pages + 1):
        url = base_url.format(page)
        response = None

        # --- Request dengan retry ---
        for attempt in range(retries):
            try:
                response = requests.get(url, timeout=timeout)
                response.raise_for_status()
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                print(f"[Page {page}] Attempt {attempt+1} gagal: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    print(f"[Page {page}] Skip halaman ini (gagal total).")
                    response = None
            except requests.RequestException as e:
                print(f"[Page {page}] Request fatal: {e}")
                response = None
                break

        if response is None:
            continue  # skip halaman ini

        # --- Parsing HTML ---
        try:
            soup = BeautifulSoup(response.content, 'html.parser')
            articles = soup.find_all("article", class_="jeg_post")

            if not articles:
                print(f"[Page {page}] Tidak ada artikel ditemukan, skip.")
                continue

            for art in articles:
                try:
                    # Ambil link & judul
                    title_tag = art.find("h3", class_="jeg_post_title")
                    a_tag = title_tag.find("a") if title_tag else None
                    if not a_tag:
                        continue

                    judul = a_tag.get_text(strip=True)
                    link = a_tag.get("href")

                    # Ambil tanggal
                    tanggal_format = None
                    date_tag = art.find("div", class_="jeg_meta_date")
                    a_date = date_tag.find("a") if date_tag else None
                    if a_date:
                        tanggal_raw = a_date.get_text(strip=True)
                        try:
                            tanggal_format = datetime.strptime(
                                tanggal_raw, "%d/%m/%Y"
                            ).strftime("%Y-%m-%d")
                        except Exception:
                            tanggal_format = None

                    # Append ke list
                    tanggal_list.append(tanggal_format)
                    nama_media_list.append("Lampung Post")
                    judul_list.append(judul)
                    link_list.append(link)

                except Exception as e:
                    print(f"[Page {page}] Error parsing artikel: {e}")
                    continue

            # --- Pagination cek ---
            pagination_div = soup.find("div", class_="jeg_navigation")
            if not pagination_div:
                break

        except Exception as e:
            print(f"[Page {page}] Parsing error: {e}")
            continue

    # --- DataFrame hasil ---
    df = pd.DataFrame({
        'Tanggal': tanggal_list,
        'Nama Media': nama_media_list,
        'Judul': judul_list,
        'Link': link_list
    }, columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])

    return df

def get_search_results_sinarlampung(keyword, max_pages, retries, timeout):
    base_url = f"https://sinarlampung.co/search/?q={keyword}&page="

    # List penampung data
    tanggal_list = []
    nama_media_list = []
    judul_list = []
    link_list = []

    page = 1
    while page <= max_pages:
        url = base_url + str(page)
        response = None

        # --- Request dengan retry ---
        for attempt in range(retries):
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                }
                response = requests.get(url, headers=headers, timeout=timeout)
                response.raise_for_status()
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                print(f"[Page {page}] Attempt {attempt+1} gagal: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    print(f"[Page {page}] Skip halaman ini (gagal total).")
                    response = None
            except requests.RequestException as e:
                print(f"[Page {page}] Request fatal: {e}")
                response = None
                break

        if response is None:
            page += 1
            continue

        # --- Parsing HTML ---
        try:
            soup = BeautifulSoup(response.content, 'html.parser')
            articles = soup.find_all(
                "article",
                class_="flex flex-col md:flex-row gap-4 bg-[#1e293b] rounded-lg overflow-hidden hover:bg-[#1e293b]/80 transition-colors duration-300 shadow-md group"
            )

            if not articles:
                print(f"[Page {page}] Tidak ada artikel ditemukan.")
                break

            for art in articles:
                try:
                    # href
                    link_tag = art.find("a", class_="block h-full")
                    href = "https://sinarlampung.co" + link_tag["href"] if link_tag and link_tag.has_attr("href") else None

                    # judul (pakai alt gambar)
                    img_tag = art.find("img")
                    judul = img_tag["alt"] if img_tag and img_tag.has_attr("alt") else None

                    # tanggal
                    date_str = None
                    time_tag = art.find("time")
                    if time_tag and time_tag.has_attr("datetime"):
                        try:
                            date_str = time_tag["datetime"].split("T")[0]
                        except Exception:
                            date_str = None

                    # Append ke list
                    tanggal_list.append(date_str)
                    nama_media_list.append("Sinar Lampung")
                    judul_list.append(judul)
                    link_list.append(href)

                except Exception as e:
                    print(f"[Page {page}] Error parsing artikel: {e}")
                    continue

            # Deteksi pagination
            has_pagination = soup.find("div", class_="flex justify-center mt-8") is not None
            if has_pagination:
                page += 1
            else:
                break

        except Exception as e:
            print(f"[Page {page}] Parsing error: {e}")
            break

    # --- DataFrame hasil ---
    df = pd.DataFrame({
        'Tanggal': tanggal_list,
        'Nama Media': nama_media_list,
        'Judul': judul_list,
        'Link': link_list
    }, columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])

    return df

def get_search_results_detiksumbagsel(keyword, max_pages, timeout):
    page = 1
    bulan_map = {
        "Janu": "01", "Feb": "02", "Mar": "03", "Apr": "04",
        "Mei": "05", "Jun": "06", "Jul": "07", "Agu": "08",
        "Sep": "09", "Okt": "10", "Nov": "11", "Des": "12"
    }
    # List penampung data
    tanggal_list = []
    nama_media_list = []
    judul_list = []
    link_list = []

    try:
        while page <= max_pages:
            try:
                url = f"https://www.detik.com/search/searchall?query={keyword}&page={page}&result_type=relevansi&siteid=154"
                response = requests.get(url, timeout=timeout)
                response.raise_for_status()
            except Exception as e:
                print(f"Error fetching page {page}: {e}")
                break

            soup = BeautifulSoup(response.content, 'html.parser')

            for article in soup.select("article.list-content__item"):
                try:
                    # Judul & Link
                    a_tag = article.select_one("h3.media__title a")
                    if not a_tag:
                        continue
                    dtr_ttl = a_tag.get("dtr-ttl", "").strip()
                    href = a_tag.get("href", "").strip()

                    # Nama media
                    nama_media_tag = article.select_one("h2.media__subtitle")
                    nama_media = nama_media_tag.get_text(strip=True) if nama_media_tag else ""

                    # Tanggal
                    span_tag = article.select_one(".media__date span")
                    title_date = span_tag.get("title", "").strip() if span_tag else ""

                    tanggal_format = ""
                    if title_date:
                        parts = title_date.split()
                        if len(parts) >= 4:
                            day = parts[1]
                            month = bulan_map.get(parts[2], "01")
                            year = parts[3]
                            tanggal_format = f"{year}-{month}-{day}"

                    # Append ke list
                    tanggal_list.append(tanggal_format)
                    nama_media_list.append(nama_media)
                    judul_list.append(dtr_ttl)
                    link_list.append(href)

                except Exception as e:
                    print(f"Error parsing article on page {page}: {e}")
                    continue

            # Pengecekan pagination
            pagination = soup.find("div", class_="pagination")
            if pagination:
                page_numbers = []
                for a in pagination.find_all("a", class_="itp-pagination"):
                    try:
                        page_numbers.append(int(a.get_text(strip=True)))
                    except ValueError:
                        pass
                if page_numbers:
                    last_page = max(page_numbers)
                    if page < last_page:
                        page += 1
                    else:
                        break
                else:
                    break
            else:
                break
    except Exception as e:
        print(f"Unexpected error: {e}")

    # Buat DataFrame, meskipun kosong tetap return
    data = {
        'Tanggal': tanggal_list,
        'Nama Media': nama_media_list,
        'Judul': judul_list,
        'Link': link_list
    }
    df = pd.DataFrame(data, columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])
    return df
      
def get_search_results_harianlampung(keyword, max_pages, timeout):
    base_url = f"https://harianlampung.id/page/{{}}/?s={keyword}&post_type%5B%5D=post"

    # List penampung data
    tanggal_list = []
    nama_media_list = []
    judul_list = []
    link_list = []

    for page in range(1, max_pages + 1):
        url = base_url.format(page)
        response = requests.get(url, timeout=timeout)

        if response.status_code != 200:
            break

        soup = BeautifulSoup(response.content, 'html.parser')
        articles = soup.find_all("article", class_="post")

        if not articles:
            break  # kalau tidak ada artikel, stop loop

        for art in articles:
            # Judul & Link
            title_tag = art.find("h2", class_="entry-title")
            if title_tag and title_tag.a:
                title = title_tag.a.get_text(strip=True)
                link = title_tag.a["href"]
            else:
                continue  # skip kalau tidak ada judul

            # Tanggal
            date_formatted = None
            time_tag = art.find("time", class_="published")
            if time_tag and time_tag.get("datetime"):
                try:
                    date_formatted = datetime.fromisoformat(
                        time_tag["datetime"].replace("Z", "+00:00")
                    ).strftime("%Y-%m-%d")
                except Exception:
                    date_formatted = None

            nama_media = "Harian Lampung"

            # Append ke list
            tanggal_list.append(date_formatted)
            nama_media_list.append(nama_media)
            judul_list.append(title)
            link_list.append(link)

    # Buat DataFrame
    data = {
        'Tanggal': tanggal_list,
        'Nama Media': nama_media_list,
        'Judul': judul_list,
        'Link': link_list
    }
    df = pd.DataFrame(data, columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])

    return df

def get_search_results_harianfajarlampung(keyword, timeout):
    base_url = f"https://harianfajarlampung.co.id/?s={keyword}&post_type=post"

    # List penampung data
    tanggal_list = []
    nama_media_list = []
    judul_list = []
    link_list = []

    try:
        response = requests.get(base_url, timeout=timeout)
        response.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Gagal request Harian Fajar Lampung: {e}")
        return pd.DataFrame(columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])

    try:
        soup = BeautifulSoup(response.content, 'html.parser')

        for article in soup.find_all("article"):
            try:
                # tanggal
                tanggal_raw = article.select_one("time")["datetime"]
                tanggal = datetime.fromisoformat(
                    tanggal_raw.replace("Z", "+00:00")
                ).strftime("%Y-%m-%d")

                # judul & link
                judul_tag = article.select_one("h2.entry-title a")
                judul = judul_tag.get_text(strip=True) if judul_tag else None
                link = judul_tag["href"] if judul_tag else None

                if not judul or not link:
                    continue  # skip artikel yang tidak lengkap

                nama_media = "Harian Fajar Lampung"
                tanggal_list.append(tanggal)
                nama_media_list.append(nama_media)
                judul_list.append(judul)
                link_list.append(link)

            except Exception as e:
                print(f"[WARNING] Gagal parsing artikel Harian Fajar Lampung: {e}")
                continue

    except Exception as e:
        print(f"[ERROR] Gagal parsing halaman Harian Fajar Lampung: {e}")

    # Buat DataFrame
    data = {
        'Tanggal': tanggal_list,
        'Nama Media': nama_media_list,
        'Judul': judul_list,
        'Link': link_list
    }
    df = pd.DataFrame(data, columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])

    return df

def get_search_results_serambilampung(keyword, max_pages, timeout):
    page = 1

    tanggal_list = []
    nama_media_list = []
    judul_list = []
    link_list = []

    bulan_map = {
        "Januari": "01", "Februari": "02", "Maret": "03", "April": "04",
        "Mei": "05", "Juni": "06", "Juli": "07", "Agustus": "08",
        "September": "09", "Oktober": "10", "November": "11", "Desember": "12"
    }

    try:
        while page <= max_pages:
            url = f"https://serambilampung.com/page/{page}/?s={keyword}"
            response = requests.get(url, timeout=timeout)

            if response.status_code != 200:
                break

            soup = BeautifulSoup(response.content, 'html.parser')
            articles = soup.find_all("div", class_="category-text-wrap")

            for art in articles:
                try:
                    a_tag = art.find("h2").find("a")
                    title = a_tag.get_text(strip=True)
                    link = a_tag["href"]

                    span_tag = art.find("p", class_="category-kategori").find("span")
                    raw_date = span_tag.get_text(strip=True)

                    # Ambil tanggal
                    date_part = raw_date.split("-")[0].strip()
                    date_only = date_part.split(", ")[-1]

                    parts = date_only.split(" ")
                    if len(parts) == 3:
                        day, month_name, year = parts
                        month_num = bulan_map.get(month_name, "01")
                        date_str = f"{year}-{month_num}-{day.zfill(2)}"
                    else:
                        date_str = None

                    tanggal_list.append(date_str)
                    nama_media_list.append("Serambi Lampung")
                    judul_list.append(title)
                    link_list.append(link)
                except Exception:
                    continue  # skip artikel rusak

            # cek pagination
            if soup.find("div", class_="navigation"):
                page += 1
            else:
                break

    except Exception:
        pass  # kalau request/parsing gagal total

    # Buat DataFrame (meski kosong tetap aman)
    df = pd.DataFrame({
        'Tanggal': tanggal_list,
        'Nama Media': nama_media_list,
        'Judul': judul_list,
        'Link': link_list
    }, columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])

    return df

def get_search_results_gemamedia(keyword, max_pages, timeout):
    page = 1

    # List penampung data
    tanggal_list = []
    nama_media_list = []
    judul_list = []
    link_list = []

    bulan_map = {
        "Januari": "01", "Februari": "02", "Maret": "03", "April": "04",
        "Mei": "05", "Juni": "06", "Juli": "07", "Agustus": "08",
        "September": "09", "Oktober": "10", "November": "11", "Desember": "12"
    }

    try:
        while page <= max_pages:
            url = f"https://gemamedia.co/page/{page}/?s={keyword}"
            try:
                response = requests.get(url, timeout=timeout)
            except requests.RequestException:
                break  # kalau timeout/error jaringan, stop

            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                articles = soup.find_all("article", class_="d-md-flex mg-posts-sec-post")

                for art in articles:
                    try:
                        # Link (ambil dari a.link-div kalau ada, kalau tidak dari h4 a)
                        link_tag = art.select_one("a.link-div") or art.select_one("h4.entry-title a")
                        link = link_tag.get("href") if link_tag else None
                        
                        # Judul
                        title_tag = art.select_one("h4.entry-title a")
                        title = title_tag.get_text(strip=True) if title_tag else None
                        
                        # Tanggal (format YYYY-MM-DD)
                        date_tag = art.select_one("span.mg-blog-date a")
                        if date_tag:
                            tanggal_raw = date_tag.get_text(strip=True).replace(",", "")
                            parts = tanggal_raw.split()
                            if len(parts) == 3:
                                bulan = bulan_map.get(parts[0], "01")
                                hari = parts[1].zfill(2)
                                tahun = parts[2]
                                tanggal_format = f"{tahun}-{bulan}-{hari}"
                            else:
                                tanggal_format = None
                        else:
                            tanggal_format = None
                        
                        nama_media = "Gema Media"

                        # Append ke list
                        tanggal_list.append(tanggal_format)
                        nama_media_list.append(nama_media)
                        judul_list.append(title)
                        link_list.append(link)
                    
                    except Exception:
                        # kalau ada 1 artikel rusak, skip aja
                        continue
                        
                # Deteksi pagination
                has_pagination = soup.find("div", class_="navigation") is not None

                if has_pagination:
                    page += 1
                else:
                    break
            else:
                break
    except Exception:
        pass  # kalau error besar, diamkan dan return df kosong

    # Buat DataFrame
    data = {
        'Tanggal': tanggal_list,
        'Nama Media': nama_media_list,
        'Judul': judul_list,
        'Link': link_list
    }
    df = pd.DataFrame(data, columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])

    return df

def get_search_results_infolampung(keyword, max_pages, timeout):
    page = 1

    # List penampung data
    tanggal_list = []
    nama_media_list = []
    judul_list = []
    link_list = []

    try:
        while page <= max_pages:
            url = f"https://www.infolampung.id/page/{page}/?s={keyword}"
            try:
                response = requests.get(url, timeout=timeout)
            except Exception:
                break  # kalau request error → berhenti

            if response.status_code == 200:
                try:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    items = soup.select("div.category-text-wrap")

                    for item in items:
                        # Judul & Link
                        a_tag = item.select_one("h2 a")
                        judul = a_tag.get_text(strip=True) if a_tag else None
                        link = a_tag["href"] if a_tag else None

                        # Tanggal
                        tgl_format = None
                        tgl_tag = item.select_one("div.tanggal-mobile")
                        if tgl_tag:
                            try:
                                tgl_raw = tgl_tag.get_text(strip=True)
                                tgl_parts = tgl_raw.split("-")[0].strip()  # contoh: "Wednesday, 16 July 2025"
                                tgl_parts = " ".join(tgl_parts.split()[1:])  # buang hari → "16 July 2025"
                                tgl_obj = datetime.strptime(tgl_parts, "%d %B %Y")
                                tgl_format = tgl_obj.strftime("%Y-%m-%d")
                            except Exception:
                                tgl_format = None

                        nama_media = "Info Lampung"
                        # Append ke list
                        tanggal_list.append(tgl_format)
                        nama_media_list.append(nama_media)
                        judul_list.append(judul)
                        link_list.append(link)

                    # Deteksi pagination
                    has_pagination = soup.find("div", class_="navigation") is not None
                    if has_pagination:
                        page += 1
                    else:
                        break
                except Exception:
                    break  # kalau parsing halaman error → stop loop
            else:
                break
    except Exception:
        pass  # kalau ada error besar → biarin aja, return df kosong

    # Buat DataFrame
    data = {
        'Tanggal': tanggal_list,
        'Nama Media': nama_media_list,
        'Judul': judul_list,
        'Link': link_list
    }
    df = pd.DataFrame(data, columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])
    return df

def get_search_results_lampungdalamberita(keyword, max_pages, timeout):
    # List penampung data
    tanggal_list, nama_media_list, judul_list, link_list = [], [], [], []

    for page in range(1, max_pages + 1):
        url = f"https://lampungdalamberita.com/page/{page}/?s={keyword}"
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException:
            break  # stop kalau error koneksi / timeout

        soup = BeautifulSoup(response.content, 'html.parser')
        articles = soup.find_all("article", class_="hentry")

        if not articles:
            break  # tidak ada artikel lagi

        for art in articles:
            # Judul & link
            title_tag = art.find("h2", class_="post-title")
            if title_tag and title_tag.find("a"):
                title = title_tag.find("a").get_text(strip=True)
                link = title_tag.find("a")["href"]
            else:
                continue

            # Tanggal
            date_tag = art.find("span", class_="updated")
            if date_tag:
                raw_date = date_tag.get_text(strip=True)
                try:
                    date_obj = datetime.strptime(raw_date, "%b %d, %Y")
                except ValueError:
                    try:
                        date_obj = datetime.strptime(raw_date, "%B %d, %Y")  # fallback panjang
                    except ValueError:
                        date_obj = None
                date_str = date_obj.strftime("%Y-%m-%d") if date_obj else None
            else:
                date_str = None

            nama_media = "Lampung Dalam Berita"

            # Append ke list
            tanggal_list.append(date_str)
            nama_media_list.append(nama_media)
            judul_list.append(title)
            link_list.append(link)

        # Deteksi pagination
        pagination = soup.find("div", class_="archive-pagination")
        if not pagination:
            break  # stop kalau tidak ada pagination lagi

    # Buat DataFrame
    df = pd.DataFrame({
        'Tanggal': tanggal_list,
        'Nama Media': nama_media_list,
        'Judul': judul_list,
        'Link': link_list
    }, columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])

    return df

def get_search_results_katalampung(keyword, max_pages, timeout):
    try:
        page = 0

        # List penampung data
        tanggal_list = []
        nama_media_list = []
        judul_list = []
        link_list = []
        
        bulan_map = {
            "Januari": "01", "Februari": "02", "Maret": "03", "April": "04",
            "Mei": "05", "Juni": "06", "Juli": "07", "Agustus": "08",
            "September": "09", "Oktober": "10", "November": "11", "Desember": "12"
        }

        maxp = max_pages * 20
        while page <= maxp:
            url = f"https://www.katalampung.com/search?q={keyword}&max-results=20&start={page}&by-date=false"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/139.0.0.0 Safari/537.36"
            }
            try:
                response = requests.get(url, headers=headers, timeout=timeout)
                response.raise_for_status()
            except Exception:
                break

            soup = BeautifulSoup(response.content, 'html.parser')
            posts = soup.find_all("div", class_="post-outer")
            for post in posts:
                try:
                    title_tag = post.find("h2", class_="post-title").a
                    title = title_tag.get_text(strip=True)
                    link = title_tag["href"]

                    # Tanggal
                    date_tag = post.find("abbr", class_="published")
                    if date_tag:
                        raw_date = date_tag.get_text(strip=True)
                        # Pecah tanggal format "Agustus 06, 2022"
                        parts = raw_date.replace(",", "").split()
                        if len(parts) == 3:
                            bulan = bulan_map.get(parts[0], "01")
                            day = parts[1].zfill(2)
                            year = parts[2]
                            tanggal_fix = f"{year}-{bulan}-{day}"
                        else:
                            tanggal_fix = None
                    else:
                        tanggal_fix = None
                    
                    nama_media = "Kata Lampung"
                    # Append ke list
                    tanggal_list.append(tanggal_fix)
                    nama_media_list.append(nama_media)
                    judul_list.append(title)
                    link_list.append(link)

                except Exception:
                    continue
                        
            # Deteksi pagination
            has_pagination = soup.find("div", class_="blog-pager") is not None
            if has_pagination:
                page += 20
            else:
                break

        # Buat DataFrame
        data = {
            'Tanggal': tanggal_list,
            'Nama Media': nama_media_list,
            'Judul': judul_list,
            'Link': link_list
        }
        df = pd.DataFrame(data, columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])
        return df

    except Exception:
        # Kalau ada error besar, tetap return df kosong
        return pd.DataFrame(columns=['Tanggal', 'Nama Media', 'Judul', 'Link'])


def insert_news_to_db(judul, tanggal_berita, link, sumber):
    """Insert satu berita ke MySQL database jika belum ada link yang sama."""
    try:
        # Ambil kredensial dari variabel lingkungan
        db_host = os.getenv("DB_HOST")
        db_user = os.getenv("DB_USER")
        db_password = os.getenv("DB_PASSWORD")
        db_database = os.getenv("DB_DATABASE")

        # Gunakan variabel untuk membuat koneksi
        conn = mysql.connector.connect(
            host=db_host,
            user=db_user,
            password=db_password,
            database=db_database
        )
        cursor = conn.cursor()

        # Cek apakah link sudah ada
        cursor.execute("SELECT COUNT(*) FROM news WHERE link = %s", (link,))
        (count,) = cursor.fetchone()

        today_str = datetime.now().strftime("%Y-%m-%d")

        if count > 0:
            # Update tanggal_update jika link sudah ada
            update_query = """
                UPDATE news
                SET tanggal_update = %s
                WHERE link = %s
            """
            cursor.execute(update_query, (today_str, link))
        else:
            # Insert data baru
            insert_query = """
                INSERT INTO news (nama, tanggal_berita, tanggal_update, link, sumber)
                VALUES (%s, %s, %s, %s, %s)
            """
            values = (
                judul,
                tanggal_berita,
                today_str,
                link,
                sumber
            )
            cursor.execute(insert_query, values)

        conn.commit()

    except mysql.connector.Error as err:
        print(f"Error: {err}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
            
def main():
    keyword = "DTSEN"
    max_pages = 10
    retries = 3
    timeout = 40

    df_antaranews = safe_call(get_search_results_antaranews, keyword, max_pages, retries, timeout)
    df_viva = safe_call(get_search_results_viva, keyword, max_pages, retries, timeout)
    df_lampungpost = safe_call(get_search_results_lampungpost, keyword, max_pages, retries, timeout)
    df_sinarlampung = safe_call(get_search_results_sinarlampung, keyword, max_pages, retries, timeout)
    df_detiksumbagsel = safe_call(get_search_results_detiksumbagsel, keyword, max_pages, timeout)
    df_harianlampung = safe_call(get_search_results_harianlampung, keyword, max_pages, timeout)
    df_harianfajarlampung = safe_call(get_search_results_harianfajarlampung, keyword, timeout)
    df_serambilampung = safe_call(get_search_results_serambilampung, keyword, max_pages, timeout)
    df_gemamedia = safe_call(get_search_results_gemamedia, keyword, max_pages, timeout)
    df_infolampung = safe_call(get_search_results_infolampung, keyword, max_pages, timeout)
    df_lampungdalamberita = safe_call(get_search_results_lampungdalamberita, keyword, max_pages, timeout)
    df_katalampung = safe_call(get_search_results_katalampung, keyword, max_pages, timeout)


    df_list = [
        df_antaranews, df_viva, df_lampungpost, df_detiksumbagsel, df_sinarlampung,
        df_harianlampung, df_harianfajarlampung, df_serambilampung, df_gemamedia,
        df_infolampung, df_lampungdalamberita, df_katalampung
    ]

    df_nonempty = [df for df in df_list if len(df) > 0]

    if df_nonempty:
        df_final = pd.concat(df_nonempty, ignore_index=True)
    else:
        df_final = pd.DataFrame(columns=["Tanggal", "Nama Media", "Judul", "Link"])

    df_final = df_final.drop_duplicates(subset=['Link'])
    df_final["Tanggal"] = pd.to_datetime(df_final["Tanggal"], errors="coerce")
    df_final = df_final.sort_values(by="Tanggal", ascending=False)
    df_final = df_final.reset_index(drop=True)

    # Masukkan ke DB
    for _, row in df_final.iterrows():
        if pd.isnull(row["Tanggal"]):
            tanggal_str = None
        else:
            tanggal_str = row["Tanggal"].strftime("%Y-%m-%d")
        insert_news_to_db(
            judul=row["Judul"],
            tanggal_berita=tanggal_str,
            link=row["Link"],
            sumber=row["Nama Media"]
        )

    print(f"{len(df_final)} berita berhasil diproses & dimasukkan ke DB.")

# =======================
# Jalankan script
# =======================
def run_scraper():
    main()

if __name__ == "__main__":
    run_scraper()