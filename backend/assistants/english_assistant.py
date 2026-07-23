"""
英语口语助手 v3
- 每天推送 10 个高频口语表达
- 本地去重：LLM 不感知记忆库，生成后在本地做规则匹配
- 缺几个补几个，直到凑够 10 个不重复的
- 记忆库 + Day 计数 + 缓存
"""

import json
import os
from datetime import datetime
from openai import OpenAI

from .english_learning_agent import build_daily_plan, get_due_reviews

# ---------- 配置 ----------
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
API_BASE = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MEMORY_FILE = os.path.join(DATA_DIR, "english_memory.json")
TODAY_FILE = os.path.join(DATA_DIR, "english_today.json")


# ============================================================================
#  记忆库
# ============================================================================

def _load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"day_count": 0, "history": []}


def _save_memory(memory):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)


# ============================================================================
#  本地去重引擎（零 token 消耗）
# ============================================================================

def _normalize(text):
    """标准化：去空格、去标点、全小写，用于模糊比较"""
    import re
    text = text.strip().lower()
    text = re.sub(r"[^\w\s]", "", text)   # 去掉标点
    text = re.sub(r"\s+", " ", text)      # 合并空格
    return text


def _is_duplicate(expression, history):
    """
    判断 expression 是否和 history 中的某个表达重复。
    策略：完全匹配 > 标准化匹配（大小写/标点） > 模糊匹配（编辑距离）
    """
    norm_new = _normalize(expression)
    new_words = set(norm_new.split())

    for old in history:
        norm_old = _normalize(old)
        if norm_new == norm_old:
            return True

        # 如果两句话的核心词高度重叠（短句判断）
        old_words = set(norm_old.split())
        if len(new_words) <= 6 and len(old_words) <= 6:
            overlap = new_words & old_words
            if len(overlap) >= len(new_words) * 0.5 and len(overlap) >= len(old_words) * 0.5:
                return True

    return False


def _dedup(expressions, history):
    """返回 (去重后的表达列表, 重复数量)"""
    valid = []
    duplicates = 0
    seen = list(history)
    for expr in expressions:
        if _is_duplicate(expr["expression"], seen):
            duplicates += 1
        else:
            valid.append(expr)
            seen.append(expr["expression"])
    return valid, duplicates


# ============================================================================
#  LLM 调用
# ============================================================================

SYSTEM_PROMPT = """你是一名专业的英语口语教练，帮助英语阅读和听力较强、但口语输出薄弱的学习者。

输出必须是严格的 JSON 格式，不要输出任何其他文字。JSON 结构如下：
{
  "expressions": [
    {
      "expression": "英文表达（短小精悍，适合脱口而出）",
      "meaning": "中文含义",
      "scene": "使用场景说明（中文）",
      "example": "包含该表达的自然英文例句",
      "example_cn": "例句的中文翻译"
    }
  ],
  "practice": {
    "scenario": "一个真实生活场景（中文）",
    "task": "要求学习者用今天学的表达完成的小任务（中文）"
  },
  "review_note": "复习提醒（中文）"
}

硬性要求：
1. expressions 数组长度必须恰好等于要求的数量
2. 优先选英语母语者真正会说的表达，不是教材英语
3. 表达短小、简单，适合直接脱口而出
4. 覆盖不同场景：日常聊天、社交、工作学习、情绪表达、请求帮助、表达观点、购物吃饭出行
5. 难度根据 day_number 调整
6. review_note 必须具体提到本次生成的至少2-3个表达，给出针对性的复习建议。绝对不要提到其他天的表达，不要泛泛而谈"""


FILL_SYSTEM_PROMPT = """你是一名英语口语教练。你只需要输出一个 JSON 数组，包含指定数量的英语口语表达。

格式：[{"expression": "...", "meaning": "...", "scene": "...", "example": "...", "example_cn": "..."}]

硬性要求：
- 数组长度必须恰好等于要求的数量
- 每个表达短小、地道、适合脱口而出
- 绝对不能输出 EXCLUDE 列表中提到的任何表达"""


def _call_llm(messages, max_tokens=3000):
    """通用 LLM 调用"""
    client = OpenAI(api_key=API_KEY, base_url=API_BASE)
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.9,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(content.strip())


