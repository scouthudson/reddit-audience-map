# Reddit Audience Map

A newsroom-oriented research tool for visualizing **observed audience overlap** between Reddit communities.

## What it measures

**Observed audience overlap** is the number of unique Reddit accounts that publicly posted or commented in both communities during a defined observation window.

It does **not** measure private subreddit subscriptions and should not be described as a measure of subscriber overlap.

## Current prototype

The current collector is designed around a 90-day observation window and discovers two separate community universes: NSFW communities and a broader SFW comparison set. The SFW set is discovered through public subreddit listings and topical keyword searches. Discovery is a coverage strategy, not a census of Reddit.

The newsroom interface presents aggregate community-level results as an interactive network map. Edges are labeled by crossover type so reporters can distinguish NSFW-to-NSFW from NSFW-to-SFW relationships.

## Privacy approach

Participant identifiers are used only in memory during a collection run. The collector does not intentionally write usernames, Reddit user IDs, post bodies, or participant-level identifiers to disk.

The persisted outputs are aggregate files:

- `data/network.json`
- `data/collection_report.json`

Before production use, review Reddit's current Data API terms, Developer Terms, Responsible Builder Policy, and deletion requirements. In particular, do not retain deleted Reddit content or user-identifying information contrary to current Reddit requirements.

## Repository structure

```text
.
├── src/
│   └── collect_reddit.py
├── web/
│   └── index.html
├── data/
├── .env.example
├── .gitignore
├── README.md
└── requirements.txt
```

## Running the collector

1. Install Python 3.10+.
2. Install dependencies:

   `python3 -m pip install -r requirements.txt`

3. Copy `.env.example` to `.env`.
4. Add authorized Reddit OAuth credentials to `.env`.
5. Run the 90-day collector:

   `python3 src/collect_reddit.py --days 90 --discovery-limit 100 --sfw-discovery-limit 100`

The collector writes only aggregate results to `data/`.

## Running the newsroom interface

From the project directory:

`python3 -m http.server 8000 --directory web`

Then open `http://localhost:8000` in a browser.

## Methodological limitations

- Public participation is not the same thing as subscription.
- Neither the NSFW nor SFW discovery process guarantees complete discovery of every subreddit.
- Reddit listings and API access can limit historical coverage, particularly for high-volume communities. The SFW comparison universe is a sampled discovery set, not all SFW Reddit.
- The results represent the specified observation window rather than a permanent audience relationship.
- A community can have observed participants without every participant being captured by the available API retrieval process.

## Intended use

This project is intended for journalistic research, data analysis, and public-interest visualization. It is not intended to moderate communities, post automatically to Reddit, access private user information, or construct individual user profiles.
