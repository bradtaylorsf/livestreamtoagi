"""YouTube auto-publish pipeline for completed simulation videos.

The orchestrator finalizes a sim → render_simulation_video.py produces an MP4
→ if ``simulation.publish_to_youtube`` is set and ``YOUTUBE_PUBLISH_ENABLED``
is on, ``enqueue_youtube_publish`` spawns ``scripts/publish_simulation_youtube.py``
to upload the MP4 via the YouTube Data API v3.
"""
