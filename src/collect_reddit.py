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


def discover_nsfw(reddit, limit):
    found = {}

    def inspect(label, listing):
        for sub in listing:
            name = getattr(sub, "display_name", None)
            if not name or not getattr(sub, "over18", False):
                continue
            item = found.setdefault(
                name,
                {
                    "name": name,
                    "label": f"r/{name}",
                    "nsfw": True,
                    "discovery_sources": set(),
                },
            )
            item["discovery_sources"].add(label)

    inspect("popular", reddit.subreddits.popular(limit=limit))
    inspect("new", reddit.subreddits.new(limit=limit))

    seeds = [
        "nsfw", "adult", "gonewild", "porn", "sex",
        "nude", "nudity", "xxx", "afterdark",
    ]
    per_seed = max(25, min(250, limit // 4))

    for seed in seeds:
        try:
            inspect(
                f"search:{seed}",
                reddit.subreddits.search(
                    seed,
                    sort="relevance",
                    time_filter="all",
                    include_over_18=True,
                    limit=per_seed,
                ),
            )
        except Exception as exc:
            print(f"Discovery warning ({seed}): {exc}")

    for item in found.values():
        item["discovery_sources"] = sorted(item["discovery_sources"])
    return found


def collect_posts_and_comments(reddit, sub_name, cutoff, observed):
    sub = reddit.subreddit(sub_name)
    posts_seen = comments_seen = 0
    newest = oldest = None

    for post in sub.new(limit=1000):
        created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
        newest = max(newest, created) if newest else created
        oldest = min(oldest, created) if oldest else created

        if created < cutoff:
            break

        author_id = getattr(post, "author_fullname", None)
        if author_id:
            observed[sub_name].add(author_id)
        posts_seen += 1

        try:
            post.comments.replace_more(limit=0)
            for comment in post.comments.list():
                ctime = datetime.fromtimestamp(
                    comment.created_utc, tz=timezone.utc
                )
                if ctime < cutoff:
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


def build_network(observed, report):
    nodes = [
        {
            "id": name,
            "label": f"r/{name}",
            "type": "NSFW",
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

        edges.append(
            {
                "source": a,
                "target": b,
                "shared_users": shared,
                "overlap_a": shared / len(ua) if ua else 0,
                "overlap_b": shared / len(ub) if ub else 0,
                "jaccard": jaccard,
            }
        )

    network = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "observation_days": report["observation_days"],
        "observation_start": report["observation_start"],
        "observation_end": report["observation_end"],
        "coverage": {
            "discovery_method": report["discovery_method"],
            "discovered_nsfw_communities": report["communities_discovered"],
            "note": (
                "Observed public activity retrieved through authorized Reddit "
                "API access; coverage may be incomplete for high-volume communities."
            ),
        },
        "method": {
            "measure": "observed audience overlap",
            "definition": (
                "Unique public participants observed in both communities "
                "during the observation window."
            ),
            "private_subscriptions": False,
            "participant_level_data_persisted": False,
        },
        "nodes": nodes,
        "edges": edges,
    }

    DATA.mkdir(exist_ok=True)
    (DATA / "network.json").write_text(
        json.dumps(network, indent=2), encoding="utf-8"
    )
    print(f"Wrote aggregate network: {len(nodes)} nodes, {len(edges)} edges")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--discovery-limit", type=int, default=100)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    user_agent = os.getenv("REDDIT_USER_AGENT")

    if not all([client_id, client_secret, user_agent]):
        raise SystemExit(
            "Set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET and "
            "REDDIT_USER_AGENT in .env"
        )

    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )
    reddit.read_only = True

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=args.days)
    observed = defaultdict(set)

    communities = discover_nsfw(reddit, args.discovery_limit)
    print(
        f"Discovered {len(communities)} NSFW communities "
        "from available discovery surfaces."
    )

    report = {
        "observation_days": args.days,
        "observation_start": cutoff.isoformat(),
        "observation_end": now.isoformat(),
        "discovery_limit": args.discovery_limit,
        "discovery_method": (
            "Reddit subreddit listings plus keyword searches; "
            "not a guaranteed census."
        ),
        "communities_discovered": len(communities),
        "collection": {},
    }

    for index, name in enumerate(sorted(communities), 1):
        print(f"[{index}/{len(communities)}] r/{name}")
        try:
            report["collection"][name] = collect_posts_and_comments(
                reddit, name, cutoff, observed
            )
        except Exception as exc:
            report["collection"][name] = {"error": str(exc)}

    report["communities"] = {
        name: {
            "label": item["label"],
            "nsfw": True,
            "discovery_sources": item["discovery_sources"],
        }
        for name, item in communities.items()
    }

    DATA.mkdir(exist_ok=True)
    (DATA / "collection_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    # Participant IDs exist only in process memory and are never serialized.
    build_network(observed, report)


if __name__ == "__main__":
    main()
