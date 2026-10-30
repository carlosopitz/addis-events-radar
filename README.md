# Addis Events Radar

A self-updating monitor of public events and news from embassies, cultural institutes and event listings in Addis Ababa.

- **Dashboard:** https://carlosopitz.github.io/addis-events-radar/
- **Source database:** [`sources.yaml`](sources.yaml) (edit it on GitHub to add or fix a source)
- **Combined RSS feed:** https://carlosopitz.github.io/addis-events-radar/data/feed.xml

## How it works

A GitHub Actions workflow (`.github/workflows/radar.yml`) runs every two hours, free, on GitHub's servers:

1. It reads every channel listed in `sources.yaml`:
   - **web**: a news or events page. Any new article link on it becomes a new item. If a page has no readable links (JavaScript-heavy sites), the monitor falls back to flagging "page was updated" when its text changes.
   - **rss**: any RSS/Atom feed.
   - **telegram**: a public Telegram channel, read through its public web preview.
   - **gnews**: a Google News search, to catch events that only get announced on Facebook but are covered by the press.
2. New items are saved to `docs/data/items.json` and marked as events when their title or summary contains event words (concert, exhibition, screening, Ausstellung, exposición, mostra …) in six languages.
3. You get a push notification on your phone through [ntfy](https://ntfy.sh): one per new event post, plus a single digest for other news.
4. The dashboard (in `docs/`, served by GitHub Pages) shows everything, with filters.

Every Monday the workflow also visits each homepage and records the social accounts, newsletter links and feeds the site links to (shown with dashed outlines on the Sources tab).

The first check records what is already on each site as a baseline, so you are not flooded. From then on only genuinely new posts count as new.

## One-time setup

### 1. Turn on GitHub Pages
Settings → Pages → Build and deployment → Source: **Deploy from a branch** → Branch: `main`, folder: `/docs` → Save.

### 2. Push notifications (ntfy)
1. Install **ntfy** from the App Store.
2. Pick a long, unguessable topic name, e.g. `addis-radar-7f3k9q2m`. Anyone who knows the name can read it, so treat it like a password.
3. In the app: **+** → enter the topic → Subscribe.
4. In this repo: Settings → Secrets and variables → Actions → **New repository secret** → Name `NTFY_TOPIC`, value: your topic.

Optional repository *variables* (same page, Variables tab):
- `NOTIFY_OTHER`: `digest` (default: one summary push for non-event posts), `each` (one push per post) or `off`.

### 3. Run it
Actions → **radar** → Run workflow → `both`. The first run takes about two minutes.

## Adding sources

Open `sources.yaml` on GitHub, click the pencil, add an entry and commit. The workflow re-runs automatically after each edit.

```yaml
- id: portugal
  name: Embassy of Portugal
  country: PT
  kind: embassy
  region: europe
  homepage: https://example.gov.pt/addis
  links:
    instagram: https://www.instagram.com/...
  channels:
    - type: web
      url: https://example.gov.pt/addis/news
      include: /addis/news/     # only links matching this count as posts
```

If the **Health** tab shows a web channel with 0 posts found, the page needs a tighter `include` pattern or a `selector` (a CSS selector for the list area).

## X, Facebook and Instagram

These platforms block automated reading, so there is no free way to monitor them. Two options:

- **Paid bridge (recommended if you want them in the dashboard):** [RSS.app](https://rss.app) turns an X, Facebook or Instagram account into an RSS feed (Basic plan covers 15 feeds). Create the feed, then add it to the right source:
  ```yaml
      - type: rss
        url: https://rss.app/feeds/XXXXXXXX.xml
        label: X
  ```
- **Free:** follow the accounts and turn on post notifications in the apps themselves.

Bluesky and Mastodon profiles have free RSS feeds built in (`https://bsky.app/profile/HANDLE/rss`), which work as `type: rss` with no extra service.

## Email newsletters

Subscribe with an address from [Kill the Newsletter](https://kill-the-newsletter.com) (free): it turns incoming emails into an Atom feed you can add as `type: rss`. This works for the Goethe-Institut, Alliance and embassy newsletters.

## Keeping it alive

GitHub pauses scheduled workflows in repositories with no activity for 60 days. The monitor commits its data on most runs, which normally counts as activity. If you ever see a banner saying the workflow was disabled, click **Enable workflow** on the Actions tab.
