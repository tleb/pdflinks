import argparse
import collections
import multiprocessing.pool
import urllib.parse

import PyPDF2
import requests
import tqdm

TIMEOUT_SECS = 5

# Logging goes through this object which therefore must be passed to workers.
progressbar = None

warn_on_redirects = None

url_to_pdf_mapping = None


def extract_urls_from_pdf(pdf_path):
    global progressbar
    urls = set()

    with open(pdf_path, "rb") as file:
        try:
            reader = PyPDF2.PdfReader(file)
        except Exception:  # PyPDF2.errors.PyPdfError isn't enough
            # TODO: shouldn't the program fail in that case?
            # Maybe only if there is a single PDF?
            progressbar.write(f"reading PDF failed: {pdf_path}")
            return pdf_path, urls

        for page in reader.pages:
            try:
                annots = page["/Annots"]
            except KeyError:
                continue

            for annot_ref in annots:
                annot = annot_ref.get_object()
                if annot.get("/Subtype") != "/Link":
                    continue

                a = annot.get("/A")
                if a and (isinstance(a, str) or isinstance(a, bytes)):
                    urls.add(a)
                elif a and isinstance(a, bytes):
                    urls.add(a.decode("utf-8"))
                elif (
                    a
                    and isinstance(a, PyPDF2.generic._data_structures.DictionaryObject)
                    and a.get("/S") == "/URI"
                    and (uri := a.get("/URI"))
                ):
                    if isinstance(uri, bytes):
                        urls.add(uri.decode("utf-8"))
                    else:
                        urls.add(uri)

    # Drop URL #fragments
    urls = set(urllib.parse.urlparse(u)._replace(fragment="").geturl() for u in urls)
    # Strip whitespace
    urls = set(u.strip() for u in urls)
    return pdf_path, urls


def request_domain_urls(domain_urls):
    global url_to_pdf_mapping
    global progressbar

    def log(msg, url):
        for pdf in url_to_pdf_mapping[url]:
            progressbar.write(f"{pdf}: {msg}")

    headers = {"User-Agent": "git/1.7.1", "Range": "bytes=0-100"}

    for url in domain_urls:
        scheme = urllib.parse.urlparse(url).scheme
        if scheme == "mailto":
            pass  # skip silently
        elif scheme != "https":
            log(f"skipped '{scheme}' request: {url}", url)
        else:
            try:
                response = requests.get(
                    url, allow_redirects=True, timeout=TIMEOUT_SECS, headers=headers
                )
            except IOError:
                log(f"{TIMEOUT_SECS}s timeout: {url}", url)
            else:
                # TODO: if we get a 403 we could retry with a different User-Agent. Example:
                # https://wiki.linuxfoundation.org/civilinfrastructureplatform/start
                code = response.status_code
                if code < 200 or code >= 300:
                    log(f"{code} HTTP code: {url}", url)
                elif response.url != url and warn_on_redirects:
                    log(f"got redirected from '{url}' to '{response.url}'", url)

        progressbar.update()


def main():
    global url_to_pdf_mapping
    global progressbar
    global warn_on_redirects

    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--warn-on-redirects", action="store_true")
    parser.add_argument("-l", "--only-list-urls", action="store_true")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()

    # Extract unique URLs from the PDF
    # urls is a mapping from URLs to PDF files from which they are extracted
    url_to_pdf_mapping = collections.defaultdict(lambda: [])
    progressbar = tqdm.tqdm(args.files, desc="parsing PDFs", leave=False)
    with multiprocessing.pool.Pool() as pool:
        for pdf_path, pdf_urls in pool.imap(extract_urls_from_pdf, progressbar):
            for url in pdf_urls:
                url_to_pdf_mapping[url] += [pdf_path]

    # We group URLs by domain. That way each pool worker is responsible for a full domain
    # and doesn't hammer the server. We sort domains by number of URLs so that domains
    # with many requests start ASAP.
    urls_grouped_by_domain = collections.defaultdict(set)
    for url in url_to_pdf_mapping:
        urls_grouped_by_domain[urllib.parse.urlparse(url).netloc].add(url)
    urls_grouped_by_domain = urls_grouped_by_domain.values()
    urls_grouped_by_domain = sorted(urls_grouped_by_domain, key=len, reverse=True)

    if args.only_list_urls:
        for urls in urls_grouped_by_domain:
            print("\n".join(sorted(urls)))
        return

    # Sadly we cannot use tqdm as it should be, by wrapping an iterator. That is because
    # our pool does one job per domain and not per URL. We need to .update() manually
    # inside the worker.
    progressbar = tqdm.tqdm(desc="requests", total=len(url_to_pdf_mapping), leave=False)
    warn_on_redirects = args.warn_on_redirects
    with multiprocessing.pool.ThreadPool() as pool:
        pool.map(request_domain_urls, urls_grouped_by_domain)
    progressbar.close()
