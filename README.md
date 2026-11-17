# cfw-alerts

A daily digest of what is new in custom firmware for music hardware, built
from the [altstrument.org](https://altstrument.org) catalog: new devices, new
firmware and tools, and new releases of things already listed. Each digest is
a GitHub issue; on days without news there is no issue.

"New" means new to the altstrument catalog. A new entry whose first release
is more than two weeks old, an existing project altstrument has only just
added, is marked _(new in catalog)_.

The workflow is scheduled three times a day, after altstrument's daily update.
GitHub often starts scheduled runs hours late and sometimes skips one, so the
second and third runs are backups: when one of them finds something new, it
adds it to that day's issue as a comment. An issue is dated by the day its run
was scheduled, even when GitHub starts it after midnight. Each run compares the
catalog with the previous run's `state.json`, which is kept on the `state`
branch so `main` holds only code.

## Two ways to use it

### 1. No setup: watch this repository's issues

This repository runs the digest itself every day, with no filters, and posts
each one as an issue. Anyone can read them on the
[issues page](https://github.com/callmevault/cfw-alerts/issues), signed in or
not.

To be notified of each new digest:

1. Sign in to GitHub and open
   [callmevault/cfw-alerts](https://github.com/callmevault/cfw-alerts).
2. Click **Watch** at the top right, choose **Custom**, tick **Issues** and
   click **Apply**.

Each new digest then appears in your GitHub notifications, and in your email
if your [notification settings](https://github.com/settings/notifications)
send email for repositories you watch. To stop, choose **Watch >
Participating and @mentions**.

### 2. Your own filters: a private copy

1. Click **Use this template > Create a new repository**, choose **Private**
   and leave **Include all branches** unticked.
2. Edit `filters.toml` in your copy to mute what you do not want (see the
   reference below) and commit.
3. Open **Actions > CFW alerts > Run workflow** once. This first run opens an
   issue straight away with the last day's changes that pass your filters, so
   you can check everything works. If nothing from the last day passes them,
   it opens no issue and simply starts tracking.

From then on your copy runs every day and opens an issue that mentions you,
so GitHub emails it to you. No settings need changing: the workflow file
grants itself the permissions it uses. In a repository owned by an
organisation nobody is mentioned; members watch the repository instead.

## Filters reference

`filters.toml` has three sections. Names are not case sensitive. For brands
and devices, use either the display name (`"M-VAVE"`, `"FM-1"`) or the id from
the altstrument URL: `altstrument.org/devices/m-vave-fm-1` is `"m-vave-fm-1"`.

| Setting | What it does |
| --- | --- |
| `[mute]` `manufacturers` | Hides whole brands, e.g. `["m-vave"]`. |
| `[mute]` `devices` | Hides single devices, e.g. `["m-vave-chocolate"]`. |
| `[mute]` `firmwares` | Hides single entries by name, or by the part of the URL after `/firmware/`, e.g. `["m-vave-fm-1/dark-1"]`. |
| `[mute]` `kinds` | `firmware` or `tool`; `["tool"]` leaves firmware only. |
| `[mute]` `tags` | Any altstrument tag, e.g. `["editor", "research"]`. |
| `[mute]` `statuses` | Any of `active`, `maintained`, `dormant`, `archived`, `announced`, `unknown`. |
| `[watch_only]` `manufacturers`, `devices` | If either list has anything in it, you hear only about these brands and devices. |
| `[options]` `alert_new_devices` | Report devices that appear in the catalog for the first time. |
| `[options]` `alert_new_entries` | Report new firmware and tools for devices already listed. |
| `[options]` `alert_new_versions` | Report new releases of entries already listed. |
| `[options]` `new_devices_bypass_mute` | Show a brand-new device even when its brand is muted. |
| `[options]` `skip_commit_only_versions` | Ignore untagged updates such as `main @ 8f4d15b`; tagged releases still show. |

All options are `true` by default. An entry listed under several devices is
shown if at least one of those devices passes the filters. The footer of each
digest says how many changes the filters hid and how many untagged updates
were left out. Changes to `filters.toml` apply from the next run.

To preview your filters before committing, run this in a clone of your copy
(Python 3.11 or later, no packages needed). It writes `digest.md` with what is
new since the last run and leaves the saved state alone:

```bash
git fetch origin state
git show origin/state:state.json > state.json
python3 alerts.py --dry-run
```

## Getting updates

Your copy starts with its own history, so the first update needs one extra
flag. In a clone of your copy, run the following with `OWNER` replaced by the
account shown under your copy's name on GitHub ("generated from
OWNER/cfw-alerts"):

```bash
git remote add upstream https://github.com/OWNER/cfw-alerts.git
git pull --no-rebase --no-edit --allow-unrelated-histories upstream main
```

If Git reports conflicts, keep your own `filters.toml`, take the upstream
version of every other conflicted file, then commit and push:

```bash
git checkout --ours filters.toml
git checkout --theirs alerts.py   # repeat for each other file git status lists as conflicted
git add -A
git commit --no-edit
git push
```

After that, each update is:

```bash
git pull --no-rebase --no-edit upstream main
git push
```

## Credits

Catalog data, and the text quoted in each digest, come from
[altstrument.org](https://altstrument.org) under
[CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/); every digest credits
and links back to it. This project is not affiliated with altstrument.org. The
code is released under the MIT licence; see [LICENSE](LICENSE).
