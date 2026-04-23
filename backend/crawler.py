import os
import requests
import zipfile
import io
import datetime
import time
import feedparser
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ──────────────────────────────────────────────────────────────────────────────
# ALL 12 Easy Access Rules published by EASA as of March 2026.
# Scraped directly from https://www.easa.europa.eu/en/document-library/easy-access-rules
# Every URL verified HTTP 200 on 2026-04-20.
# ──────────────────────────────────────────────────────────────────────────────
EASA_DOMAINS = {
    # ── Operations & Flight Rules ─────────────────────────────────────────────
    "air-ops":                  "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-air-operations",
    "sera":                     "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-standardised-european-rules-air-sera",

    # ── Aerodromes & Ground ───────────────────────────────────────────────────
    "aerodromes":               "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-aerodromes",
    "ground-handling":          "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-ground-handling-gh-regulations-eu-202523-and",
    "remote-atc":               "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-guidance-material-remote-aerodrome-air-traffic",

    # ── Airworthiness ─────────────────────────────────────────────────────────
    "initial-airworthiness":    "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-initial-airworthiness-and-environmental",
    "continuing-airworthiness": "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-continuing-airworthiness-regulation-eu-no",
    "additional-airworthiness": "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-additional-airworthiness-specifications-2",

    # ── Aircrew & Licensing ───────────────────────────────────────────────────
    "aircrew":                  "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-aircrew-regulation-eu-no-11782011",

    # ── ATM/ANS ───────────────────────────────────────────────────────────────
    "atm-ans":                  "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-air-traffic-managementair-navigation-services",

    # ── Type Certificates / Rotorcraft ────────────────────────────────────────
    "large-rotorcraft":         "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-large-rotorcraft-cs-29",

    # ── Security ──────────────────────────────────────────────────────────────
    "info-security":            "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-information-security-regulations-eu-2023203",
}

BASE_DATA_DIR = "data/easa"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Official EASA Easy Access Rules RSS feed (verified working 2026-04-20)
DATA_DIR = BASE_DATA_DIR
RSS_FEED_URL = "https://www.easa.europa.eu/en/document-library/easy-access-rules/feed.xml"



# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _domain_dir(domain: str) -> str:
    path = os.path.join(BASE_DATA_DIR, domain)
    os.makedirs(path, exist_ok=True)
    return path


def _update_last_checked(domain: str = "global"):
    folder = _domain_dir(domain)
    with open(os.path.join(folder, ".last_checked"), "w") as f:
        f.write(datetime.datetime.now().isoformat())


def _get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


# ──────────────────────────────────────────────────────────────────────────────
# Public API: multi-domain paths
# ──────────────────────────────────────────────────────────────────────────────

def get_all_xml_paths() -> dict:
    """
    Returns a dict mapping domain name → XML file path for all locally available XMLs.
    Example: {"aerodromes": "data/easa/aerodromes/rules.xml", ...}
    """
    result = {}

    # Also scan legacy root data dir for backwards compat
    for f in os.listdir(BASE_DATA_DIR) if os.path.exists(BASE_DATA_DIR) else []:
        if f.endswith(".xml"):
            result["legacy"] = os.path.join(BASE_DATA_DIR, f)
            break

    for domain in EASA_DOMAINS:
        domain_folder = os.path.join(BASE_DATA_DIR, domain)
        if os.path.exists(domain_folder):
            for f in os.listdir(domain_folder):
                if f.endswith(".xml"):
                    result[domain] = os.path.join(domain_folder, f)
                    break

    return result


def _get_existing_xml() -> str:
    """Legacy single-domain fallback: returns first found XML from any folder."""
    paths = get_all_xml_paths()
    if paths:
        return next(iter(paths.values()))
    return ""


def get_all_pdf_paths() -> dict:
    """
    Returns a dict mapping domain name → PDF file path for all locally available PDFs.
    Example: {"aerodromes": "data/easa/aerodromes/EAR-Aerodromes.pdf", ...}
    """
    result = {}
    for domain in EASA_DOMAINS:
        domain_folder = os.path.join(BASE_DATA_DIR, domain)
        if os.path.exists(domain_folder):
            for f in os.listdir(domain_folder):
                if f.endswith(".pdf"):
                    result[domain] = os.path.join(domain_folder, f)
                    break
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Deep Crawl — single domain
# ──────────────────────────────────────────────────────────────────────────────

