# raw_keys_check_py

A local script that finds keys in the `raw_data` of `activities` documents that are not described in `handled_fields.json`.

## How it works

1. Loads `handled_fields.json` and builds the set of known keys:
   - array → its items are used;
   - object → its keys are used;
   - the sections `generalFormsBlackList`, `projectsFormsBlackList`, `projectsFormsWhiteList` and `platformSpecificData` are skipped.
2. Selects platforms:
   - with no `platform_id` argument, all platforms with no `sample` in `url` and `setup: true` (or `setup: false` with `--setup false`). `--status` additionally keeps only platforms with the given `status`;
   - with a `platform_id` argument, that single platform. `--status` and `--setup` cannot be used in this mode.
3. For each platform, adds its keys from `platformSpecificData[<platform_id>]`.
4. Iterates over `activities` with `created_date >= --since` and collects the dot-separated key paths of `raw_data`. Array indexes are not included in paths, and keys containing `milestones.` are skipped.
5. Prints the keys that are not in the known set, then prints the number of platforms with problems.

## `handled_fields.json` structure

The file is a single JSON object. Each top-level key is a section, and the script only needs the key paths listed in it.

```jsonc
{
  // 1. Field lists: arrays of raw_data key paths mapped to one lead field
  "full_name_list": ["name", "form_fields.full_name", "..."],
  "first_name_list": ["..."],
  "phone": ["..."],
  "email": ["..."],

  // 2. Field maps: objects of "raw_data key path" -> "human-readable label"
  "messageField": { "form_fields.message": "Message", "...": "..." },

  // 3. Keys that are known but intentionally not used
  "ignored_keys": ["created_at", "tags.id", "..."],

  // 4. Per-platform additions, keyed by platform _id
  "platformSpecificData": {
    "65c3601246455b56f28c4ffc": {
      "messageField": { "field": "Message" },
      "ignored_keys": ["some_key"]
    }
  },

  // 5. Form filters (skipped by this script)
  "generalFormsBlackList": ["Job Form", "..."],
  "projectsFormsBlackList": { "<platform_id>": ["<form name or id>"] },
  "projectsFormsWhiteList": { "<platform_id>": ["<form name or id>"] }
}
```

### Sections

| Kind | Sections | Value type | What the script reads |
|---|---|---|---|
| Field lists | `full_name_list`, `prefix_name_list`, `first_name_list`, `middle_name_list`, `last_name_list`, `phone`, `email`, `address`, `street`, `street_2`, `city`, `state`, `country`, `zip`, `utm_string`, `utm_source`, `utm_medium`, `utm_campaign`, `gclid`, `fbclid`, `msclkid`, `ip_address`, `landingPage`, `referrerPage`, `user_referral_source` | array of strings | every item |
| Field maps | `messageField`, `messageFieldMultiselect`, `messageFieldBoolean` | object `key path -> label` | the keys only (labels are ignored) |
| Ignored keys | `ignored_keys` | array of strings | every item |
| Platform overrides | `platformSpecificData` | object `platform_id -> { section: list or map }` | the keys of every nested section, for the matching platform only |
| Form filters | `generalFormsBlackList`, `projectsFormsBlackList`, `projectsFormsWhiteList` | array or object | skipped: these hold form names, not key paths |

The script does not hardcode section names. Any new top-level section is picked up automatically: if it is an array, its items are used; if it is an object, its keys are used. The same rule applies to sections inside `platformSpecificData`. Because of this, a misspelled section name such as `ingnored_keys` still counts.

### Key path format

- Nested keys are joined with dots, for example `form_fields.email` or `customer.default_address.city`.
- Array indexes are not part of the path. Keys of objects inside an array are listed under the array's own key, for example `line_items.price_set.shop_money.amount`.
- Matching is exact and case-sensitive. `Email` and `email` are separate entries, and so are keys with leading BOM characters (`﻿name`).
- Every intermediate path must be listed too. If `raw_data` contains `customer.default_address.city`, the paths `customer` and `customer.default_address` are reported as well unless they appear in some section.
- Paths containing `milestones.` are never reported, so they do not need to be listed.

### Adding a new key

When the script reports an unhandled key:

- the key maps to a lead field: add it to the matching field list or field map;
- the key is noise: add it to `ignored_keys`;
- the key only matters for one platform: add it under `platformSpecificData.<platform_id>`.

### Differences from the original

- Keys from one platform's `platformSpecificData` no longer carry over to the next platforms. In the original they accumulated in the shared `HANDLED_KEYS`.
- When `platform_id` is passed, the platform document is loaded from the database, so the output shows its `url`. The original passed a string instead of an `ObjectId` and printed `undefined`.
- The `platform` field is matched both as an `ObjectId` and as a string.
- Known keys are stored in a `set`, which makes lookups faster.
- The start date is set with `--since` instead of being hardcoded.

## Setup

Requires Python 3.7 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Fill in `.env` and put `handled_fields.json` from the main project
(`src/modules/workflows/utils/handled_fields.json`) next to the script. Alternatively, set its path in `HANDLED_FIELDS_PATH`.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `MONGODB_URI` | — | Connection string, required |
| `MONGODB_DB` | name from the URI | Database |
| `PLATFORMS_COLLECTION` | `platforms` | Platforms collection |
| `ACTIVITIES_COLLECTION` | `activities` | Activities collection |
| `HANDLED_FIELDS_PATH` | `./handled_fields.json` | Path to the known-keys config |

## Usage

```bash
python check_raw_keys.py
```

### Options

| Option | Description |
|---|---|
| `platform_id` | Check only this platform. Omit to check all platforms |
| `--status STATUS` | All-platforms mode only: check only platforms with this exact `status`, for example `active` (case-sensitive) |
| `--setup true\|false` | All-platforms mode only: check platforms with this `setup` value, default `true` |
| `--since YYYY-MM-DD` | Lower bound for `created_date` (UTC), default `2025-01-01` |
| `--handled-fields PATH` | Path to `handled_fields.json` |

### Examples

Check all platforms with `setup: true`:

```bash
python check_raw_keys.py
```

Check a single platform:

```bash
python check_raw_keys.py 64f1c0a1b2c3d4e5f6a7b8c9
```

Check only active platforms (`status: "active"` and `setup: true`):

```bash
python check_raw_keys.py --status active
```

Check platforms with `setup: false` and `status: "active"`:

```bash
python check_raw_keys.py --setup false --status active
```

Use a custom start date and config path:

```bash
python check_raw_keys.py --since 2025-06-01 --handled-fields D:\project\handled_fields.json
```
