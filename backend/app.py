"""Standalone Flask service for the adaptive English speaking agent."""

import glob
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(__file__).resolve().parent / "data"
FRONTEND_DIR = ROOT_DIR / "frontend"

# Load local configuration before importing modules that construct LLM clients.
load_dotenv(ROOT_DIR / ".env")

from assistants.english_assistant import (  # noqa: E402
    _get_review_expressions,
    generate_practice,
    get_today_expression,
)
from assistants.english_learning_agent import (  # noqa: E402
    get_dashboard,
    get_profile,
    record_attempts,
    save_profile,
)


app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
app.config["JSON_AS_ASCII"] = False


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"error": "请求内容过大"}), 413


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "img-src 'self' data:"
    )
    return response


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _day_path(day):
    return DATA_DIR / f"day{day}.json"


@app.get("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/health")
def health():
    return jsonify({
        "service": "adaptive-english-speaking-agent",
        "status": "healthy",
    })


@app.get("/api/english/today")
def english_today():
    try:
        data = get_today_expression()
        _write_json(str(_day_path(data["day"])), data)
        return jsonify(data)
    except Exception:
        app.logger.exception("Failed to generate today's English lesson")
        return jsonify({"error": "内容生成失败，请检查模型配置和服务日志"}), 500


@app.get("/api/english/history")
def english_history():
    try:
        days = []
        for filepath in glob.glob(str(DATA_DIR / "day*.json")):
            filename = os.path.basename(filepath)
            day_number = int(filename.removeprefix("day").removesuffix(".json"))
            data = _read_json(filepath)
            days.append({
                "day": day_number,
                "date": data.get("date", ""),
                "expression_count": len(data.get("expressions", [])),
            })
        days.sort(key=lambda item: item["day"])
        return jsonify({"days": days})
    except (OSError, ValueError, json.JSONDecodeError):
        app.logger.exception("Failed to read lesson history")
        return jsonify({"error": "历史学习数据读取失败"}), 500


@app.get("/api/english/day/<int:day>")
def english_day(day):
    path = _day_path(day)
    if not path.exists():
        return jsonify({"error": f"Day {day} 不存在"}), 404
    try:
        return jsonify(_read_json(path))
    except (OSError, json.JSONDecodeError):
        app.logger.exception("Failed to read lesson day %s", day)
        return jsonify({"error": "学习内容读取失败"}), 500


@app.get("/api/english/practice/<int:day>")
def english_practice(day):
    cache_path = DATA_DIR / f"practice_day{day}.json"
    try:
        if cache_path.exists():
            return jsonify(_read_json(cache_path))

        lesson_path = _day_path(day)
        if not lesson_path.exists():
            return jsonify({"error": f"Day {day} 不存在"}), 404
        lesson = _read_json(lesson_path)
        reviews = _get_review_expressions(day, count=5)
        generated = generate_practice(day, lesson["expressions"], reviews)
        result = {
            "day": day,
            "date": lesson.get("date", ""),
            "exercises": generated.get("exercises", []),
            "review_note": generated.get("review_note", ""),
            "review_expressions": reviews,
        }
        _write_json(str(cache_path), result)
        return jsonify(result)
    except Exception:
        app.logger.exception("Failed to generate practice for day %s", day)
        return jsonify({"error": "练习生成失败，请检查模型配置和服务日志"}), 500


@app.route("/api/english/profile", methods=["GET", "PUT"])
def english_profile():
    try:
        if request.method == "GET":
            return jsonify(get_profile())
        return jsonify(save_profile(request.get_json(silent=True) or {}))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception:
        app.logger.exception("Failed to read or update learner profile")
        return jsonify({"error": "学习画像处理失败"}), 500


@app.get("/api/english/dashboard")
def english_dashboard():
    try:
        return jsonify(get_dashboard())
    except Exception:
        app.logger.exception("Failed to build learning dashboard")
        return jsonify({"error": "学习计划读取失败"}), 500


@app.post("/api/english/attempts")
def english_attempts():
    try:
        data = request.get_json(silent=True) or {}
        result = record_attempts(data.get("day", 0), data.get("attempts", []))
        return jsonify({
            "session": result["session"],
            "dashboard": get_dashboard(),
        })
    except (TypeError, ValueError) as error:
        return jsonify({"error": str(error)}), 400
    except Exception:
        app.logger.exception("Failed to record learning attempts")
        return jsonify({"error": "练习记录保存失败"}), 500


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
    )
