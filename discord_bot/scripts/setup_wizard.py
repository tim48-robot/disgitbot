#!/usr/bin/env python3
"""
Simple setup wizard for self-hosted DisgitBot.
Generates discord_bot/config/.env from .env.example and optionally copies credentials.json.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

FIELD_DESCRIPTIONS = {
    "DISCORD_BOT_TOKEN": "Discord bot token",
    "GITHUB_TOKEN": "GitHub personal access token (needs repo read + workflow if using Actions)",
    "GITHUB_CLIENT_ID": "GitHub OAuth app client ID",
    "GITHUB_CLIENT_SECRET": "GitHub OAuth app client secret",
    "REPO_OWNER": "GitHub org/user that owns this repo (for workflow dispatch)",
    "OAUTH_BASE_URL": "Public base URL (e.g. https://<your-cloud-run-url>)",
    "DISCORD_BOT_CLIENT_ID": "Discord application ID (client ID)",
    "GITHUB_APP_ID": "GitHub App ID (invite-only mode)",
    "GITHUB_APP_PRIVATE_KEY_B64": "GitHub App private key (base64 PEM, invite-only mode)",
    "GITHUB_APP_SLUG": "GitHub App slug (apps/<slug>)",
}

REQUIRED_KEYS = {
    "DISCORD_BOT_TOKEN",
    "GITHUB_TOKEN",
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    "REPO_OWNER",
    "OAUTH_BASE_URL",
    "DISCORD_BOT_CLIENT_ID",
}


def _parse_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _prompt_value(key: str, existing: str) -> str:
    description = FIELD_DESCRIPTIONS.get(key, "")
    label = f"{key}"
    if description:
        label += f" ({description})"
    if existing:
        label += f" [current: {existing}]"
    label += ": "

    value = input(label).strip()
    if not value:
        return existing
    return value


def _write_env(example_path: Path, env_path: Path, values: dict[str, str]) -> None:
    lines = []
    for line in example_path.read_text().splitlines():
        if not line.strip() or line.strip().startswith("#"):
            lines.append(line)
            continue
        if "=" not in line:
            lines.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        lines.append(f"{key}={values.get(key, '')}")

    env_path.write_text("\n".join(lines) + "\n")


def _handle_credentials(config_dir: Path) -> None:
    target_path = config_dir / "credentials.json"
    if target_path.exists():
        print(f"Found existing credentials at {target_path}")
        return

    input_path = input(
        "Path to Firebase service account JSON (leave blank to skip): "
    ).strip()
    if not input_path:
        print("Skipping credentials copy. You must add config/credentials.json before running the bot.")
        return

    source_path = Path(input_path).expanduser()
    if not source_path.exists():
        print(f"File not found: {source_path}")
        print("Skipping credentials copy.")
        return

    shutil.copy2(source_path, target_path)
    print(f"Copied credentials to {target_path}")


def main() -> int:
    base_dir = Path(__file__).resolve().parents[1]
    config_dir = base_dir / "config"
    example_path = config_dir / ".env.example"
    env_path = config_dir / ".env"

    if not example_path.exists():
        print(f"Missing {example_path}")
        return 1

    config_dir.mkdir(parents=True, exist_ok=True)

    existing_values = _parse_env(env_path)
    new_values = dict(existing_values)

    print("DisgitBot setup wizard\n")

    example_keys = []
    for line in example_path.read_text().splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        example_keys.append(key)
        current = existing_values.get(key, "")
        new_values[key] = _prompt_value(key, current)

    # Prompt for any known keys missing from .env.example
    for key in FIELD_DESCRIPTIONS:
        if key in example_keys:
            continue
        current = existing_values.get(key, "")
        new_values[key] = _prompt_value(key, current)

    missing_required = [
        key for key in REQUIRED_KEYS if not new_values.get(key)
    ]
    if missing_required:
        print("\nMissing required values:")
        for key in sorted(missing_required):
            print(f"- {key}")
        print("\nYou can re-run this wizard after collecting the missing values.")

    _write_env(example_path, env_path, new_values)
    print(f"\nWrote {env_path}")

    _handle_credentials(config_dir)

    print("\nNext steps:")
    print("- Run: python main.py (from discord_bot/)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
