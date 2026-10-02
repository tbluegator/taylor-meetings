# Taylor Meetings

A self-updating website for Taylor County BOCC, Perry City Council, the School Board, and TCDA.
It checks the official sources three times a day, rebuilds the page, and emails you only when something breaks.

## Setup (one time, ~15 minutes)

1. **Make a GitHub repo** named `taylor-meetings` (public, so Pages is free). Upload this folder's contents.
2. **Turn on Pages:** repo → *Settings → Pages → Build and deployment → Source: **GitHub Actions***.
3. **Run it once:** repo → *Actions → Update meetings → Run workflow*. Wait ~2 minutes.
4. **Set your address:** open `config.yaml` and set `site.base_url` to the Pages URL shown in step 3's run summary. Commit.
5. **Check failure emails are on:** github.com → your avatar → *Settings → Notifications → Actions → "Only notify for failed workflows"* (on by default).

That's it. From here it runs by itself.

## Day-to-day

| You want to… | Do this |
|---|---|
| Watch a new topic | Add a line under `topics:` in `config.yaml` |
| Add a board | Add an entry under `sources:` (same types as the existing ones) |
| Refresh right now | *Actions → Update meetings → Run workflow* |
| See why it failed | Open the failed run; the last step lists each problem in plain words |

## How it stays hands-off

- **Every run self-tests first** against saved samples in `tests/fixtures/`. If the code is broken, nothing gets published.
- **History is kept** in `data/meetings.json`. If one source is down, the site keeps showing its last good data.
- **The watchdog** (`tracker/health.py`) fails the run, and GitHub emails you, when:
  - a source can't be reached,
  - a source answers but lists no meetings (likely a site redesign), or
  - none of a board's meetings in the last 30 days has an agenda (likely the agenda links moved).
- An upcoming meeting with no agenda yet is shown on the site as a warning but doesn't email you.

## Sources and how each is read

| Board | Source | Method | Fragility |
|---|---|---|---|
| BOCC + VAB | CivicClerk (`taylorcofl`) | Public JSON API | Low |
| School Board | BoardDocs (`fl/taylor`) | JSON meeting list + agenda fragment | Low–medium |
| Perry City Council | cityofperry.net (CivicPlus) | Site RSS + meeting pages + agenda PDF text | **Medium: most likely to need a fix** |
| TCDA | none online | Standing schedule (3rd Thursday, noon) | n/a |

Notes worth knowing:
- CivicClerk's times end in `Z` but are local time. The code treats them that way (see the test that checks the 5:01 pm budget hearing).
- BoardDocs' `robots.txt` asks crawlers to stay out. This makes a handful of targeted requests per run for public records; keep the schedule modest.
- Perry agendas are parsed from the PDF text. The format matched the Sept 22, 2026 agenda; if the clerk changes the layout, items may come through less cleanly, but the links still work.
- School Board agenda titles are generic ("Approval of Agreement/Contracts"). The substance is in the attachments, so topic matching catches less there.

## Run locally

```
pip install -r requirements.txt
python -m pytest -q                                              # self-test
python -m tracker.build --offline tests/fixtures --today 2026-10-01   # build from samples into site/
python -m tracker.build                                          # live run
```

## Not built yet (Phase 2 ideas)

- Plain-language summaries of each agenda (Claude API; CivicClerk already serves agenda/packet text via `GetMeetingFileStream(...,plainText=true)`).
- Email digest for subscribers.
- School Board video: add the district's YouTube channel ID in `config.yaml` (`youtube_channel_id`).
- Transcripts from the BOCC video files (the CivicClerk `.mp4` links are in `data/meetings.json`).
