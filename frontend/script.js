const state = {
    days: [],
    currentDay: null,
    dashboard: null,
    lesson: null,
    practice: null,
    outcomes: new Map(),
    matching: { selected: null, mistakes: new Set(), matched: new Set() },
};

const elements = {
    agent: document.getElementById("englishAgentPanel"),
    lesson: document.getElementById("lessonPanel"),
    practice: document.getElementById("practicePanel"),
    dayLabel: document.getElementById("dayLabel"),
    prev: document.getElementById("prevDay"),
    next: document.getElementById("nextDay"),
    profileForm: document.getElementById("englishProfileForm"),
};

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = String(value ?? "");
    return div.innerHTML;
}

async function fetchJson(url, options, context) {
    const response = await fetch(url, options);
    const data = await readApiJson(response, context);
    if (!response.ok) throw new Error(data.error || `${context}失败`);
    return data;
}

async function loadDashboard() {
    try {
        state.dashboard = await fetchJson("/api/english/dashboard", undefined, "学习计划");
        renderDashboard();
    } catch (error) {
        elements.agent.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
    }
}

function renderDashboard() {
    const { plan = {}, stats = {}, weaknesses = [] } = state.dashboard || {};
    const accuracy = stats.recent_accuracy == null
        ? "待积累"
        : `${Math.round(stats.recent_accuracy * 100)}%`;
    const weaknessText = weaknesses.length
        ? weaknesses.map(item => `${escapeHtml(item.label)} ${item.count} 次`).join(" · ")
        : "暂无错因数据";
    elements.agent.innerHTML = `
        <div class="agent-heading">
            <div>
                <div class="kicker">TODAY'S PLAN · ${escapeHtml(plan.level || "B1")}</div>
                <h2>${escapeHtml(plan.theme || "日常交流")}</h2>
                <p>${escapeHtml(plan.reason || "正在建立学习基线。")}</p>
            </div>
            <button class="button ghost" id="editProfile" type="button">调整目标</button>
        </div>
        <div class="plan-grid">
            <div><strong>${plan.new_expression_count ?? 0}</strong><span>新表达</span></div>
            <div><strong>${plan.review_expression_count ?? 0}</strong><span>计划复习</span></div>
            <div><strong>${stats.due_count ?? 0}</strong><span>当前到期</span></div>
            <div><strong>${accuracy}</strong><span>近期正确率</span></div>
        </div>
        <div class="diagnosis">
            <span>训练重点：${escapeHtml(plan.exercise_focus || "场景运用")}</span>
            <span>薄弱记录：${weaknessText}</span>
            <span>已掌握 ${stats.mastered_count ?? 0} / ${stats.learned_count ?? 0}</span>
        </div>`;
    document.getElementById("editProfile").addEventListener("click", openProfile);
}

function openProfile() {
    const profile = state.dashboard?.profile || {};
    document.getElementById("englishGoals").value = (profile.goals || []).join(", ");
    document.getElementById("englishLevel").value = profile.level || "B1";
    document.getElementById("englishDailyMinutes").value = profile.daily_minutes || 15;
    document.getElementById("englishInterests").value = (profile.interests || []).join(", ");
    elements.profileForm.hidden = false;
    document.getElementById("englishGoals").focus();
}

async function loadHistory(preferredDay = null) {
    const data = await fetchJson("/api/english/history", undefined, "学习历史");
    state.days = data.days || [];
    if (!state.days.length) {
        state.currentDay = null;
        elements.dayLabel.textContent = "Day --";
        elements.prev.disabled = true;
        elements.next.disabled = true;
        elements.lesson.innerHTML = `
            <div class="empty-state">
                <strong>还没有学习内容</strong>
                <span>生成第一天内容后，Agent 会开始积累长期学习状态。</span>
                <div><button class="button primary" id="generateLesson" type="button">生成今日内容</button></div>
            </div>`;
        document.getElementById("generateLesson").addEventListener("click", generateToday);
        return;
    }
    const exists = state.days.some(item => item.day === preferredDay);
    state.currentDay = exists ? preferredDay : state.days.at(-1).day;
    await loadDay(state.currentDay);
}

