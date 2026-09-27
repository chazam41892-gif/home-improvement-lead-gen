from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit


def canonicalize_linkedin_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value if "://" in value else f"https://{value}")
    host = parsed.netloc.lower().removeprefix("www.")
    if host != "linkedin.com":
        return value
    path = parsed.path.rstrip("/")
    return urlunsplit(("https", "www.linkedin.com", path, "", ""))


@dataclass
class Engagement:
    post_urn: str
    actor_urn: str = ""
    profile_url: str = ""
    action: str = ""
    actions: list[str] = field(default_factory=list)
    name: str = ""
    headline: str = ""
    comment_text: str = ""

    def __post_init__(self):
        self.profile_url = canonicalize_linkedin_url(self.profile_url)
        normalized = self.action.strip().upper()
        if normalized and normalized not in self.actions:
            self.actions.append(normalized)

    @property
    def identity_key(self) -> str:
        return self.actor_urn.strip() or self.profile_url


@dataclass(frozen=True)
class ViralScore:
    weighted_engagement: int
    velocity: float
    is_viral: bool


def score_post(reactions: int, comments: int, reposts: int, age_hours: float | None) -> ViralScore:
    weighted = max(reactions, 0) + max(comments, 0) * 3 + max(reposts, 0) * 4
    velocity = round(weighted / max(float(age_hours), 1.0), 2) if age_hours is not None else 0.0
    return ViralScore(weighted, velocity, weighted >= 150 or velocity >= 50.0)


def deduplicate_engagements(engagements: Iterable[Engagement]) -> list[Engagement]:
    indexed: dict[str, Engagement] = {}
    for engagement in engagements:
        key = engagement.identity_key
        if not key:
            continue
        current = indexed.get(key)
        if current is None:
            indexed[key] = engagement
            continue
        for action in engagement.actions:
            if action not in current.actions:
                current.actions.append(action)
        if engagement.name and not current.name:
            current.name = engagement.name
        if engagement.headline and not current.headline:
            current.headline = engagement.headline
        if engagement.comment_text:
            current.comment_text = "\n".join(filter(None, [current.comment_text, engagement.comment_text]))
    return list(indexed.values())
