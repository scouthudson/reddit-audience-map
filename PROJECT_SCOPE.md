# Project scope for API review

This application is an external newsroom research and visualization tool.

It uses authorized Reddit API access to collect publicly observable posts/comments across multiple communities over a defined observation period, calculate aggregate community-to-community overlap, and publish community-level visualization data.

It does not require installation inside the communities being studied, does not moderate or post to Reddit, and does not attempt to access private subscriptions or other private account information.

The central metric is **observed audience overlap**: unique accounts publicly participating in both communities during the observation period.