async function generateToday() {
    elements.lesson.innerHTML = '<div class="loading">正在调用模型生成今日表达…</div>';
    try {
        const lesson = await fetchJson("/api/english/today", undefined, "今日内容");
        await loadHistory(lesson.day);
        await loadDashboard();
    } catch (error) {
        elements.lesson.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
    }
}

async function loadDay(day) {
    try {
        state.lesson = await fetchJson(`/api/english/day/${day}`, undefined, `Day ${day}`);
        state.currentDay = day;
        state.practice = null;
        renderLesson();
        updateDaySwitcher();
        if (!elements.practice.hidden) await loadPractice();
    } catch (error) {
        elements.lesson.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
    }
}

function updateDaySwitcher() {
    const index = state.days.findIndex(item => item.day === state.currentDay);
    elements.dayLabel.textContent = `Day ${state.currentDay} / ${state.days.length}`;
    elements.prev.disabled = index <= 0;
    elements.next.disabled = index < 0 || index >= state.days.length - 1;
}

function renderLesson() {
    const lesson = state.lesson;
    let html = `
        <div class="day-header">
            <span class="badge">Day ${lesson.day}</span>
            <span class="count">共 ${(lesson.expressions || []).length} 个表达</span>
        </div>`;
    (lesson.expressions || []).forEach((item, index) => {
        html += `
            <article class="expression">
                <span class="number">${index + 1}</span>
                <div>
                    <h3>${escapeHtml(item.expression)}</h3>
                    <div class="expression-meta">
                        <span class="meaning">${escapeHtml(item.meaning)}</span>
                        <span>场景：${escapeHtml(item.scene)}</span>
                    </div>
                    <div class="example">
                        <p>${escapeHtml(item.example)}</p>
                        <p class="cn">${escapeHtml(item.example_cn)}</p>
                    </div>
                </div>
            </article>`;
    });
    if (lesson.review_note) {
        html += `<div class="review"><strong>复习提醒：</strong>${escapeHtml(lesson.review_note)}</div>`;
    }
    elements.lesson.innerHTML = html;
}

async function loadPractice() {
    if (!state.currentDay) {
        elements.practice.innerHTML = '<div class="empty-state"><strong>请先生成今日内容</strong></div>';
        return;
    }
    elements.practice.innerHTML = '<div class="loading">Agent 正在生成练习…</div>';
    try {
        state.practice = await fetchJson(
            `/api/english/practice/${state.currentDay}`,
            undefined,
            "互动练习",
        );
        state.outcomes = new Map();
        state.matching = { selected: null, mistakes: new Set(), matched: new Set() };
        renderPractice();
    } catch (error) {
        elements.practice.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
    }
}

function renderPractice() {
    const exercises = state.practice?.exercises || [];
    let html = `
        <div class="practice-header">
            <span class="badge">Day ${state.currentDay} 练习</span>
            <span class="score" id="score">已完成 0 / ${exercises.length}</span>
        </div>`;
    exercises.forEach((exercise, index) => {
        const label = {
            multiple_choice: "选择题",
            scenario_choice: "场景应用",
            fill_blank: "填空题",
            matching: "连线题",
        }[exercise.type] || exercise.type;
        html += `
            <article class="exercise" data-exercise-id="${exercise.id}">
                <div class="exercise-head"><span class="number">${index + 1}</span><span class="type">${label}</span></div>
                <div class="question">${escapeHtml(exercise.question || exercise.title || "")}</div>
                ${renderExerciseBody(exercise)}
                <div class="explanation" id="explanation-${exercise.id}" hidden></div>
            </article>`;
    });
    html += '<div id="practiceResult"></div>';
    elements.practice.innerHTML = html;
}

