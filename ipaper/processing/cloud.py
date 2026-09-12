"""One-shot MinerU precision API operations. Never persist signed URLs or keys."""
from __future__ import annotations
import json
import re
import time
from pathlib import Path

import requests

from ipaper.security.outbound import guarded_request
from ipaper.document_worker.safety import bounded_copy
from .common import ProcessingError


class MinerUCloud:
    BASE = "https://mineru.net/api/v4"
    def __init__(self, token, policy):
        self.token, self.policy = token, policy

    def _json(self, method, path, payload=None):
        # The API host/path are fixed, not configurable model output. Transfer
        # URLs are separately validated against exact configured origins.
        try:
            with requests.request(method, self.BASE + path, json=payload,
                    headers={"Authorization": "Bearer " + self.token},
                    timeout=(10, 30), allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    raise ProcessingError("mineru_http_" + str(response.status_code), 502)
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > 1024**2:
                        raise ProcessingError("mineru_response_too_large", 502)
                value = json.loads(content)
                if not isinstance(value, dict) or value.get("code") != 0 or not isinstance(value.get("data"), dict):
                    raise ProcessingError("mineru_api_rejected", 502)
                return value["data"]
        except ProcessingError:
            raise
        except Exception:
            raise ProcessingError("mineru_response_unknown", 502) from None

    def submit(self, path, unit, jobs, job_id, save_batch):
        attempt = jobs.reserve_attempt(job_id, "cloud_create", unit)
        try:
            data = self._json("POST", "/file-urls/batch", {"files": [{"name": attempt + ".pdf", "data_id": unit}], "model_version": "vlm"})
            batch = data.get("batch_id")
            urls = data.get("file_urls")
            if (not isinstance(batch, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", batch)
                    or not isinstance(urls, list) or len(urls) != 1 or not isinstance(urls[0], str)):
                raise ProcessingError("mineru_response_unknown", 502)
            # Persist accepted identity before the upload. A crash here may
            # leave an unknown create attempt; explicit recovery never creates it again.
            save_batch(batch)
            jobs.finish_attempt(job_id, attempt, "completed", {"batchId": batch})
        except Exception as error:
            definite = isinstance(error,ProcessingError) and error.code in {"mineru_http_400","mineru_http_401","mineru_http_403","mineru_http_429"}
            jobs.finish_attempt(job_id,attempt,"rejected" if definite else "unknown")
            raise
        jobs.check(job_id)
        upload = jobs.reserve_attempt(job_id, "cloud_upload", unit, metadata={"batchId": batch})
        try:
            with Path(path).open("rb") as handle:
                response = guarded_request(self.policy, "PUT", urls[0], purpose="transfer", data=handle, timeout=(10, 120))
            try:
                if response.status_code not in {200, 201, 204}:
                    raise ProcessingError("mineru_upload_rejected", 502)
            finally:
                response.close()
            jobs.finish_attempt(job_id, upload, "completed")
        except Exception:
            jobs.finish_attempt(job_id, upload, "unknown")
            raise ProcessingError("mineru_upload_unknown", 502) from None
        return batch

    def wait_download(self, batch, destination, jobs, job_id):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", batch):
            raise ProcessingError("invalid_mineru_batch")
        started = time.monotonic()
        while time.monotonic() - started < 1800:
            jobs.check(job_id)
            data = self._json("GET", "/extract-results/batch/" + batch)
            items = data.get("extract_result")
            if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
                raise ProcessingError("mineru_result_invalid", 502)
            result = items[0]
            if result.get("state") == "failed":
                raise ProcessingError("mineru_parse_failed", 502)
            if result.get("state") == "done":
                url = result.get("full_zip_url")
                if not isinstance(url, str):
                    raise ProcessingError("mineru_result_invalid", 502)
                jobs.check(job_id)
                try:
                    with guarded_request(self.policy, "GET", url, purpose="transfer", stream=True, timeout=(10, 120)) as response:
                        if response.status_code != 200:
                            raise ProcessingError("mineru_download_rejected", 502)
                        response.raw.decode_content = True
                        bounded_copy(response.raw, destination, 200 * 1024**2)
                except ProcessingError:
                    raise
                except Exception:
                    raise ProcessingError("mineru_download_failed", 502) from None
                return
            for _ in range(50):
                jobs.check(job_id)
                time.sleep(0.2)
        raise ProcessingError("mineru_poll_timeout", 504)
