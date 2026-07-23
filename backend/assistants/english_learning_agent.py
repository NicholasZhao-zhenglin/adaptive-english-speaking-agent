"""自适应英语学习 Agent：画像、掌握度、复习调度与学习诊断。"""

import json
import os
import re
import threading
from copy import deepcopy
from datetime import datetime, timedelta


DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PROFILE_FILE = os.path.join(DATA_DIR, "english_profile.json")
STATE_FILE = os.path.join(DATA_DIR, "english_learning_state.json")
SESSIONS_FILE = os.path.join(DATA_DIR, "english_sessions.json")

VALID_LEVELS = {"A1", "A2", "B1", "B2", "C1"}
DEFAULT_PROFILE = {
    "goals": ["日常交流"],
    "level": "B1",
    "daily_minutes": 15,
    "interests": [],
}
ERROR_LABELS = {
    "recognition": "含义辨认",
    "recall": "主动回忆",
    "context": "场景运用",
    "matching": "表达配对",
}
EXERCISE_FOCUS = {
    "recognition": "含义辨认与对比",
    "recall": "填空与主动回忆",
    "context": "场景选择与角色扮演",
    "matching": "表达与含义配对",
}
EXERCISE_MIXES = {
    "recognition": {"multiple_choice": 5, "fill_blank": 2, "matching": 1, "scenario_choice": 2},
    "recall": {"multiple_choice": 2, "fill_blank": 5, "matching": 1, "scenario_choice": 2},
    "context": {"multiple_choice": 2, "fill_blank": 2, "matching": 1, "scenario_choice": 5},
    "matching": {"multiple_choice": 3, "fill_blank": 2, "matching": 2, "scenario_choice": 3},
}
EXERCISE_TO_ERROR = {
    "multiple_choice": "recognition",
    "fill_blank": "recall",
    "scenario_choice": "context",
    "matching": "matching",
}

_file_lock = threading.RLock()


def _now_local():
    """使用系统本地时区，确保每日复习边界符合用户所在日期。"""
    return datetime.now().astimezone()


def _read_json(path, default):
    with _file_lock:
        if not os.path.exists(path):
            return deepcopy(default)
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)


def _write_json(path, value):
    with _file_lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)


def _normalize_list(value, fallback=None, limit=8):
    if not isinstance(value, list):
        return list(fallback or [])
    result = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text[:40])
    return result[:limit] or list(fallback or [])


def _expression_key(expression):
    text = re.sub(r"[^\w\s']", "", expression.strip().lower())
    return re.sub(r"\s+", " ", text)


def get_profile():
    profile = _read_json(PROFILE_FILE, DEFAULT_PROFILE)
    return {**DEFAULT_PROFILE, **profile}


def save_profile(data):
    data = data if isinstance(data, dict) else {}
    level = str(data.get("level", DEFAULT_PROFILE["level"])).upper().strip()
    if level not in VALID_LEVELS:
        level = DEFAULT_PROFILE["level"]
    try:
        daily_minutes = int(data.get("daily_minutes", DEFAULT_PROFILE["daily_minutes"]))
    except (TypeError, ValueError):
        daily_minutes = DEFAULT_PROFILE["daily_minutes"]

    profile = {
        "goals": _normalize_list(data.get("goals"), DEFAULT_PROFILE["goals"], limit=4),
        "level": level,
        "daily_minutes": max(5, min(60, daily_minutes)),
        "interests": _normalize_list(data.get("interests"), limit=8),
        "updated_at": _now_local().isoformat(),
    }
    _write_json(PROFILE_FILE, profile)
    return profile


def _load_state():
    return _read_json(STATE_FILE, {"version": 1, "items": {}, "error_totals": {}})


def _load_sessions():
    return _read_json(SESSIONS_FILE, [])


def _next_interval(streak):
    intervals = {1: 1, 2: 3, 3: 7, 4: 14}
    return intervals.get(streak, 30)


def record_attempts(day, attempts, now=None):
    """串行更新状态和会话，避免并发请求互相覆盖。"""
    with _file_lock:
        return _record_attempts_locked(day, attempts, now=now)