function renderExerciseBody(exercise) {
    if (exercise.type === "multiple_choice" || exercise.type === "scenario_choice") {
        return `<div class="options">${(exercise.options || []).map((option, index) => `
            <button class="option" type="button" data-action="choice" data-id="${exercise.id}" data-index="${index}">
                ${String.fromCharCode(65 + index)}. ${escapeHtml(option)}
            </button>`).join("")}</div>`;
    }
    if (exercise.type === "fill_blank") {
        return `<div class="fill-row">
            <input id="fill-${exercise.id}" type="text" autocomplete="off" placeholder="${escapeHtml(exercise.hint || "输入英文表达")}">
            <button type="button" data-action="fill" data-id="${exercise.id}">确认</button>
        </div>`;
    }
    if (exercise.type === "matching") {
        const right = [...(exercise.pairs || [])]
            .map((pair, index) => ({ ...pair, index }))
            .sort(() => Math.random() - 0.5);
        return `<div class="matching">
            <div class="match-column"><span class="match-title">英文表达</span>${(exercise.pairs || []).map((pair, index) => `
                <button class="match-item" type="button" data-action="left" data-id="${exercise.id}" data-index="${index}">
                    ${escapeHtml(pair.left)}
                </button>`).join("")}</div>
            <div class="match-column"><span class="match-title">中文含义</span>${right.map(item => `
                <button class="match-item" type="button" data-action="right" data-id="${exercise.id}" data-index="${item.index}">
                    ${escapeHtml(item.right)}
                </button>`).join("")}</div>
        </div>`;
    }
    return '<div class="error">暂不支持该题型</div>';
}

function getExercise(id) {
    return (state.practice?.exercises || []).find(item => String(item.id) === String(id));
}

function answerChoice(button) {
    const exercise = getExercise(button.dataset.id);
    if (!exercise || state.outcomes.has(exercise.id)) return;
    const selected = Number(button.dataset.index);
    const container = button.closest(".exercise");
    container.querySelectorAll(".option").forEach((item, index) => {
        item.disabled = true;
        if (index === Number(exercise.answer)) item.classList.add("correct");
        if (index === selected && index !== Number(exercise.answer)) item.classList.add("wrong");
    });
    finishExercise(exercise, selected === Number(exercise.answer), exercise.explanation);
}

function normalizeAnswer(value) {
    return String(value || "").trim().toLowerCase()
        .replace(/^[.!?,;:'"“”‘’]+|[.!?,;:'"“”‘’]+$/g, "")
        .replace(/\s+/g, " ");
}

function answerFill(button) {
    const exercise = getExercise(button.dataset.id);
    if (!exercise || state.outcomes.has(exercise.id)) return;
    const input = document.getElementById(`fill-${exercise.id}`);
    if (!normalizeAnswer(input.value)) return;
    input.disabled = true;
    button.disabled = true;
    const correct = normalizeAnswer(input.value) === normalizeAnswer(exercise.answer);
    finishExercise(
        exercise,
        correct,
        `正确答案：${exercise.answer}${correct ? "" : `；你的答案：${input.value}`}`,
    );
}

function selectMatch(button) {
    const exercise = getExercise(button.dataset.id);
    if (!exercise || state.outcomes.has(exercise.id)) return;
    const index = Number(button.dataset.index);
    const side = button.dataset.action;
    if (side === "left") {
        if (state.matching.matched.has(`${exercise.id}-${index}`)) return;
        button.closest(".matching").querySelectorAll('[data-action="left"]').forEach(item => item.classList.remove("selected"));
        button.classList.add("selected");
        state.matching.selected = { exerciseId: exercise.id, index, element: button };
        return;
    }
    const selected = state.matching.selected;
    if (!selected || String(selected.exerciseId) !== String(exercise.id)) return;
    if (selected.index === index) {
        selected.element.classList.remove("selected");
        selected.element.classList.add("done");
        button.classList.add("done");
        selected.element.disabled = true;
        button.disabled = true;
        state.matching.matched.add(`${exercise.id}-${index}`);
        const done = [...state.matching.matched].filter(key => key.startsWith(`${exercise.id}-`)).length;
        if (done === (exercise.pairs || []).length) {
            const hadMistake = [...state.matching.mistakes].some(key => key.startsWith(`${exercise.id}-`));
            finishExercise(exercise, !hadMistake, hadMistake ? "已完成配对，本轮存在错配。" : "全部配对正确。");
        }
    } else {
        const key = `${exercise.id}-${selected.index}`;
        state.matching.mistakes.add(key);
        selected.element.classList.add("mistake");
        button.classList.add("mistake");
        setTimeout(() => {
            selected.element.classList.remove("mistake", "selected");
            button.classList.remove("mistake");
        }, 450);
    }
    state.matching.selected = null;
}

function finishExercise(exercise, correct, explanationText) {
    state.outcomes.set(exercise.id, correct);
    const explanation = document.getElementById(`explanation-${exercise.id}`);
    explanation.textContent = explanationText || (correct ? "回答正确。" : "回答错误。");
    explanation.hidden = false;
    document.getElementById("score").textContent =
        `已完成 ${state.outcomes.size} / ${(state.practice?.exercises || []).length}`;
    if (state.outcomes.size === (state.practice?.exercises || []).length) {
        renderResult();
        submitAttempts();
    }
}

function renderResult() {
    const total = state.outcomes.size;
    const correct = [...state.outcomes.values()].filter(Boolean).length;
    const percent = total ? Math.round(correct / total * 100) : 0;
    document.getElementById("practiceResult").innerHTML = `
        <div class="result">
            <h3>${percent >= 80 ? "掌握得不错" : "继续巩固薄弱表达"}</h3>
            <div>${correct} / ${total}（${percent}%）</div>
            <div id="syncStatus" class="sync">正在更新长期记忆与下一次计划…</div>
        </div>`;
}

function findMeaning(expression) {
    const items = [
        ...(state.lesson?.expressions || []),
        ...(state.practice?.review_expressions || []),
    ];
    return items.find(item => normalizeAnswer(item.expression) === normalizeAnswer(expression))?.meaning || "";
}

function collectAttempts() {
    const attempts = [];
    (state.practice?.exercises || []).forEach(exercise => {
        if (exercise.type === "matching") {
            (exercise.pairs || []).forEach((pair, index) => {
                attempts.push({
                    expression: pair.left,
                    meaning: pair.right,
                    correct: !state.matching.mistakes.has(`${exercise.id}-${index}`),
                    exercise_type: "matching",
                    error_type: "matching",
                });
            });
        } else if (exercise.expression) {
            attempts.push({
                expression: exercise.expression,
                meaning: findMeaning(exercise.expression),
                correct: Boolean(state.outcomes.get(exercise.id)),
                exercise_type: exercise.type,
            });
        }
    });
    return attempts;
}

async function submitAttempts() {
    const status = document.getElementById("syncStatus");
    const attempts = collectAttempts();
    if (!attempts.length) {
        status.textContent = "本轮没有可记录的表达。";
        return;
    }
    try {
        const data = await fetchJson("/api/english/attempts", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ day: state.currentDay, attempts }),
        }, "练习记录");
        state.dashboard = data.dashboard;
        renderDashboard();
        status.textContent = `已记录 ${data.session.attempt_count} 个表达，Agent 已重新规划。`;
    } catch (error) {
        status.textContent = `记录失败：${error.message}`;
    }
}

