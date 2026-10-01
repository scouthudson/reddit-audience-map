import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path

import praw
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def discover_communities(reddit, limit, nsfw=True):
    found = {}

    def inspect(label, listing):
        for sub in listing:
            name = getattr(sub, "display_name", None)
            if not name:
                continue
            is_nsfw = bool(getattr(sub, "over18", False))
            if is_nsfw != nsfw:
                continue
            item = found.setdefault(
                name,
                {
                    "name": name,
                    "label": f"r/{name}",
                    "nsfw": nsfw,
                    "discovery_sources": set(),
                },
            )
            item["discovery_sources"].add(label)

    inspect("popular", reddit.subreddits.popular(limit=limit))
    inspect("new", reddit.subreddits.new(limit=limit))

    seeds = (
        ["nsfw", "adult", "gonewild", "porn", "sex", "nude", "nudity", "xxx", "afterdark"]
        if nsfw
        else ["news", "politics", "technology", "science", "sports", "gaming",
              "movies", "music", "books", "food", "travel", "finance",
              "education", "art", "history"]
    )
    per_seed = max(25, min(250, limit // 4))

    for seed in seeds:
        try:
            inspect(
                f"search:{seed}",
                reddit.subreddits.search(
                    seed,
                    sort="relevance",
                    time_filter="all",
                    include_over_18=nsfw,
                    limit=per_seed,
                ),
            )
        except Exception as exc:
            print(f"Discovery warning ({seed}): {exc}")

    for item in found.values():
        item["discovery_sources"] = sorted(item["discovery_sources"])
    return found


def collect_posts_and_comments(reddit, sub_name, cutoff, window_end, observed):
    sub = reddit.subreddit(sub_name)
    posts_seen = comments_seen = 0
    newest = oldest = None

    for post in sub.new(limit=1000):
        created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
        newest = max(newest, created) if newest else created
        oldest = min(oldest, created) if oldest else created
        if created < cutoff:
            break
        if created > window_end:
            continue

        author_id = getattr(post, "author_fullname", None)
        if author_id:
            observed[sub_name].add(author_id)
        posts_seen += 1

        try:
            post.comments.replace_more(limit=0)
            for comment in post.comments.list():
                ctime = datetime.fromtimestamp(comment.created_utc, tz=timezone.utc)
                if ctime < cutoff or ctime > window_end:
                    continue
                cid = getattr(comment, "author_fullname", None)
                if cid:
                    observed[sub_name].add(cid)
                comments_seen += 1
        except Exception as exc:
            print(f"  comment warning r/{sub_name}: {exc}")

    return {
        "posts_seen": posts_seen,
        "comments_seen": comments_seen,
        "observed_participants": len(observed[sub_name]),
        "oldest_activity_retrieved": oldest.isoformat() if oldest else None,
        "newest_activity_retrieved": newest.isoformat() if newest else None,
    }


def build_network(observed, report, output_path):
    nodes = [
        {
            "id": name,
            "label": f"r/{name}",
            "type": report["communities"].get(name, {}).get("type", "NSFW"),
            "observed_users": len(users),
        }
        for name, users in sorted(observed.items())
    ]

    edges = []
    for a, b in combinations(sorted(observed), 2):
        ua, ub = observed[a], observed[b]
        shared = len(ua & ub)
        union = len(ua | ub)
        if shared < 10 or not union:
            continue

        jaccard = shared / union
        if jaccard < 0.001:
            continue

        edges.append({
            "source": a,
            "target": b,
            "shared_users": shared,
            "overlap_a": shared / len(ua) if ua else 0,
            "overlap_b": shared / len(ub) if ub else 0,
            "jaccard": jaccard,
            "crossover": "NSFW-SFW" if (
                report["communities"][a]["type"] != report["communities"][b]["type"]
            ) else report["communities"][a]["type"] + "-" + report["communities"][b]["type"],
        })

    network = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "observation_days": report["observation_days"],
        "observation_start": report["observation_start"],
        "observation_end": report["observation_end"],
        "coverage": {
            "discovery_method": report["discovery_method"],
            "discovered_nsfw_communities": report["nsfw_communities_discovered"],
            "discovered_sfw_communities": report["sfw_communities_discovered"],
            "note": "Observed public activity retrieved through authorized Reddit API access; discovery and historical retrieval may be incomplete.",
        },
        "method": {
            "measure": "observed audience overlap",
            "definition": "Unique public participants observed in both communities during the observation window.",
            "private_subscriptions": False,
            "participant_level_data_persisted": False,
        },
        "nodes": nodes,
        "edges": edges,
    }

    DATA.mkdir(exist_ok=True)
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(json.dumps(network, indent=2), encoding="utf-8")
    print(f"Wrote aggregate network: {len(nodes)} nodes, {len(edges)} edges")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--discovery-limit", type=int, default=100)
    parser.add_argument("--sfw-discovery-limit", type=int, default=100)
    parser.add_argument("--end", help="UTC window end in ISO format; defaults to now")
    parser.add_argument("--output", help="Output JSON path; defaults to data/network_YYYYMMDD_YYYYMMDD.json")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    user_agent = os.getenv("REDDIT_USER_AGENT")
    if not all([client_id, client_secret, user_agent]):
        raise SystemExit("Set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET and REDDIT_USER_AGENT in .env")

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )
    reddit.read_only = True

    now = datetime.now(timezone.utc)
    if args.end:
        now = datetime.fromisoformat(args.end.replace("Z", "+00:00"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
    cutoff = now - timedelta(days=args.days)
    observed = defaultdict(set)

    nsfw_communities = discover_communities(reddit, args.discovery_limit, nsfw=True)
    sfw_communities = discover_communities(reddit, args.sfw_discovery_limit, nsfw=False)
    communities = {**nsfw_communities, **sfw_communities}

    report = {
        "observation_days": args.days,
        "observation_start": cutoff.isoformat(),
        "observation_end": now.isoformat(),
        "discovery_limit": args.discovery_limit,
        "sfw_discovery_limit": args.sfw_discovery_limit,
        "discovery_method": "Reddit subreddit listings plus keyword searches across separate NSFW and SFW discovery universes; not a guaranteed census.",
        "nsfw_communities_discovered": len(nsfw_communities),
        "sfw_communities_discovered": len(sfw_communities),
        "communities_discovered": len(communities),
        "collection": {},
    }

    report["communities"] = {
        name: {
            "label": item["label"],
            "nsfw": item["nsfw"],
            "type": "NSFW" if item["nsfw"] else "SFW",
            "discovery_sources": item["discovery_sources"],
        }
        for name, item in communities.items()
    }

    for index, name in enumerate(sorted(communities), 1):
        print(f"[{index}/{len(communities)}] r/{name}")
        try:
            report["collection"][name] = collect_posts_and_comments(
                reddit, name, cutoff, now, observed
            )
        except Exception as exc:
            report["collection"][name] = {"error": str(exc)}

    DATA.mkdir(exist_ok=True)
    (DATA / "collection_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    default_name = f"network_{cutoff:%Y%m%d}_{now:%Y%m%d}.json"
    output_path = Path(args.output) if args.output else DATA / default_name
    build_network(observed, report, output_path)
    (DATA / "network.json").write_text(output_path.read_text(encoding="utf-8"), encoding="utf-8")


if __name__ == "__main__":
    main()
