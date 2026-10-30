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
3. Every morning at about 06:50 Addis time you get one email digest: event posts first, then other news. Days with nothing new send no email.
4. The dashboard (in `docs/`, served by GitHub Pages) shows everything, with filters.

Every Monday the workflow also visits each homepage and records the social accounts, newsletter links and feeds the site links to (shown with dashed outlines on the Sources tab).

The first check records what is already on each site as a baseline, so you are not flooded. From then on only genuinely new posts count as new.

## One-time setup

### 1. Turn on GitHub Pages
Settings → Pages → Build and deployment → Source: **Deploy from a branch** → Branch: `main`, folder: `/docs` → Save.

### 2. Daily email digest (Gmail)
1. Make sure 2-Step Verification is on for your Google account.
2. Open https://myaccount.google.com/apppasswords, name it `Addis Events Radar`, click **Create** and copy the 16-character password.
3. In this repo: Settings → Secrets and variables → Actions → **New repository secret**, twice:
   - `MAIL_USERNAME`: your Gmail address
   - `MAIL_PASSWORD`: the app password
4. Optional: `MAIL_TO` if the digest should go to a different address.
5. Actions → **radar** → Run workflow → `test-email` sends a sample right away.

The digest is sent from your own Gmail to yourself. To stop it, delete the app password on the same Google page (this also revokes access) or remove the secrets.

### 3. Run it
Actions → **radar** → Run workflow → `both`. The first run takes about two minutes.

Other manual tasks: `digest` (send today's digest now), `test-email`, `discover` (refresh social links), `snapshot` (save raw pages to `debug/` for tuning rules).

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
