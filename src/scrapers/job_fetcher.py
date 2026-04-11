import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from curl_cffi import requests

from src.errors.base_errors import TokenExpired
from src.models.job_models import Job, JobList
from src.proxies.proxy_manager import WebshareProxyManager
from src.settings.config import PAGE_SIZE

LOGGER = logging.getLogger(__name__)

UPWORK_GRAPHQL_URL = "https://www.upwork.com/api/graphql/v1"
MAX_OFFSET = 5000  # Upwork API caps pagination at offset ~5000
CONCURRENT_WORKERS = 10

GRAPHQL_QUERY = """
query VisitorJobSearch($requestVariables: VisitorJobSearchV1Request!) {
  search {
    universalSearchNuxt {
      visitorJobSearchV1(request: $requestVariables) {
        paging {
          total
          offset
          count
        }
        results {
          id
          title
          description
          ontologySkills {
            prefLabel
          }
          jobTile {
            job {
              id
              ciphertext: cipherText
              jobType
              hourlyBudgetMax
              hourlyBudgetMin
              contractorTier
              publishTime
              hourlyEngagementDuration {
                weeks
              }
              fixedPriceAmount {
                amount
              }
              fixedPriceEngagementDuration {
                weeks
              }
            }
          }
        }
      }
    }
  }
}
"""

HEADERS_BASE = {
    "Accept": "*/*",
    "Accept-Language": "en-GB,en;q=0.7,en-US;q=0.3",
    "Accept-Encoding": "gzip",
    "Referer": "https://www.upwork.com/nx/search/jobs/?",
    "X-Upwork-Accept-Language": "en-US",
    "Content-Type": "application/json",
}


def fetch_jobs_page(
    token: str, proxy_dict: dict, offset: int = 0, count: int = PAGE_SIZE
) -> list[Job]:
    headers = {**HEADERS_BASE, "Authorization": f"Bearer {token}"}
    payload = {
        "query": GRAPHQL_QUERY,
        "variables": {
            "requestVariables": {
                "sort": "recency",
                "highlight": True,
                "paging": {"offset": offset, "count": count},
            }
        },
    }

    resp = requests.post(
        UPWORK_GRAPHQL_URL,
        headers=headers,
        json=payload,
        proxies=proxy_dict,
        impersonate="chrome",
        timeout=20,
    )

    if resp.status_code == 401:
        raise TokenExpired("Upwork returned 401 — token expired")

    resp.raise_for_status()
    job_list = JobList.model_validate(resp.json())
    return job_list.jobs


def fetch_all_jobs(
    token: str, proxy_manager: WebshareProxyManager, max_pages: int = 100
) -> list[Job]:
    # Cap pages to API pagination limit
    max_offset = min(max_pages * PAGE_SIZE, MAX_OFFSET + PAGE_SIZE)
    offsets = list(range(0, max_offset, PAGE_SIZE))

    all_jobs: list[Job] = []
    failed = 0

    def _fetch_page(offset: int) -> tuple[int, list[Job]]:
        proxy = proxy_manager.get_proxy()
        jobs = fetch_jobs_page(token, proxy.to_curl_cffi_dict(), offset=offset)
        return offset, jobs

    with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as pool:
        futures = {pool.submit(_fetch_page, o): o for o in offsets}

        token_expired = None
        for future in as_completed(futures):
            offset = futures[future]
            try:
                _, jobs = future.result()
                all_jobs.extend(jobs)
            except TokenExpired as e:
                token_expired = e
                for f in futures:
                    f.cancel()
                break
            except Exception:
                failed += 1
                LOGGER.warning("Failed to fetch offset %d", offset, exc_info=True)

    if token_expired:
        raise token_expired

    LOGGER.info(
        "Fetched %d jobs from %d pages (%d failed)",
        len(all_jobs), len(offsets) - failed, failed,
    )
    return all_jobs