document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", async () => {
        document.querySelectorAll(".tab").forEach(item => item.classList.toggle("active", item === tab));
        const practice = tab.dataset.tab === "practice";
        elements.lesson.hidden = practice;
        elements.practice.hidden = !practice;
        if (practice && !state.practice) await loadPractice();
    });
});

elements.prev.addEventListener("click", () => {
    const index = state.days.findIndex(item => item.day === state.currentDay);
    if (index > 0) loadDay(state.days[index - 1].day);
});

elements.next.addEventListener("click", () => {
    const index = state.days.findIndex(item => item.day === state.currentDay);
    if (index >= 0 && index < state.days.length - 1) loadDay(state.days[index + 1].day);
});

document.getElementById("englishProfileCancel").addEventListener("click", () => {
    elements.profileForm.hidden = true;
});

elements.profileForm.addEventListener("submit", async event => {
    event.preventDefault();
    const split = value => value.split(/[,，]/).map(item => item.trim()).filter(Boolean);
    try {
        await fetchJson("/api/english/profile", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                goals: split(document.getElementById("englishGoals").value),
                level: document.getElementById("englishLevel").value,
                daily_minutes: Number(document.getElementById("englishDailyMinutes").value),
                interests: split(document.getElementById("englishInterests").value),
            }),
        }, "学习画像");
        elements.profileForm.hidden = true;
        await loadDashboard();
    } catch (error) {
        window.alert(error.message);
    }
});

elements.practice.addEventListener("click", event => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    if (button.dataset.action === "choice") answerChoice(button);
    if (button.dataset.action === "fill") answerFill(button);
    if (button.dataset.action === "left" || button.dataset.action === "right") selectMatch(button);
});

Promise.all([loadDashboard(), loadHistory()]).catch(error => {
    elements.lesson.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
});
