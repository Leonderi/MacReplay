import json
import os
import shutil
import subprocess
import time
from urllib.error import URLError, HTTPError
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener, Request, urlopen


DEFAULT_TEST_BYTES = 10 * 1024 * 1024
DEFAULT_USER_AGENT = "MacReplay-Speedtest/1.0"


def _read_json_response(opener, url, *, timeout=10, user_agent=DEFAULT_USER_AGENT):
    req = Request(url, headers={"User-Agent": user_agent})
    with opener.open(req, timeout=timeout) as resp:
        body = resp.read(65536).decode("utf-8", errors="ignore")
    return json.loads(body)


def _country_flag(code):
    code = (code or "").strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ""
    return chr(ord(code[0]) + 127397) + chr(ord(code[1]) + 127397)


def _lookup_country(ip):
    ip = (ip or "").strip()
    if not ip:
        return {"country_code": "", "country_name": "", "country_flag": ""}

    endpoints = [
        f"https://ipwho.is/{quote(ip)}",
        f"http://ip-api.com/json/{quote(ip)}?fields=status,country,countryCode",
    ]

    for url in endpoints:
        try:
            with urlopen(Request(url, headers={"User-Agent": DEFAULT_USER_AGENT}), timeout=8) as resp:
                body = resp.read(65536).decode("utf-8", errors="ignore")
            data = json.loads(body)
            if "ipwho.is" in url:
                if data.get("success") is False:
                    continue
                code = (data.get("country_code") or "").strip().upper()
                name = (data.get("country") or "").strip()
            else:
                status = str(data.get("status") or "").lower()
                if status != "success":
                    continue
                code = (data.get("countryCode") or "").strip().upper()
                name = (data.get("country") or "").strip()
            return {
                "country_code": code,
                "country_name": name,
                "country_flag": _country_flag(code),
            }
        except Exception:
            continue

    return {"country_code": "", "country_name": "", "country_flag": ""}


def _run_http_probe(opener, *, test_bytes=DEFAULT_TEST_BYTES, timeout=20):
    test_urls = [
        f"https://speed.cloudflare.com/__down?bytes={test_bytes}",
        "https://proof.ovh.net/files/10Mb.dat",
    ]

    last_error = None
    for test_url in test_urls:
        try:
            started = time.perf_counter()
            req = Request(
                test_url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Range": f"bytes=0-{test_bytes - 1}",
                },
            )
            total = 0
            with opener.open(req, timeout=timeout) as resp:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total >= test_bytes:
                        break

            elapsed = max(time.perf_counter() - started, 0.001)
            mbps = (total * 8.0) / elapsed / 1_000_000.0
            return {
                "ok": True,
                "download_bytes": int(total),
                "download_ms": round(elapsed * 1000.0, 1),
                "download_mbps": round(mbps, 2),
                "message": "",
            }
        except (URLError, HTTPError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        except Exception as exc:
            last_error = str(exc)

    return {
        "ok": False,
        "download_bytes": 0,
        "download_ms": None,
        "download_mbps": None,
        "message": f"Download probe failed: {last_error or 'unknown error'}",
    }


def _run_ookla_probe(*, proxy_url="", use_proxy=False):
    speedtest_bin = shutil.which("speedtest")
    if not speedtest_bin:
        return {
            "ok": False,
            "message": "Ookla speedtest binary not installed",
            "download_bytes": 0,
            "download_ms": None,
            "download_mbps": None,
            "latency_ms": None,
        }

    cmd = [
        speedtest_bin,
        "--accept-license",
        "--accept-gdpr",
        "--format=json",
        "--progress=no",
    ]
    env = None
    if use_proxy and proxy_url:
        env = dict(**os.environ)
        env["http_proxy"] = proxy_url
        env["https_proxy"] = proxy_url

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=90,
            env=env,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "ok": False,
                "message": (proc.stderr or proc.stdout or "ookla speedtest failed").strip()[:300],
                "download_bytes": 0,
                "download_ms": None,
                "download_mbps": None,
                "latency_ms": None,
            }

        payload = json.loads(proc.stdout or "{}")
        download_bps = float((payload.get("download") or {}).get("bandwidth") or 0) * 8.0
        latency_ms = float((payload.get("ping") or {}).get("latency") or 0)
        return {
            "ok": True,
            "message": "",
            "download_bytes": 0,
            "download_ms": None,
            "download_mbps": round(download_bps / 1_000_000.0, 2) if download_bps > 0 else None,
            "latency_ms": round(latency_ms, 1) if latency_ms > 0 else None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Ookla speedtest failed: {exc}",
            "download_bytes": 0,
            "download_ms": None,
            "download_mbps": None,
            "latency_ms": None,
        }


def run_speedtest(*, proxy_url="", use_proxy=False, provider="http"):
    provider_requested = (provider or "http").strip().lower()
    if provider_requested not in {"http", "ookla"}:
        provider_requested = "http"

    proxy_url = (proxy_url or "").strip()
    opener = build_opener(
        ProxyHandler({"http": proxy_url, "https": proxy_url})
    ) if (use_proxy and proxy_url) else build_opener()

    result = {
        "ok": True,
        "mode": "proxy" if use_proxy else "direct",
        "provider_requested": provider_requested,
        "provider_used": provider_requested,
        "proxy": proxy_url if (use_proxy and proxy_url) else "",
        "public_ip": "",
        "country_code": "",
        "country_name": "",
        "country_flag": "",
        "latency_ms": None,
        "ip_lookup_ms": None,
        "download_bytes": 0,
        "download_ms": None,
        "download_mbps": None,
        "message": "",
        "tested_at": int(time.time()),
    }

    try:
        ip_started = time.perf_counter()
        ip_data = _read_json_response(opener, "https://api.ipify.org?format=json", timeout=10)
        ip_elapsed = (time.perf_counter() - ip_started) * 1000.0
        result["public_ip"] = str(ip_data.get("ip") or "").strip()
        result["ip_lookup_ms"] = round(ip_elapsed, 1)
        result["latency_ms"] = round(ip_elapsed, 1)
    except Exception as exc:
        result["ok"] = False
        result["message"] = f"IP lookup failed: {exc}"
        return result

    geo = _lookup_country(result["public_ip"])
    result.update(geo)

    probe = None
    if provider_requested == "ookla":
        probe = _run_ookla_probe(proxy_url=proxy_url, use_proxy=use_proxy)
        if not probe.get("ok"):
            fallback_probe = _run_http_probe(opener)
            if fallback_probe.get("ok"):
                result["provider_used"] = "http"
                probe = fallback_probe
                result["message"] = f"Ookla unavailable, fallback to HTTP: {probe.get('message') or 'ok'}"
    if probe is None:
        probe = _run_http_probe(opener)

    result["ok"] = bool(probe.get("ok"))
    result["download_bytes"] = probe.get("download_bytes")
    result["download_ms"] = probe.get("download_ms")
    result["download_mbps"] = probe.get("download_mbps")

    if probe.get("latency_ms") is not None:
        result["latency_ms"] = probe.get("latency_ms")

    if not result["ok"]:
        result["message"] = probe.get("message") or result.get("message") or "Speedtest failed"
    elif not result.get("message"):
        result["message"] = probe.get("message") or ""

    return result
