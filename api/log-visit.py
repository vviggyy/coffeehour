"""Vercel serverless function: log coffee line visits to coffee_data.csv via GitHub API."""

import base64
import csv
import io
import json
import os
from http.server import BaseHTTPRequestHandler

REPO = "vviggyy/coffeehour"
CSV_PATH = "coffee_data.csv"
BRANCH = "main"


def github_request(path, method="GET", body=None, token=None):
    import urllib.request

    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    if method == "GET":
        url += f"?ref={BRANCH}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "coffeehour-vercel",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def fetch_csv(token):
    file_info = github_request(CSV_PATH, token=token)
    sha = file_info["sha"]
    content = base64.b64decode(file_info["content"]).decode("utf-8")
    return content, sha


def parse_csv(content):
    reader = csv.DictReader(io.StringIO(content))
    return list(reader)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            self._json(500, {"error": "GITHUB_TOKEN not configured"})
            return

        try:
            content, _ = fetch_csv(token)
            rows = parse_csv(content)
            self._json(200, {"data": rows})
        except Exception as e:
            self._json(500, {"error": f"Failed to fetch data: {e}"})

    def do_POST(self):
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            self._json(500, {"error": "GITHUB_TOKEN not configured"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self._json(400, {"error": "Invalid JSON"})
            return

        date = payload.get("date")
        arrival_time = payload.get("arrival_time")
        coffee_time = payload.get("coffee_time")
        people_ahead = payload.get("people_ahead")
        refills = payload.get("refills", 0)

        if not all([date, arrival_time, coffee_time, people_ahead is not None]):
            self._json(400, {"error": "Missing required fields"})
            return

        try:
            csv_content, sha = fetch_csv(token)
        except Exception as e:
            self._json(500, {"error": f"Failed to fetch CSV: {e}"})
            return

        # Append new row
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow([date, arrival_time, coffee_time, int(people_ahead), int(refills)])
        updated_csv = csv_content.rstrip("\n") + "\n" + buf.getvalue()

        updated_b64 = base64.b64encode(updated_csv.encode("utf-8")).decode("ascii")
        commit_msg = f"Log visit {date} {arrival_time} ({people_ahead} people)"
        try:
            github_request(
                CSV_PATH,
                method="PUT",
                body={
                    "message": commit_msg,
                    "content": updated_b64,
                    "sha": sha,
                    "branch": BRANCH,
                },
                token=token,
            )
        except Exception as e:
            self._json(500, {"error": f"Failed to commit: {e}"})
            return

        self._json(200, {"ok": True, "date": date, "arrival_time": arrival_time})

    def _json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
