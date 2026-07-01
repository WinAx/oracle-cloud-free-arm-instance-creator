#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
import shlex
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = PROJECT_DIR / "config.json"
DEFAULT_LOG = PROJECT_DIR / "a1_hammer.log"
STOP = False

PERMANENT_ERROR_HINTS = (
    "service limits were exceeded",
    "quota exceeded",
    "notauthorizedornotfound",
    "not authorized",
    "invalidparameter",
    "invalid parameter",
)


def stop_later(signum: int, _frame: object) -> None:
    global STOP
    STOP = True
    log(f"signal={signum}; stopping after current OCI request")


signal.signal(signal.SIGINT, stop_later)
signal.signal(signal.SIGTERM, stop_later)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


LOG_FILE: Path | None = None


def log(message: str) -> None:
    line = f"[{now()}] {message}"
    print(line, flush=True)
    if LOG_FILE:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def load_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = [
        "profile",
        "compartment_id",
        "image_id",
        "subnet_id",
        "ssh_public_key_file",
        "display_name",
        "shape",
        "ocpus",
        "memory_gb",
        "boot_volume_gb",
        "availability_domains",
    ]
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"missing config keys: {', '.join(missing)}")
    if not data["availability_domains"]:
        raise ValueError("availability_domains is empty")
    return data


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def extract_message(text: str) -> str:
    clean = strip_ansi(text).strip()
    if not clean:
        return "empty OCI response"

    starts = [idx for idx in (clean.find("{"), clean.find("[")) if idx >= 0]
    if starts:
        try:
            parsed = json.loads(clean[min(starts) :])
            if isinstance(parsed, dict):
                if parsed.get("message"):
                    return str(parsed["message"])
                if parsed.get("code"):
                    return str(parsed["code"])
        except json.JSONDecodeError:
            pass

    for line in clean.splitlines():
        if line.strip():
            return line.strip()
    return clean


def was_created(text: str) -> tuple[bool, str | None, str | None]:
    clean = strip_ansi(text).strip()
    starts = [idx for idx in (clean.find("{"), clean.find("[")) if idx >= 0]
    if not starts:
        return False, None, None

    try:
        parsed = json.loads(clean[min(starts) :])
    except json.JSONDecodeError:
        return False, None, None

    data = parsed.get("data") if isinstance(parsed, dict) else None
    if not isinstance(data, dict):
        return False, None, None

    instance_id = data.get("id")
    lifecycle_state = data.get("lifecycle-state")
    valid_states = {"PROVISIONING", "RUNNING", "STARTING"}
    return bool(instance_id and lifecycle_state in valid_states), instance_id, lifecycle_state


def launch_once(config: dict[str, Any], availability_domain: str, dry_run: bool) -> tuple[bool, str]:
    shape_config = {
        "ocpus": float(config["ocpus"]),
        "memoryInGBs": float(config["memory_gb"]),
    }
    cmd = [
        "oci",
        "compute",
        "instance",
        "launch",
        "--no-retry",
        "--auth",
        "api_key",
        "--profile",
        str(config["profile"]),
        "--opc-client-request-id",
        f"a1-hammer-{uuid.uuid4()}",
        "--display-name",
        str(config["display_name"]),
        "--compartment-id",
        str(config["compartment_id"]),
        "--image-id",
        str(config["image_id"]),
        "--subnet-id",
        str(config["subnet_id"]),
        "--availability-domain",
        availability_domain,
        "--shape",
        str(config["shape"]),
        "--shape-config",
        json.dumps(shape_config, separators=(",", ":")),
        "--boot-volume-size-in-gbs",
        str(config["boot_volume_gb"]),
        "--ssh-authorized-keys-file",
        str(config["ssh_public_key_file"]),
        "--output",
        "json",
    ]

    if dry_run:
        log("DRY RUN: " + " ".join(shlex.quote(part) for part in cmd))
        return False, "dry run"

    completed = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    raw = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    created, instance_id, lifecycle_state = was_created(raw)
    if created:
        return True, f"CREATED id={instance_id} state={lifecycle_state}"
    return False, extract_message(raw)


def throttle_delay(message: str, base: float, max_delay: float, throttle_count: int) -> float | None:
    lowered = message.lower()
    if "too many requests" not in lowered and "toomanyrequests" not in lowered and "rate limit" not in lowered:
        return None
    delay = min(max_delay, base * (2 ** min(throttle_count, 6)))
    return delay + random.uniform(0, min(delay, base))


def is_permanent_error(message: str) -> bool:
    lowered = message.lower()
    return any(hint in lowered for hint in PERMANENT_ERROR_HINTS)


def run(args: argparse.Namespace) -> int:
    global LOG_FILE
    LOG_FILE = args.log_file

    config = load_config(args.config)
    domains = list(config["availability_domains"])
    if args.shuffle:
        random.shuffle(domains)

    log(
        "start hammer: "
        f"{config['shape']} {config['ocpus']} OCPU/{config['memory_gb']} GB, "
        f"boot={config['boot_volume_gb']} GB, ADs={len(domains)}, interval={args.interval}s"
    )

    attempt = 0
    throttle_count = 0
    while not STOP:
        for ad in domains:
            if STOP:
                break
            attempt += 1
            log(f"attempt #{attempt}: {ad}")
            try:
                ok, message = launch_once(config, ad, args.dry_run)
            except subprocess.TimeoutExpired:
                ok, message = False, "OCI command timed out"
            except FileNotFoundError:
                log("oci CLI not found in PATH")
                return 2

            if ok:
                log(f"{ad}: {message}")
                return 0

            log(f"{ad}: {message}")
            if args.dry_run:
                continue

            if is_permanent_error(message):
                log(
                    "fatal: OCI rejected the request with a non-retryable error; "
                    "check config.json, IAM permissions, quotas, and service limits"
                )
                return 2

            delay = throttle_delay(message, args.throttle_sleep, args.max_throttle_sleep, throttle_count)
            if delay is not None:
                throttle_count += 1
                log(f"throttled; sleep {delay:.0f}s")
                time.sleep(delay)
            else:
                throttle_count = 0
                time.sleep(args.interval + random.uniform(0, args.jitter))

            if args.max_attempts and attempt >= args.max_attempts:
                log(f"max attempts reached: {args.max_attempts}")
                return 1
            if args.once:
                continue

        if args.once:
            log("one pass finished")
            return 1

    log("stopped")
    return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Retry OCI instance launch requests across configured ADs.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--interval", type=float, default=30.0, help="Sleep after each failed launch request.")
    parser.add_argument("--jitter", type=float, default=10.0, help="Random extra sleep after each failed request.")
    parser.add_argument("--throttle-sleep", type=float, default=120.0, help="Base sleep after Too many requests.")
    parser.add_argument("--max-throttle-sleep", type=float, default=1800.0)
    parser.add_argument("--max-attempts", type=int)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--shuffle", action="store_true", help="Shuffle AD order on startup.")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except Exception as exc:
        log(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