def _record_attempts_locked(day, attempts, now=None):
    """记录一轮练习，并更新表达级掌握度和下一次复习日期。"""
    if not isinstance(attempts, list) or not attempts:
        raise ValueError("attempts 必须是非空数组")
    if len(attempts) > 100:
        raise ValueError("每次最多提交 100 条练习结果")
    try:
        day = int(day)
    except (TypeError, ValueError) as error:
        raise ValueError("day 必须是整数") from error
    if day < 0 or day > 100000:
        raise ValueError("day 超出有效范围")
    now = now or _now_local()
    state = _load_state()
    items = state.setdefault("items", {})
    error_totals = state.setdefault("error_totals", {})
    normalized_attempts = []

    for attempt in attempts:
        expression = str(attempt.get("expression", "")).strip()
        if not expression:
            continue
        if len(expression) > 200:
            raise ValueError("expression 最长 200 个字符")
        if not isinstance(attempt.get("correct"), bool):
            raise ValueError("correct 必须是布尔值")
        key = _expression_key(expression)
        if not key:
            raise ValueError("expression 必须包含字母、数字或文字")
        correct = attempt["correct"]
        exercise_type = str(attempt.get("exercise_type", "unknown"))[:40]
        error_type = str(attempt.get("error_type") or EXERCISE_TO_ERROR.get(exercise_type, "recall"))
        if error_type not in ERROR_LABELS:
            error_type = EXERCISE_TO_ERROR.get(exercise_type, "recall")
        item = items.setdefault(key, {
            "expression": expression,
            "meaning": str(attempt.get("meaning", "")).strip()[:200],
            "seen_count": 0,
            "correct_count": 0,
            "wrong_count": 0,
            "streak": 0,
            "mastery": 0.0,
            "error_counts": {},
        })
        if attempt.get("meaning"):
            item["meaning"] = str(attempt["meaning"]).strip()[:200]
        item["seen_count"] = int(item.get("seen_count", 0)) + 1
        item["last_practiced_at"] = now.isoformat()

        if correct:
            item["correct_count"] = int(item.get("correct_count", 0)) + 1
            item["streak"] = int(item.get("streak", 0)) + 1
            item["mastery"] = round(min(1.0, float(item.get("mastery", 0)) * 0.65 + 0.35), 3)
            interval = _next_interval(item["streak"])
            item["next_review_at"] = (now + timedelta(days=interval)).date().isoformat()
        else:
            item["wrong_count"] = int(item.get("wrong_count", 0)) + 1
            item["streak"] = 0
            item["mastery"] = round(float(item.get("mastery", 0)) * 0.6, 3)
            item["next_review_at"] = now.date().isoformat()
            errors = item.setdefault("error_counts", {})
            errors[error_type] = int(errors.get(error_type, 0)) + 1
            error_totals[error_type] = int(error_totals.get(error_type, 0)) + 1

        normalized_attempts.append({
            "expression": expression,
            "correct": correct,
            "exercise_type": exercise_type,
            "error_type": None if correct else error_type,
        })

    if not normalized_attempts:
        raise ValueError("至少需要一个包含 expression 的练习结果")

    correct_count = sum(1 for item in normalized_attempts if item["correct"])
    session = {
        "day": day,
        "attempt_count": len(normalized_attempts),
        "correct_count": correct_count,
        "accuracy": round(correct_count / len(normalized_attempts), 3),
        "attempts": normalized_attempts,
        "completed_at": now.isoformat(),
    }
    state["updated_at"] = now.isoformat()
    sessions = _load_sessions()
    sessions.append(session)
    _write_json(STATE_FILE, state)
    _write_json(SESSIONS_FILE, sessions[-100:])
    return {"session": session, **state}


def get_due_reviews(count=6, today=None):
    today = today or _now_local()
    today_text = today.date().isoformat()
    items = _load_state().get("items", {})
    due = [
        item for item in items.values()
        if item.get("next_review_at", today_text) <= today_text
    ]
    due.sort(key=lambda item: (
        item.get("next_review_at", ""),
        float(item.get("mastery", 0)),
        -int(item.get("wrong_count", 0)),
    ))
    return [deepcopy(item) for item in due[:max(0, int(count))]]


def _recent_accuracy(sessions):
    recent = [float(item.get("accuracy", 0)) for item in sessions[-5:] if "accuracy" in item]
    return round(sum(recent) / len(recent), 3) if recent else None


def build_daily_plan(today=None):
    """根据目标、近期表现和错因生成可解释的每日计划。"""
    today = today or _now_local()
    profile = get_profile()
    sessions = _load_sessions()
    state = _load_state()
    accuracy = _recent_accuracy(sessions)
    goals = profile["goals"]
    theme = goals[(today.toordinal() - 1) % len(goals)]

    if accuracy is not None and accuracy < 0.6:
        new_count, review_count = 4, 8
        reason = f"近期正确率 {accuracy:.0%}，今天降低新内容比例并强化复习。"
    elif accuracy is not None and accuracy >= 0.85:
        new_count, review_count = 8, 4
        reason = f"近期正确率 {accuracy:.0%}，今天适度增加新表达。"
    else:
        new_count, review_count = 6, 6
        reason = "暂无稳定表现数据，采用均衡的新学与复习比例。" if accuracy is None else f"近期正确率 {accuracy:.0%}，保持均衡训练。"

    error_totals = state.get("error_totals", {})
    weakest = max(error_totals, key=error_totals.get) if error_totals else "context"
    interests = profile.get("interests", [])
    context_hint = "、".join(interests[:2]) if interests else theme
    return {
        "date": today.date().isoformat(),
        "theme": theme,
        "level": profile["level"],
        "daily_minutes": profile["daily_minutes"],
        "new_expression_count": new_count,
        "review_expression_count": review_count,
        "exercise_focus": EXERCISE_FOCUS.get(weakest, EXERCISE_FOCUS["context"]),
        "exercise_mix": deepcopy(EXERCISE_MIXES.get(weakest, EXERCISE_MIXES["context"])),
        "weakest_dimension": ERROR_LABELS.get(weakest, weakest),
        "context_hint": context_hint,
        "reason": reason,
    }


def get_dashboard(today=None):
    today = today or _now_local()
    state = _load_state()
    sessions = _load_sessions()
    items = list(state.get("items", {}).values())
    due = get_due_reviews(count=20, today=today)
    error_totals = state.get("error_totals", {})
    weaknesses = [
        {"type": key, "label": ERROR_LABELS.get(key, key), "count": value}
        for key, value in sorted(error_totals.items(), key=lambda pair: pair[1], reverse=True)
    ]
    accuracy = _recent_accuracy(sessions)
    return {
        "profile": get_profile(),
        "plan": build_daily_plan(today=today),
        "stats": {
            "learned_count": len(items),
            "mastered_count": sum(1 for item in items if float(item.get("mastery", 0)) >= 0.8),
            "due_count": len(due),
            "recent_accuracy": accuracy,
            "session_count": len(sessions),
        },
        "weaknesses": weaknesses[:4],
        "due_reviews": due[:8],
    }
