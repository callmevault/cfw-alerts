#!/usr/bin/env python3
"""Daily filtered alerts from the altstrument.org catalog.

Downloads the catalog (compressed, and only if it changed since the previous
run), compares it with the state saved by that run, applies filters.toml and
writes a Markdown digest. Standard library only (Python 3.11+).

Catalog data: altstrument.org, CC-BY-4.0.
"""
import argparse
import gzip
import json
import re
import sys
import tomllib
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

CATALOG_URL = "https://altstrument.org/api/catalog.json"
SITE = "https://altstrument.org"
COMMIT_ONLY = re.compile(r"@\s*[0-9a-f]{7,40}\b|^[0-9a-f]{7,40}$", re.I)
MAX_BODY = 60000  # GitHub issue bodies are capped at 65536 characters
# A new entry whose first listed release is older than this was only just
# catalogued, not just released, and is marked "(new in catalog)".
CATALOG_ONLY_DAYS = 14


def load_catalog(source, etag=None):
    """Return (catalog, etag). The catalog is None when the server says it has
    not changed since the given etag."""
    if not re.match(r"https?://", source):
        return json.loads(Path(source).read_text(encoding="utf-8")), None
    # Compressed, the catalog is about a fifth of its size; with the previous
    # run's etag the server answers 304 and sends nothing if it is unchanged.
    headers = {"User-Agent": "cfw-alerts", "Accept-Encoding": "gzip"}
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(source, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
            if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                body = gzip.decompress(body)
            return json.loads(body), resp.headers.get("ETag")
    except urllib.error.HTTPError as err:
        if err.code == 304:
            return None, etag
        raise


def norm(value):
    return str(value or "").strip().lower()


def norm_list(values):
    return {norm(v) for v in (values or [])}


def absolute(url):
    if not url:
        return SITE
    return url if re.match(r"https?://", url) else SITE + "/" + url.lstrip("/")


def index_catalog(catalog):
    """Flatten the catalog into devices and firmwares keyed by id.

    An entry that targets several devices appears under each of them with the
    same id, so firmwares are merged and remember every device hosting them.
    """
    devices, firmwares = {}, {}
    for dev in catalog.get("devices", []):
        dev_id = dev.get("id")
        if not dev_id:
            continue
        devices[dev_id] = {
            "name": dev.get("name") or dev_id,
            "manufacturer": dev.get("manufacturer") or "",
            "manufacturer_slug": dev.get("manufacturer_slug") or "",
            "category": dev.get("category") or "",
            "tagline": dev.get("tagline") or "",
            "url": absolute(dev.get("url")),
            "entries": [f.get("name") or f.get("slug") or "?" for f in dev.get("firmwares", [])],
        }
        for fw in dev.get("firmwares", []):
            fw_id = fw.get("id")
            if not fw_id:
                continue
            entry = firmwares.setdefault(fw_id, {
                "name": fw.get("name") or fw_id,
                "kind": fw.get("kind") or "firmware",
                "summary": fw.get("summary") or "",
                "status": fw.get("status") or "",
                "tags": fw.get("tags") or [],
                "quality": (fw.get("quality") or {}).get("rating"),
                "brick_risk": bool(fw.get("brick_risk")),
                "url": absolute(fw.get("url")),
                "versions": [],
                "devices": [],
            })
            if dev_id not in entry["devices"]:
                entry["devices"].append(dev_id)
            for other in fw.get("also_devices") or []:
                if other not in entry["devices"]:
                    entry["devices"].append(other)
            known = {v["version"] for v in entry["versions"]}
            for ver in fw.get("versions") or []:
                label = str(ver.get("version") or "").strip()
                if label and label not in known:
                    known.add(label)
                    entry["versions"].append({
                        "version": label,
                        "date": ver.get("date") or "",
                        "url": ver.get("url") or "",
                        "notes": ver.get("notes") or "",
                    })
    return devices, firmwares


def make_state(devices, firmwares, etag=None):
    state = {
        "devices": sorted(devices),
        "firmwares": {k: sorted(v["version"] for v in f["versions"]) for k, f in sorted(firmwares.items())},
    }
    if etag:
        state["catalog_etag"] = etag
    return state


class Filters:
    def __init__(self, cfg):
        mute = cfg.get("mute", {})
        watch = cfg.get("watch_only", {})
        opts = cfg.get("options", {})
        self.mute_manufacturers = norm_list(mute.get("manufacturers"))
        self.mute_devices = norm_list(mute.get("devices"))
        self.mute_firmwares = norm_list(mute.get("firmwares"))
        self.mute_kinds = norm_list(mute.get("kinds"))
        self.mute_tags = norm_list(mute.get("tags"))
        self.mute_statuses = norm_list(mute.get("statuses"))
        self.watch_manufacturers = norm_list(watch.get("manufacturers"))
        self.watch_devices = norm_list(watch.get("devices"))
        self.new_devices_bypass_mute = opts.get("new_devices_bypass_mute", True)
        self.skip_commit_only = opts.get("skip_commit_only_versions", True)
        self.alert_new_devices = opts.get("alert_new_devices", True)
        self.alert_new_entries = opts.get("alert_new_entries", True)
        self.alert_new_versions = opts.get("alert_new_versions", True)

    def _maker_keys(self, dev):
        return {norm(dev["manufacturer_slug"]), norm(dev["manufacturer"])} - {""}

    def device_muted(self, dev_id, dev):
        if norm(dev_id) in self.mute_devices or norm(dev["name"]) in self.mute_devices:
            return True
        return bool(self._maker_keys(dev) & self.mute_manufacturers)

    def device_watched(self, dev_id, dev):
        if not (self.watch_manufacturers or self.watch_devices):
            return True
        if norm(dev_id) in self.watch_devices or norm(dev["name"]) in self.watch_devices:
            return True
        return bool(self._maker_keys(dev) & self.watch_manufacturers)

    def device_ok(self, dev_id, dev, is_new=False):
        if not self.device_watched(dev_id, dev):
            return False
        if self.device_muted(dev_id, dev):
            return is_new and self.new_devices_bypass_mute
        return True

    def firmware_ok(self, fw_id, fw, devices):
        if norm(fw_id) in self.mute_firmwares or norm(fw["name"]) in self.mute_firmwares:
            return False
        if norm(fw["kind"]) in self.mute_kinds:
            return False
        if norm(fw["status"]) in self.mute_statuses:
            return False
        if norm_list(fw["tags"]) & self.mute_tags:
            return False
        hosts = [(d, devices[d]) for d in fw["devices"] if d in devices]
        if not hosts:
            return True
        # Shown if at least one of its devices is watched and not muted.
        return any(self.device_watched(d, dev) and not self.device_muted(d, dev) for d, dev in hosts)


def diff(state, devices, firmwares, flt):
    old_devices = set(state.get("devices", []))
    old_firmwares = state.get("firmwares", {})
    new_devices, new_entries, new_versions = [], [], []
    hidden = 0
    untagged = []  # commit-only versions ("main @ 8f4d15b") left out by skip_commit_only_versions

    fresh_device_ids = {d for d in devices if d not in old_devices}
    for dev_id in sorted(fresh_device_ids):
        if flt.alert_new_devices and flt.device_ok(dev_id, devices[dev_id], is_new=True):
            new_devices.append(dev_id)
        else:
            hidden += 1

    for fw_id, fw in sorted(firmwares.items()):
        if fw_id not in old_firmwares:
            # Entries of a brand-new device are already listed with that device.
            if fw["devices"] and all(d in new_devices for d in fw["devices"]):
                continue
            if flt.alert_new_entries and flt.firmware_ok(fw_id, fw, devices):
                new_entries.append(fw_id)
            else:
                hidden += 1
            continue
        seen = set(old_firmwares[fw_id])
        added = [v for v in fw["versions"] if v["version"] not in seen]
        if not added:
            continue
        if not (flt.alert_new_versions and flt.firmware_ok(fw_id, fw, devices)):
            hidden += len(added)
            continue
        if flt.skip_commit_only:
            untagged += [v["version"] for v in added if COMMIT_ONLY.search(v["version"])]
            added = [v for v in added if not COMMIT_ONLY.search(v["version"])]
        if added:
            new_versions.append((fw_id, added))
    return new_devices, new_entries, new_versions, hidden, untagged


def full_name(dev):
    # Some catalog names already start with the brand ("M5Stack Tab5", "Korg logue SDK tools").
    maker, name = dev["manufacturer"], dev["name"]
    if not maker or norm(name) == norm(maker) or norm(name).startswith(norm(maker) + " "):
        return name
    return f"{maker} {name}"


def device_names(fw, devices):
    return ", ".join(full_name(devices[d]) if d in devices else d for d in fw["devices"])


def badges(fw):
    out = []
    if fw["kind"] != "firmware":
        out.append(fw["kind"])
    if fw["quality"]:
        out.append(fw["quality"])
    if fw["brick_risk"]:
        out.append("brick risk")
    return f" `{' · '.join(out)}`" if out else ""


def short(text, limit=220):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def first_release(fw):
    dates = []
    for v in fw["versions"]:
        try:
            dates.append(date.fromisoformat(v["date"]))
        except (TypeError, ValueError):
            pass
    return min(dates, default=None)


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def render(new_devices, new_entries, new_versions, hidden, untagged, devices, firmwares, today=None):
    today = today or datetime.now(timezone.utc).date()
    lines = []
    if new_devices:
        lines.append(f"## New devices ({len(new_devices)})\n")
        for dev_id in new_devices:
            dev = devices[dev_id]
            lines.append(f"- **[{full_name(dev)}]({dev['url']})**"
                         + (f" ({dev['category']})" if dev["category"] else ""))
            if dev["tagline"]:
                lines.append(f"  {short(dev['tagline'])}")
            if dev["entries"]:
                listed = ", ".join(dev["entries"][:8])
                more = len(dev["entries"]) - 8
                lines.append(f"  Listed: {listed}" + (f" and {more} more" if more > 0 else ""))
        lines.append("")
    if new_entries:
        lines.append(f"## New firmware and tools ({len(new_entries)})\n")
        for fw_id in new_entries:
            fw = firmwares[fw_id]
            latest = fw["versions"][0]["version"] if fw["versions"] else ""
            first = first_release(fw)
            marker = " _(new in catalog)_" if first and first < today - timedelta(days=CATALOG_ONLY_DAYS) else ""
            lines.append(f"- **[{fw['name']}]({fw['url']})**{badges(fw)}{marker} for {device_names(fw, devices)}"
                         + (f", latest {latest}" if latest else ""))
            if fw["summary"]:
                lines.append(f"  {short(fw['summary'])}")
        lines.append("")
    if new_versions:
        lines.append(f"## New versions ({len(new_versions)})\n")
        for fw_id, added in new_versions:
            fw = firmwares[fw_id]
            labels = ", ".join(
                f"[{v['version']}]({v['url']})" if v["url"] else v["version"] for v in added[:5]
            )
            if len(added) > 5:
                labels += f" and {len(added) - 5} more"
            lines.append(f"- **[{fw['name']}]({fw['url']})**{badges(fw)} {labels} for {device_names(fw, devices)}")
            if added[0]["notes"]:
                lines.append(f"  {short(added[0]['notes'])}")
        lines.append("")
    if not lines:
        return ""
    body = "\n".join(lines)
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY].rsplit("\n", 1)[0] + f"\n\n_Digest cut short; see {SITE}/recent for the rest._\n"
    footer = "---\n"
    if untagged:
        footer += (f"{plural(len(untagged), 'untagged update')} (such as `{untagged[0]}`) not listed; "
                   f"see `skip_commit_only_versions` in `filters.toml`. ")
    if hidden:
        footer += f"{plural(hidden, 'other change')} hidden by `filters.toml`. "
    footer += f"Data from [altstrument.org]({SITE}), CC-BY-4.0."
    return body + "\n" + footer + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--catalog", default=CATALOG_URL, help="URL or local path of catalog.json")
    ap.add_argument("--state", default="state.json")
    ap.add_argument("--filters", default="filters.toml")
    ap.add_argument("--out", default="digest.md")
    ap.add_argument("--dry-run", action="store_true", help="do not update the state file")
    args = ap.parse_args()

    out, state_path = Path(args.out), Path(args.state)
    out.unlink(missing_ok=True)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None

    catalog, etag = load_catalog(args.catalog, (state or {}).get("catalog_etag"))
    if catalog is None:
        print("Catalog unchanged since the last run. No alert sent.")
        return
    devices, firmwares = index_catalog(catalog)
    if not devices:
        sys.exit("Catalog has no devices; refusing to overwrite state.")

    cfg = tomllib.loads(Path(args.filters).read_text(encoding="utf-8")) if Path(args.filters).exists() else {}
    flt = Filters(cfg)

    if state is None:
        print(f"First run: recorded {len(devices)} devices and {len(firmwares)} entries as the baseline. No alert sent.")
    else:
        new_devices, new_entries, new_versions, hidden, untagged = diff(state, devices, firmwares, flt)
        digest = render(new_devices, new_entries, new_versions, hidden, untagged, devices, firmwares)
        print(f"{len(new_devices)} new devices, {len(new_entries)} new entries, "
              f"{len(new_versions)} entries with new versions, {hidden} hidden by filters, "
              f"{len(untagged)} untagged updates not listed.")
        if digest:
            out.write_text(digest, encoding="utf-8")

    if not args.dry_run:
        state_path.write_text(json.dumps(make_state(devices, firmwares, etag), indent=0, sort_keys=True) + "\n",
                              encoding="utf-8")


if __name__ == "__main__":
    main()
