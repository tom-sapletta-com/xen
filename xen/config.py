"""Configuration and data directory management."""

import os
from pathlib import Path


def get_data_dir() -> Path:
    """Zwróć katalog danych xen."""
    env = os.environ.get("XEN_DATA_DIR")
    if env:
        p = Path(env)
    else:
        p = Path.home() / ".xen"
    p.mkdir(parents=True, exist_ok=True)
    (p / "sessions").mkdir(exist_ok=True)
    (p / "exports").mkdir(exist_ok=True)
    return p


# Predefiniowane rozmiary dla social media
CROP_PRESETS = {
    "instagram_post": {"w": 1080, "h": 1080, "label": "Instagram Post (1:1)"},
    "instagram_story": {"w": 1080, "h": 1920, "label": "Instagram Story (9:16)"},
    "twitter_post": {"w": 1200, "h": 675, "label": "Twitter/X Post (16:9)"},
    "linkedin_post": {"w": 1200, "h": 627, "label": "LinkedIn Post"},
    "facebook_post": {"w": 1200, "h": 630, "label": "Facebook Post"},
    "youtube_thumb": {"w": 1280, "h": 720, "label": "YouTube Thumbnail (16:9)"},
    "og_image": {"w": 1200, "h": 630, "label": "OG Image"},
    "widescreen": {"w": 1920, "h": 1080, "label": "Widescreen (16:9)"},
    "square": {"w": 1080, "h": 1080, "label": "Square (1:1)"},
    "portrait": {"w": 1080, "h": 1350, "label": "Portrait (4:5)"},
}

# Linki do publikacji
SOCIAL_LINKS = {
    "twitter": "https://twitter.com/intent/tweet?text={text}&url={url}",
    "linkedin": "https://www.linkedin.com/sharing/share-offsite/?url={url}",
    "facebook": "https://www.facebook.com/sharer/sharer.php?u={url}",
    "reddit": "https://reddit.com/submit?url={url}&title={text}",
    "hackernews": "https://news.ycombinator.com/submitlink?u={url}&t={text}",
    "telegram": "https://t.me/share/url?url={url}&text={text}",
    "whatsapp": "https://wa.me/?text={text}%20{url}",
}