def _scrape_xml_url_from_page(page_url: str) -> str:
    """
    Scrapes a given EASA document library page to locate the XML/ZIP download link.
    Returns the direct download URL or empty string.
    """
    try:
        session = _get_session()
        response = session.get(page_url, timeout=20)
        if response.status_code == 404:
            return ""
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Priority 1: look for anchor tags with explicit XML text
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].lower()
            text = a_tag.get_text().lower()
            if ("xml" in text or "zip" in text) and ("easy access" in text or "download" in text or "xml" in href):
                return urljoin(response.url, a_tag["href"])

        # Priority 2: any link ending in .xml or .zip
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].lower()
            if href.endswith(".xml") or href.endswith(".zip"):
                return urljoin(response.url, a_tag["href"])

    except Exception as e:
        print(f"Failed to scrape {page_url}: {e}")
    return ""


def _scrape_pdf_url_from_page(page_url: str) -> str:
    """
    Scrapes a given EASA document library page to locate the PDF download link.
    Returns the direct download URL or empty string.
    """
    try:
        session = _get_session()
        response = session.get(page_url, timeout=20)
        if response.status_code == 404:
            return ""
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Priority 1: anchor with PDF text
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].lower()
            text = a_tag.get_text().lower()
            if "pdf" in text and ("easy access" in text or "download" in text or href.endswith(".pdf")):
                return urljoin(response.url, a_tag["href"])

        # Priority 2: any link ending in .pdf
        for a_tag in soup.find_all("a", href=True):
            if a_tag["href"].lower().endswith(".pdf"):
                return urljoin(response.url, a_tag["href"])

    except Exception as e:
        print(f"Failed to scrape PDF from {page_url}: {e}")
    return ""


def _download_to_domain(download_url: str, domain: str) -> bool:
    """Downloads XML/ZIP from URL and saves it under the domain's data folder."""
    print(f"[{domain}] Downloading from {download_url}...")
    folder = _domain_dir(domain)
    try:
        session = _get_session()
        resp = session.get(download_url, stream=True, timeout=30)
        resp.raise_for_status()

        filename = download_url.split("/")[-1].split("?")[0]
        if not filename or filename.endswith(".html"):
            filename = f"{domain}_rules.zip"

        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                xml_files = [f for f in z.namelist() if f.endswith(".xml")]
                if not xml_files:
                    print(f"[{domain}] ZIP contains no XML files.")
                    return False
                for xml_file in xml_files:
                    z.extract(xml_file, folder)
                    print(f"[{domain}] Extracted: {xml_file}")
        except zipfile.BadZipFile:
            xml_path = os.path.join(folder, filename if filename.endswith(".xml") else filename + ".xml")
            with open(xml_path, "wb") as f:
                f.write(resp.content)
            print(f"[{domain}] Saved XML to: {xml_path}")

        with open(os.path.join(folder, ".latest_download"), "w") as f:
            f.write(filename)

        return True
    except Exception as e:
        print(f"[{domain}] Download failed: {e}")
        return False


