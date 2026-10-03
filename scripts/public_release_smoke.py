import argparse
import sys

import httpx

from app.public_web.urls import assam_job_path


def first_job_detail_path(payload: object) -> str | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return None
    first = next((item for item in payload["items"] if isinstance(item, dict)), None)
    identifier = first.get("id") if first else None
    display_name = first.get("display_name") if first else None
    if not isinstance(identifier, str) or not identifier or not isinstance(display_name, str):
        return None
    return assam_job_path(identifier, display_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the bounded public deployment")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    failures: list[str] = []
    with httpx.Client(base_url=base_url, timeout=10, follow_redirects=False) as client:
        responses: dict[str, httpx.Response] = {}
        for path in ("/healthz", "/readyz", "/jobs", "/api/jobs/v1/recruitments"):
            response = client.get(path)
            responses[path] = response
            if response.status_code != 200:
                failures.append(f"{path}: expected 200, received {response.status_code}")
        recruitments = responses["/api/jobs/v1/recruitments"]
        if recruitments.status_code == 200:
            try:
                detail_path = first_job_detail_path(recruitments.json())
            except ValueError:
                failures.append("/api/jobs/v1/recruitments: response was not valid JSON")
            else:
                if detail_path:
                    detail = client.get(detail_path)
                    if detail.status_code != 200:
                        failures.append(
                            f"{detail_path}: expected 200, received {detail.status_code}"
                        )
        for path in ("/review", "/operations", "/api/v1/health", "/docs", "/openapi.json"):
            response = client.get(path)
            if response.status_code != 404:
                failures.append(f"{path}: expected 404, received {response.status_code}")
    if failures:
        print("Public release smoke test FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Public release smoke test PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
