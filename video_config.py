"""Validation helpers for script JSON imported from external AI tools."""


def normalize_import_video_config(raw_config=None) -> dict:
    if not isinstance(raw_config, dict):
        return {}

    result = {}
    topic = raw_config.get("topic")
    if isinstance(topic, str) and topic.strip():
        result["topic"] = topic.strip()

    language = raw_config.get("language")
    if language in {"English", "Vietnamese", "Korean", "Japanese"}:
        result["language"] = language

    def bounded_number(field, minimum, maximum, *, integer=False):
        value = raw_config.get(field)
        if isinstance(value, bool):
            return
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
        value = min(max(value, minimum), maximum)
        result[field] = int(round(value)) if integer else value

    bounded_number("total_duration", 15, 18000, integer=True)
    bounded_number("target_seconds_per_scene", 3, 30, integer=True)

    # tts_speed is accepted as a friendly alias; tts_rate remains canonical.
    raw_rate = raw_config.get("tts_rate", raw_config.get("tts_speed"))
    try:
        rate = float(raw_rate)
    except (TypeError, ValueError):
        rate = None
    if rate is not None:
        valid_rates = [0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 2.0]
        result["tts_rate"] = f"{min(valid_rates, key=lambda item: abs(item - rate)):.1f}"

    aspect = str(raw_config.get("aspect_ratio", "")).strip()
    if aspect in {"9:16", "9:16 (Shorts/TikTok)"}:
        result["aspect"] = "9:16 (Shorts/TikTok)"
    elif aspect in {"16:9", "16:9 (YouTube)"}:
        result["aspect"] = "16:9 (YouTube)"

    subtitles = raw_config.get("subtitles")
    if isinstance(subtitles, bool):
        result["subtitles"] = subtitles

    return result
