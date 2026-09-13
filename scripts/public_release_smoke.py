import argparse
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the bounded public deployment")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    failures: list[str] = []
    with httpx.Client(base_url=base_url, timeout=10, follow_redirects=False) as client:
        for path in ("/healthz", "/readyz", "/jobs", "/api/public/v1/recruitments"):
            response = client.get(path)
            if response.status_code != 200:
                failures.append(f"{path}: expected 200, received {response.status_code}")
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