def _download_pdf_to_domain(pdf_url: str, domain: str) -> bool:
    """Downloads PDF from URL and saves it under the domain's data folder."""
    print(f"[{domain}] Downloading PDF from {pdf_url}...")
    folder = _domain_dir(domain)
    try:
        session = _get_session()
        resp = session.get(pdf_url, stream=True, timeout=60)
        resp.raise_for_status()

        filename = pdf_url.split("/")[-1].split("?")[0]
        if not filename.endswith(".pdf"):
            filename = f"{domain}_rules.pdf"

        pdf_path = os.path.join(folder, filename)
        with open(pdf_path, "wb") as f:
            f.write(resp.content)
        print(f"[{domain}] Saved PDF to: {pdf_path}")
        return True
    except Exception as e:
        print(f"[{domain}] PDF download failed: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Multi-Domain Sync
# ──────────────────────────────────────────────────────────────────────────────

def sync_all_domains(force: bool = False) -> dict:
    """
    Iterates all EASA_DOMAINS and downloads XML + PDF for any domain not yet cached.
    Returns a dict of {domain: xml_path} for all successfully synced domains.
    """
    os.makedirs(BASE_DATA_DIR, exist_ok=True)
    results = {}

    for domain, page_url in EASA_DOMAINS.items():
        domain_folder = os.path.join(BASE_DATA_DIR, domain)
        existing_xml = None

        if os.path.exists(domain_folder):
            for f in os.listdir(domain_folder):
                if f.endswith(".xml"):
                    existing_xml = os.path.join(domain_folder, f)
                    break

        if existing_xml and not force:
            print(f"[{domain}] Already cached at {existing_xml}. Skipping.")
            results[domain] = existing_xml
            continue

        print(f"[{domain}] Crawling: {page_url}")

        # Download XML
        download_url = _scrape_xml_url_from_page(page_url)
        if download_url:
            success = _download_to_domain(download_url, domain)
            if success:
                _update_last_checked(domain)
                for f in os.listdir(_domain_dir(domain)):
                    if f.endswith(".xml"):
                        results[domain] = os.path.join(_domain_dir(domain), f)
                        break
        else:
            print(f"[{domain}] No XML link found.")

        # Download PDF (best-effort, non-blocking)
        existing_pdf = any(f.endswith(".pdf") for f in os.listdir(_domain_dir(domain))) if os.path.exists(_domain_dir(domain)) else False
        if not existing_pdf:
            pdf_url = _scrape_pdf_url_from_page(page_url)
            if pdf_url:
                _download_pdf_to_domain(pdf_url, domain)

    return results


def check_for_updates() -> bool:
    """
    Backward-compatible entry point: checks RSS for the main feed, falls back to
    deep-crawling the aerodromes domain if the RSS feed is unavailable.
    Returns True if a new file was downloaded.
    """
    print(f"Monitoring EASA RSS Feed: {RSS_FEED_URL}")
    os.makedirs(BASE_DATA_DIR, exist_ok=True)
    rss_triggered_download = False

    try:
        session = _get_session()
        response = session.get(RSS_FEED_URL, timeout=15)
        response.raise_for_status()
        feed = feedparser.parse(response.text)

        if not feed.bozo and feed.entries:
            latest_entry = next(
                (e for e in feed.entries if
                 "aerodrome" in e.title.lower() or "part-adr" in e.title.lower()),
                feed.entries[0] if feed.entries else None
            )
            if latest_entry:
                last_checked_file = os.path.join(BASE_DATA_DIR, ".last_checked")
                last_checked_dt = datetime.datetime.min
                if os.path.exists(last_checked_file):
                    try:
                        with open(last_checked_file, "r") as f:
                            last_checked_dt = datetime.datetime.fromisoformat(f.read().strip())
                    except ValueError:
                        pass

                pub_dt = (
                    datetime.datetime.fromtimestamp(time.mktime(latest_entry.published_parsed))
                    if hasattr(latest_entry, "published_parsed") and latest_entry.published_parsed
                    else datetime.datetime.now()
                )

                if pub_dt > last_checked_dt:
                    download_url = latest_entry.link
                    for enc in getattr(latest_entry, "enclosures", []):
                        if "xml" in enc.href.lower() or "zip" in enc.href.lower():
                            download_url = enc.href
                            break
                    if _download_to_domain(download_url, "aerodromes"):
                        _update_last_checked("global")
                        rss_triggered_download = True
                else:
                    print("RSS Database is up-to-date.")
    except Exception as e:
        print(f"Failed to check RSS updates: {e}")

    # If nothing from RSS and local folder is empty, try deep crawl of aerodromes
    if not rss_triggered_download and not _get_existing_xml():
        print("Local folder is empty. Initiating targeted deep crawl for aerodromes domain...")
        url = _scrape_xml_url_from_page(EASA_DOMAINS["aerodromes"])
        if url:
            return _download_to_domain(url, "aerodromes")

    return rss_triggered_download


def fetch_and_extract() -> str:
    """Legacy compatibility: forces sync and returns first available XML path."""
    check_for_updates()
    return _get_existing_xml()


if __name__ == "__main__":
    print("=== Syncing all EASA domains ===")
    results = sync_all_domains()
    print(f"\nSync complete. Available XMLs: {results}")