def _generate_batch(count, day_number, exclude_expressions=None, plan=None):
    """
    生成 count 个表达。如果 exclude_expressions 不为空，要求 LLM 排除它们。
    只在补充生成时传 exclude 列表（通常很短），主力生成不传。
    """
    if exclude_expressions:
        # 补充生成模式：只传需要排除的短列表
        exclude_text = "\n".join(f"- {e}" for e in exclude_expressions)
        plan_hint = ""
        if plan:
            plan_hint = f"\n学习主题：{plan['theme']}；水平：{plan['level']}；场景偏好：{plan['context_hint']}。"
        user_prompt = f"""请生成 {count} 个新的英语口语表达（Day {day_number} 难度）。{plan_hint}

=== 必须排除以下表达（不要生成相同或极其相似的） ===
{exclude_text}

请只输出 JSON 数组。"""
        messages = [
            {"role": "system", "content": FILL_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        result = _call_llm(messages, max_tokens=1500)
        # _call_llm 返回的就是数组
        return result
    else:
        plan = plan or {
            "theme": "日常交流",
            "level": "B1",
            "context_hint": "真实生活",
            "exercise_focus": "场景选择与角色扮演",
        }
        # 主力生成模式：由学习计划决定主题、难度和数量。
        user_prompt = f"""今天是第 {day_number} 天。请生成 {count} 个高频口语表达，包含 practice 和 review_note。

学习者水平：{plan['level']}
今日主题：{plan['theme']}
兴趣或语境：{plan['context_hint']}
重点练习方式：{plan['exercise_focus']}
难度补充：{"入门级，挑选最基础、最高频的表达" if day_number <= 7 else "稍有提升，可加入常用短语动词" if day_number <= 30 else "加入一些地道习语和习惯搭配"}

重要：review_note 必须提到本次生成的具体表达（至少2-3个），并给出针对这些表达的复习建议。不要使用模板化的提醒，每天都要不同。"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        result = _call_llm(messages)
        return result["expressions"], result["practice"], result["review_note"]


# ============================================================================
#  主接口
# ============================================================================

def get_today_expression():
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 1. 缓存命中
    if os.path.exists(TODAY_FILE):
        with open(TODAY_FILE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if cached.get("date") == today_str:
            return cached

    # 2. 加载记忆库
    memory = _load_memory()
    day_number = memory["day_count"] + 1
    history = memory["history"]
    learning_plan = build_daily_plan()
    target_count = learning_plan["new_expression_count"]

    # 3. 按 Agent 计划生成新内容（不传完整 history，避免 token 浪费）
    expressions, practice, review_note = _generate_batch(
        target_count, day_number, plan=learning_plan
    )

    # 4. 本地去重
    valid, dup_count = _dedup(expressions, history)
    total_api_calls = 1

    # 5. 缺几个补几个
    fill_attempts = 0
    while len(valid) < target_count and fill_attempts < 5:
        fill_attempts += 1
        missing = target_count - len(valid)
        # 多要 2 个做冗余，减少循环次数
        batch_size = min(missing + 2, 10)
        # 补充生成时，排除所有已知表达（当前 valid + 全部 history）
        exclude_for_fill = [e["expression"] for e in valid] + history
        fill_expressions = _generate_batch(
            batch_size, day_number, exclude_for_fill, plan=learning_plan
        )
        total_api_calls += 1

        # 再次去重
        fill_valid, _ = _dedup(
            fill_expressions,
            history + [item["expression"] for item in valid],
        )
        for expr in fill_valid:
            if len(valid) >= target_count:
                break
            valid.append(expr)

    if len(valid) < target_count:
        raise RuntimeError("英语表达补位失败：连续 5 次仍未获得足够的不重复内容")

    # 6. 只取计划要求的数量
    valid = valid[:target_count]

    # 7. 组装结果
    result = {
        "day": day_number,
        "date": today_str,
        "expressions": valid,
        "practice": practice,
        "review_note": review_note,
        "learning_plan": learning_plan,
        "_api_calls": total_api_calls,  # 调试信息，前端不展示
    }

    # 8. 更新记忆库
    memory["day_count"] = day_number
    memory["history"].extend(e["expression"] for e in valid)
    _save_memory(memory)

    # 9. 缓存今日
    with open(TODAY_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


if __name__ == "__main__":
    import sys
    if r"D:\Lib\site-packages" not in sys.path:
        sys.path.insert(0, r"D:\Lib\site-packages")
    result = get_today_expression()
    print(f"Day {result['day']} | API 调用次数: {result.get('_api_calls', '?')}")
    print(f"表达数量: {len(result['expressions'])}")
    for i, e in enumerate(result["expressions"], 1):
        print(f"  {i}. {e['expression']}")


# ============================================================================
#  互动练习题生成
# ============================================================================

PRACTICE_SYSTEM_PROMPT = """你是一名专业的英语口语教师，现在需要为学习者生成交互式练习题。
输出必须是严格的 JSON 格式，不要输出任何其他文字、不要用 markdown 代码块包裹。"""


def _build_practice_prompt(day_number, today_text, review_text, plan=None):
    """构建练习题生成的 user prompt（避免 format 转义问题）"""
    plan = plan or build_daily_plan()
    mix = plan["exercise_mix"]
    return f"""请根据以下表达生成交互式练习题。

=== 今日新学表达（Day {day_number}）===
{today_text}

=== 复习表达（之前学过的）===
{review_text}

请生成以下类型的练习题，确保覆盖所有今日新学表达：

Agent 诊断的重点训练方向是“{plan['exercise_focus']}”。请按以下动态题型配比生成：
1. 选择题（multiple_choice）{mix['multiple_choice']}题：给出英文表达，选择正确的中文含义
2. 填空题（fill_blank）{mix['fill_blank']}题：给出场景描述，在句子的空格处填入正确的英文表达
3. 连线题（matching）{mix['matching']}题：将5个英文表达与其中文含义配对（从今日和复习中各选一些）
4. 场景应用题（scenario_choice）{mix['scenario_choice']}题：给出生活场景，选择最合适的表达

同时生成一个复习提醒（review_note），必须具体提到今天 Day {day_number} 的表达内容，给出有针对性的复习建议。

输出格式（严格 JSON）：
{{
  "exercises": [
    {{
      "type": "multiple_choice",
      "question": "\\"英文表达\\" 是什么意思？",
      "options": ["正确含义", "错误含义1", "错误含义2", "错误含义3"],
      "answer": 0,
      "explanation": "解析说明",
      "expression": "对应的表达"
    }},
    {{
      "type": "fill_blank",
      "question": "场景描述，句子中用 ____ 表示空格",
      "answer": "正确答案（英文表达，不含标点）",
      "hint": "中文提示",
      "expression": "对应的表达"
    }},
    {{
      "type": "matching",
      "title": "将英文表达与中文含义配对",
      "pairs": [
        {{"left": "英文表达", "right": "中文含义"}},
        {{"left": "英文表达", "right": "中文含义"}},
        {{"left": "英文表达", "right": "中文含义"}},
        {{"left": "英文表达", "right": "中文含义"}},
        {{"left": "英文表达", "right": "中文含义"}}
      ]
    }},
    {{
      "type": "scenario_choice",
      "question": "场景描述",
      "options": ["表达A", "表达B", "表达C", "表达D"],
      "answer": 1,
      "explanation": "解析说明",
      "expression": "对应的表达"
    }}
  ],
  "review_note": "基于今天 Day {day_number} 具体表达的复习建议，必须提到至少2-3个今天的表达"
}}

硬性要求：
- 选择题选项顺序必须打乱，answer 是正确选项的索引（从 0 开始）
- 填空题的 answer 不要包含标点符号，比较时不区分大小写
- 连线题至少 5 对，左右顺序都要打乱
- 场景应用题要混合使用今日新学和复习表达作为选项
- review_note 必须提到今天的至少 2-3 个具体表达，不要使用模板化语言
- 所有练习题加起来要覆盖所有今日新学表达
- 只输出 JSON，不要输出任何其他内容"""


def _get_review_expressions(day_number, count=5):
    """优先选择到期且掌握度低的表达，不足时再从历史随机补充。"""
    import random
    review = []
    due_reviews = get_due_reviews(count=count)
    for item in due_reviews:
        review.append({
            "expression": item["expression"],
            "meaning": item.get("meaning", ""),
            "scene": item.get("scene", "历史薄弱表达"),
            "source": "adaptive_scheduler",
        })
    if len(review) >= count:
        return review[:count]

    selected = {item["expression"].strip().lower() for item in review}
    fallback = []
    for d in range(1, day_number):
        filepath = os.path.join(DATA_DIR, f"day{d}.json")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            for expr in data.get("expressions", []):
                if expr["expression"].strip().lower() in selected:
                    continue
                fallback.append({
                    "expression": expr["expression"],
                    "meaning": expr["meaning"],
                    "scene": expr["scene"],
                    "source_day": d,
                })
    missing = count - len(review)
    if len(fallback) > missing:
        fallback = random.sample(fallback, missing)
    return review + fallback


def generate_practice(day_number, today_expressions, review_expressions):
    """
    调用 LLM 生成交互式练习题。
    - today_expressions: 今日的 10 个表达（完整 dict 列表）
    - review_expressions: 从历史天数中抽取的复习表达
    返回: {exercises: [...], review_note: "..."}
    """
    today_text = "\n".join(
        f"- {e['expression']}：{e['meaning']}（场景：{e['scene']}）"
        for e in today_expressions
    )
    review_text = "\n".join(
        f"- {e['expression']}：{e['meaning']}（场景：{e['scene']}，Day {e.get('source_day', '?')}）"
        for e in review_expressions
    ) if review_expressions else "（暂无历史表达）"

    plan = build_daily_plan()
    user_prompt = _build_practice_prompt(day_number, today_text, review_text, plan=plan)

    messages = [
        {"role": "system", "content": PRACTICE_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    result = _call_llm(messages, max_tokens=4000)

    # 给每个练习题加 ID
    for i, ex in enumerate(result.get("exercises", [])):
        ex["id"] = i + 1

    return result
