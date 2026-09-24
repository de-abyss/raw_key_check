#!/usr/bin/env python3
"""
Check raw_data in activities for keys that are not described in handled_fields.json.

Examples:
    python check_raw_keys.py                            # all platforms with setup: true
    python check_raw_keys.py 64f1c0...                  # a single platform
    python check_raw_keys.py --since 2025-06-01         # custom created_date lower bound
    python check_raw_keys.py --status active            # all platforms with setup: true and status: active
    python check_raw_keys.py --setup false              # all platforms with setup: false
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from pymongo import MongoClient

BASE_DIR = Path(__file__).resolve().parent

KEYS_TO_SKIP = {
    "generalFormsBlackList",
    "projectsFormsBlackList",
    "projectsFormsWhiteList",
    "platformSpecificData",
}


def get_all_key_paths(data: Dict[str, Any], parent_key: str = "") -> Set[str]:
    """All dot-separated key paths. Array indexes are not included in the path."""
    keys = set()
    for key, value in data.items():
        new_key = "{}.{}".format(parent_key, key) if parent_key else str(key)
        keys.add(new_key)
        if isinstance(value, dict):
            keys |= get_all_key_paths(value, new_key)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    keys |= get_all_key_paths(item, new_key)
    return keys


def section_keys(section: Any) -> List[str]:
    """Array -> its items, object -> its keys (same as the original)."""
    if isinstance(section, list):
        return list(section)
    if isinstance(section, dict):
        return list(section.keys())
    return []


def load_handled_keys(handled: Dict[str, Any]) -> Set[str]:
    keys = set()
    for name, section in handled.items():
        if name in KEYS_TO_SKIP:
            continue
        keys.update(section_keys(section))
    return keys


def platform_specific_keys(handled: Dict[str, Any], platform_id: Any) -> Set[str]:
    data = (handled.get("platformSpecificData") or {}).get(str(platform_id)) or {}
    keys = set()
    for section in data.values():
        keys.update(section_keys(section))
    return keys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find unhandled keys in raw_data")
    parser.add_argument("platform_id", nargs="?", help="Platform ID; omit to check all platforms")
    parser.add_argument("--since", default="2025-01-01",
                        help="Lower bound for created_date (UTC), default 2025-01-01")
    parser.add_argument("--status", default=None,
                        help="Only check platforms with this status, e.g. active (all-platforms mode only)")
    parser.add_argument("--setup", choices=["true", "false"], default=None,
                        help="Only check platforms with this setup value (all-platforms mode only, default: true)")
    parser.add_argument("--handled-fields", default=None,
                        help="Path to handled_fields.json (default: HANDLED_FIELDS_PATH or ./handled_fields.json)")
    args = parser.parse_args()
    if args.platform_id and (args.status is not None or args.setup is not None):
        parser.error("--status and --setup cannot be used together with platform_id")
    return args


def load_platforms(db, collection: str, args: argparse.Namespace) -> List[Dict[str, Any]]:
    platforms = db[collection]
    if args.platform_id:
        try:
            pid = ObjectId(args.platform_id)
        except InvalidId:
            pid = args.platform_id
        doc = platforms.find_one({"_id": pid}, {"_id": 1, "url": 1})
        if doc is None:
            sys.exit("Platform {} not found in collection {}".format(args.platform_id, collection))
        return [doc]

    query = {
        "setup": args.setup != "false",
        "url": {"$not": re.compile("sample", re.IGNORECASE)},
    }
    if args.status is not None:
        query["status"] = args.status
    return list(platforms.find(query, {"_id": 1, "url": 1}))


def main() -> None:
    load_dotenv(str(BASE_DIR / ".env"))
    args = parse_args()

    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri:
        sys.exit("MONGODB_URI is not set (see .env.example)")

    handled_path = Path(args.handled_fields or os.getenv("HANDLED_FIELDS_PATH")
                        or BASE_DIR / "handled_fields.json")
    with open(str(handled_path), encoding="utf-8") as f:
        handled = json.load(f)

    since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    client = MongoClient(mongo_uri)
    db_name = os.getenv("MONGODB_DB")
    db = client[db_name] if db_name else client.get_default_database()
    platforms_coll = os.getenv("PLATFORMS_COLLECTION", "platforms")
    activities = db[os.getenv("ACTIVITIES_COLLECTION", "activities")]

    base_handled_keys = load_handled_keys(handled)
    count_problems = 0

    try:
        platforms = load_platforms(db, platforms_coll, args)
        if args.platform_id:
            print("🚀 Running analysis for specific platform: {}".format(args.platform_id))
        else:
            filters = "setup: {}".format(args.setup or "true")
            if args.status is not None:
                filters += ", status: {}".format(args.status)
            print("🚀 Running analysis for ALL platforms ({}): {} found.".format(filters, len(platforms)))

        for platform_doc in platforms:
            platform_id = platform_doc["_id"]
            platform_url = platform_doc.get("url", str(platform_id))

            # platform-specific keys apply only to the current platform
            handled_keys = base_handled_keys | platform_specific_keys(handled, platform_id)

            # platform may be stored either as an ObjectId or as a string
            query = {
                "platform": {"$in": [platform_id, str(platform_id)]},
                "created_date": {"$gte": since},
            }

            all_found_keys = set()
            for doc in activities.find(query, {"raw_data": 1, "_id": 0}, batch_size=1000):
                raw_data = doc.get("raw_data")
                if isinstance(raw_data, dict):
                    for key in get_all_key_paths(raw_data):
                        if "milestones." not in key:
                            all_found_keys.add(key)

            print("Found a total of {} unique keys.".format(len(all_found_keys)))
            new_keys = sorted(all_found_keys - handled_keys)

            if new_keys:
                count_problems += 1
                print("\t🚨 Signal!\nPlatform: {}\n Found unhandled keys - {} new".format(
                    platform_url, len(new_keys)))
                for key in new_keys:
                    print("\t\t - {}".format(key))
            else:
                print("\t✅ Success!\t Platform: {}\n No new keys found. All keys are handled.".format(
                    platform_url))
    finally:
        client.close()

    print("total: {}".format(count_problems))


if __name__ == "__main__":
    main()
