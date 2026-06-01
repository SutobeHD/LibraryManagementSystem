"""Pydantic request models for the library format converter.

Standalone module so BOTH the `POST /api/library/format-swap` route (this
feature) and the sister `library-quality-upgrade-finder` (`trigger=
"quality_verdict"`) import the SAME shapes — the bilateral contract the plan's
Gap 5 / Task T-8 calls for. No app imports → no circular-import risk.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

# Mirror of `app.format_swap_codec.VALID_TARGETS` (kept here too so the model
# validates without importing the codec module). Tests pin they stay in sync.
VALID_TARGETS = ("AIFF", "FLAC", "WAV", "MP3")
VALID_TRIGGERS = ("user_format_pick", "quality_verdict")


class FormatSwapScope(BaseModel):
    """Exactly one of the four scope selectors must be set."""

    track_ids: list[int] | None = None
    playlist_id: int | None = None
    all_m4a: bool = False
    path: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> FormatSwapScope:
        chosen = [
            bool(self.track_ids),
            self.playlist_id is not None,
            bool(self.all_m4a),
            bool(self.path),
        ]
        if sum(chosen) != 1:
            raise ValueError(
                "scope must set exactly one of track_ids / playlist_id / all_m4a / path"
            )
        return self


class FormatSwapOptions(BaseModel):
    force_16bit_flac: bool = False
    mp3_quality: int = Field(0, ge=0, le=9)  # libmp3lame -q:a (0=best VBR)


class FormatSwapReq(BaseModel):
    trigger: str = "user_format_pick"
    scope: FormatSwapScope
    target: str
    dry_run: bool = False
    options: FormatSwapOptions = Field(default_factory=FormatSwapOptions)

    @field_validator("target")
    @classmethod
    def _valid_target(cls, v: str) -> str:
        up = (v or "").upper()
        if up not in VALID_TARGETS:
            raise ValueError(f"target must be one of {VALID_TARGETS}")
        return up

    @field_validator("trigger")
    @classmethod
    def _valid_trigger(cls, v: str) -> str:
        if v not in VALID_TRIGGERS:
            raise ValueError(f"trigger must be one of {VALID_TRIGGERS}")
        return v

    def scope_dict(self) -> dict:
        """Engine-ready scope dict (carries `trigger` for the log marker)."""
        d = self.scope.model_dump()
        d["trigger"] = self.trigger
        return d


class FormatSwapRollbackReq(BaseModel):
    manifest_id: str
