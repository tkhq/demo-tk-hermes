#!/usr/bin/env python3
"""OpenClaw SecretRef resolver and Tact launcher using tkhq/tk."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid


class Failure(Exception):
    pass


def load_config(path):
    config = json.loads(Path(path).read_text())
    if not isinstance(config, dict):
        raise Failure("INVALID_CONFIG")
    if not Path(config.get("tk", "")).is_absolute():
        raise Failure("INVALID_TK_PATH")
    if not isinstance(config.get("profile"), str) or not config["profile"]:
        raise Failure("MISSING_PROFILE")
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", config.get("provider", "")):
        raise Failure("INVALID_PROVIDER")
    secrets = config.get("secrets")
    if not isinstance(secrets, dict) or not secrets:
        raise Failure("MISSING_SECRET_BINDINGS")
    for name, secret_id in secrets.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", name):
            raise Failure("INVALID_SECRET_ALIAS")
        uuid.UUID(secret_id)
    return config


def export_secret(config, alias):
    if alias not in config["secrets"]:
        raise Failure("NOT_FOUND")
    # An explicit profile wins over ambient Turnkey credentials. The request
    # cannot supply a profile, organization, endpoint, command, or secret ID.
    command = [config["tk"], "--profile", config["profile"],
               "--message-format", "json", "--non-interactive",
               "secret", "export", "--id", config["secrets"][alias]]
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=20, check=False)
        records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    except subprocess.TimeoutExpired:
        raise Failure("EXPORT_TIMEOUT") from None
    except (OSError, ValueError):
        raise Failure("EXPORT_FAILED") from None
    if result.returncode != 0:
        raise Failure("EXPORT_FAILED")
    matches = [r for r in records if isinstance(r, dict)
               and r.get("reason") == "command_result"
               and r.get("command") == "secret.export"]
    if len(matches) != 1:
        raise Failure("INVALID_EXPORT_RESPONSE")
    record = matches[0]
    if record.get("status") == "pending":
        # tk persists the recipient key. A later resolver run resumes it.
        raise Failure("APPROVAL_REQUIRED")
    data = record.get("data")
    if (record.get("status") != "completed" or not isinstance(data, dict)
            or not isinstance(data.get("value"), str) or not data["value"]):
        raise Failure("INVALID_EXPORT_RESPONSE")
    return data["value"]


def resolve(config, request):
    if (not isinstance(request, dict) or request.get("protocolVersion") != 1
            or request.get("provider") != config["provider"]):
        raise Failure("INVALID_REQUEST")
    ids = request.get("ids")
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 16
            or any(not isinstance(alias, str) for alias in ids)
            or len(set(ids)) != len(ids)):
        raise Failure("INVALID_REQUEST")
    values, errors = {}, {}
    for alias in ids:
        try:
            values[alias] = export_secret(config, alias)
        except Failure as error:
            errors[alias] = {"code": str(error)}
    return {"protocolVersion": 1, "values": values, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("openclaw")
    tact = sub.add_parser("tact")
    tact.add_argument("--binary", required=True, help="Absolute path to tact")
    tact.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.mode == "openclaw":
            raw = sys.stdin.buffer.read(65537)
            if len(raw) > 65536:
                raise Failure("REQUEST_TOO_LARGE")
            response = resolve(config, json.loads(raw))
            # stdout is the provider transport; never invoke this as an LLM tool.
            sys.stdout.write(json.dumps(response) + "\n")
        else:
            if not Path(args.binary).is_absolute():
                raise Failure("INVALID_TACT_PATH")
            environment = os.environ.copy()
            for alias in config["secrets"]:
                value = export_secret(config, alias)
                if "\0" in value:
                    raise Failure("INVALID_ENV_VALUE")
                environment[alias] = value
            # Do not propagate ambient Turnkey credentials to Tact's children.
            for name in list(environment):
                if name.startswith("TURNKEY_") or name in ("TK_PROFILE", "TK_CONFIG"):
                    environment.pop(name)
            tail = args.args[1:] if args.args[:1] == ["--"] else args.args
            os.execve(args.binary, [args.binary, *tail], environment)
    except Failure as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, AttributeError):
        # Never print input, child stdout, SDK errors, or secret-bearing tracebacks.
        print("CONFIG_OR_PROTOCOL_ERROR", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
