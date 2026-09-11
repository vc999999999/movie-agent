let currentProjectId = null;
let selectedAnswers = {};
let currentBrief = null;

async function apiJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.message || `请求失败 (${response.status})`);
  }
  return data;
}

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = String(value ?? "");
  return node.innerHTML;
}

function switchStep(step) {
  for (let i = 1; i <= 4; i++) {
    const sec = document.getElementById(`step-${i}`);
    const btn = document.getElementById(`step-btn-${i}`);
    if (sec) sec.classList.toggle("active", i === step);
    if (btn) {
      btn.classList.toggle("active", i === step);
      if (i < step) btn.classList.add("completed");
    }
  }
}

async function handleStartProject() {
  const text = document.getElementById("idea-input").value.trim();
  if (!text) {
    alert("请输入电影创意或故事梗概！");
    return;
  }

  const btn = document.getElementById("btn-start-project");
  btn.disabled = true;
  btn.innerText = "⏳ 正在分析要素与规划...";

  try {
    const data = await apiJson("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_text: text })
    });
    currentProjectId = data.project.id;
    document.getElementById("current-project-badge").innerText = `项目: ${currentProjectId}`;

    // Add user message to chat
    appendChatMessage("user", text);

    // Update sidebar
    updateSidebar(data.questions_response);

    // If ready to review, jump to step 2
    if (data.questions_response.status === "brief_review") {
      currentBrief = data.project.brief;
      populateBrief(currentBrief);
      switchStep(2);
    } else {
      document.getElementById("chat-card").style.display = "block";
      renderQuestions(data.questions_response.questions);
    }
  } catch (err) {
    alert("创建项目失败: " + err.message);
  } finally {
    btn.disabled = false;
    btn.innerText = "🚀 开始分析并创建";
  }
}

function appendChatMessage(role, content) {
  const box = document.getElementById("chat-box");
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${role}`;
  bubble.innerText = content;
  box.appendChild(bubble);
  box.scrollTop = box.scrollHeight;
}

function updateSidebar(qResp) {
  const pct = Math.round((qResp.brief_completion || 0) * 100);
  document.getElementById("completion-text").innerText = `${pct}%`;
  document.getElementById("completion-bar").style.width = `${pct}%`;

  // Assumptions
  const assumpContainer = document.getElementById("assumptions-list");
  assumpContainer.innerHTML = "";
  if (qResp.assumptions && qResp.assumptions.length > 0) {
    qResp.assumptions.forEach(a => {
      const item = document.createElement("div");
      item.className = "assumption-item";
      item.innerText = a;
      assumpContainer.appendChild(item);
    });
  } else {
    assumpContainer.innerHTML = `<div class="assumption-item">暂无默认假设</div>`;
  }
}

function renderQuestions(questions) {
  const container = document.getElementById("questions-container");
  container.innerHTML = "";
  selectedAnswers = {};

  if (!questions || questions.length === 0) {
    container.innerHTML = `<p style="color: var(--text-muted); font-size: 0.85rem;">要素已基本完备，准备进入简报确认。</p>`;
    document.getElementById("btn-submit-answers").style.display = "none";
    return;
  }

  questions.forEach(q => {
    const card = document.createElement("div");
    card.className = "question-card";

    const title = document.createElement("div");
    title.style.fontSize = "0.92rem";
    title.style.fontWeight = "600";
    title.style.color = "#f1f5f9";
    title.innerText = `❓ [${q.field}] ${q.text}`;
    card.appendChild(title);

    const choicesDiv = document.createElement("div");
    choicesDiv.className = "question-choices";

    q.choices.forEach(c => {
      const chip = document.createElement("button");
      chip.className = "choice-chip";
      chip.type = "button";
      chip.innerText = c;
      chip.onclick = () => {
        // Toggle selected in this group
        Array.from(choicesDiv.children).forEach(ch => ch.classList.remove("selected"));
        chip.classList.add("selected");
        selectedAnswers[q.field] = c;
      };
      choicesDiv.appendChild(chip);
    });

    card.appendChild(choicesDiv);
    container.appendChild(card);
  });

  document.getElementById("btn-submit-answers").style.display = "inline-flex";
}

async function handleSubmitAnswers() {
  if (!currentProjectId) return;

  const answersArray = Object.keys(selectedAnswers).map(k => ({
    field: k,
    answer: selectedAnswers[k]
  }));

  if (answersArray.length === 0) {
    alert("请至少选择一个问题的选项！");
    return;
  }

  const btn = document.getElementById("btn-submit-answers");
  btn.disabled = true;
  btn.innerText = "⏳ 提交并再推断...";

  try {
    const data = await apiJson(`/api/projects/${encodeURIComponent(currentProjectId)}/answers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answers: answersArray })
    });

    // Append to chat
    appendChatMessage("user", answersArray.map(a => `${a.field}: ${a.answer}`).join(" | "));

    updateSidebar(data);

    if (data.status === "brief_review" || data.can_confirm) {
      // Fetch latest brief
      const pData = await apiJson(`/api/projects/${encodeURIComponent(currentProjectId)}`);
      currentBrief = pData.project.brief;
      populateBrief(currentBrief);
      switchStep(2);
    } else {
      renderQuestions(data.questions);
    }
  } catch (err) {
    alert("提交回答失败: " + err.message);
  } finally {
    btn.disabled = false;
    btn.innerText = "提交回答并下一步";
  }
}

async function handleSkipQuestions() {
  if (!currentProjectId) return;
  const pData = await apiJson(`/api/projects/${encodeURIComponent(currentProjectId)}`);
  currentBrief = pData.project.brief;
  populateBrief(currentBrief);
  switchStep(2);
}

function populateBrief(brief) {
  if (!brief) return;
  document.getElementById("brief-title").value = brief.title || "雨夜追缉";
  document.getElementById("brief-duration").value = brief.duration_seconds || 45;
  document.getElementById("brief-aspect").value = brief.aspect_ratio || "16:9";
  document.getElementById("brief-dialogue").value = brief.dialogue_mode || "voiceover";
  document.getElementById("brief-logline").value = brief.logline || "";
  document.getElementById("brief-style").value = brief.visual_style || "写实电影感，雨夜冷色调，35mm胶片质感";
  document.getElementById("brief-protagonist").value = brief.protagonist || "侦探";
  document.getElementById("brief-goal").value = brief.protagonist_goal || "追缉暴风雨夜致命凶手";
  document.getElementById("brief-conflict").value = brief.conflict || "凶手在暗处设伏并试图灭口";
  document.getElementById("brief-ending").value = brief.ending || "预告片式悬念";
}

async function handleConfirmBrief() {
  if (!currentProjectId) return;

  const briefUpdates = {
    title: document.getElementById("brief-title").value,
    duration_seconds: parseInt(document.getElementById("brief-duration").value),
    aspect_ratio: document.getElementById("brief-aspect").value,
    dialogue_mode: document.getElementById("brief-dialogue").value,
    logline: document.getElementById("brief-logline").value,
    visual_style: document.getElementById("brief-style").value,
    protagonist: document.getElementById("brief-protagonist").value,
    protagonist_goal: document.getElementById("brief-goal").value,
    conflict: document.getElementById("brief-conflict").value,
    ending: document.getElementById("brief-ending").value,
  };

  try {
    await apiJson(`/api/projects/${encodeURIComponent(currentProjectId)}/brief/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(briefUpdates)
    });
    alert("✅ 创作简报已确认！已为您生成剧本设定与分镜镜头表。");
    await loadScreenplayAndShots(currentProjectId);
    switchStep(3);
  } catch (err) {
    alert("确认简报失败: " + err.message);
  }
}

async function loadScreenplayAndShots(projectId) {
  // Load Screenplay
  const encodedProjectId = encodeURIComponent(projectId);
  const spData = await apiJson(`/api/projects/${encodedProjectId}/screenplay`);
  renderProjectBible(spData.project_bible);
  renderScenes(spData.scenes);

  // Load Shots
  const shData = await apiJson(`/api/projects/${encodedProjectId}/shots`);
  renderShots(shData.shots);
  renderContinuityAlerts(shData.continuity_issues);

  document.getElementById("target-dur-badge").innerText = `${spData.project_bible.target_duration}s`;
  document.getElementById("current-dur-badge").innerText = `${shData.total_duration.toFixed(1)}s`;
}

function renderProjectBible(bible) {
  const charBox = document.getElementById("bible-characters-box");
  charBox.innerHTML = "<strong>角色设定:</strong>";
  bible.characters.forEach(c => {
    const p = document.createElement("div");
    p.style.fontSize = "0.85rem";
    p.style.marginTop = "0.4rem";
    p.innerHTML = `<span style="color: #60a5fa;">${escapeHtml(c.name)}</span>: ${escapeHtml(c.fixed_appearance)}<br><span style="color: var(--text-muted); font-size: 0.8rem;">固定着装: ${escapeHtml(c.fixed_costume)}</span>`;
    charBox.appendChild(p);
  });

  const locBox = document.getElementById("bible-locations-box");
  locBox.innerHTML = "<strong>场景设定:</strong>";
  bible.locations.forEach(l => {
    const p = document.createElement("div");
    p.style.fontSize = "0.85rem";
    p.style.marginTop = "0.4rem";
    p.innerHTML = `<span style="color: #60a5fa;">${escapeHtml(l.name)}</span> (${escapeHtml(l.time_of_day)})<br><span style="color: var(--text-muted); font-size: 0.8rem;">${escapeHtml(l.fixed_visual_description)}</span>`;
    locBox.appendChild(p);
  });
}

function renderScenes(scenes) {
  const box = document.getElementById("scenes-list-box");
  box.innerHTML = "";
  scenes.forEach(s => {
    const div = document.createElement("div");
    div.style.background = "var(--bg-input)";
    div.style.padding = "0.65rem";
    div.style.borderRadius = "6px";
    div.style.marginBottom = "0.5rem";
    div.style.fontSize = "0.85rem";
    div.innerHTML = `<strong>${escapeHtml(s.heading)}</strong><p style="color: var(--text-muted); font-size: 0.8rem; margin-top: 0.2rem;">${escapeHtml(s.setup)}</p>`;
    box.appendChild(div);
  });
}

function renderShots(shots) {
  const container = document.getElementById("shots-container");
  container.innerHTML = "";

  shots.forEach(s => {
    const card = document.createElement("div");
    card.className = "shot-card";

    card.innerHTML = `
      <div class="shot-header">
        <div style="display: flex; align-items: center; gap: 0.5rem;">
          <span class="shot-id-badge">${escapeHtml(s.shot_id)}</span>
          <span class="tag tag-accent">${escapeHtml(s.duration_seconds)} 秒</span>
          <span class="tag">${escapeHtml(s.shot_size)}</span>
          <span class="tag">${escapeHtml(s.camera_movement)}</span>
        </div>
        <span class="tag" style="background: rgba(16, 185, 129, 0.2); color: #34d399;">${escapeHtml(s.generation_mode)}</span>
      </div>
      <div style="font-size: 0.9rem; line-height: 1.5;">
        <div><strong style="color: #94a3b8;">起幅 (Start):</strong> ${escapeHtml(s.start_frame)}</div>
        <div style="margin-top: 0.3rem;"><strong style="color: #38bdf8;">核心动作 (Action):</strong> ${escapeHtml(s.action)}</div>
        <div style="margin-top: 0.3rem;"><strong style="color: #94a3b8;">落幅 (End):</strong> ${escapeHtml(s.end_frame)}</div>
      </div>
      <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.8rem; color: var(--text-muted); border-top: 1px solid var(--border-color); padding-top: 0.5rem;">
        <span>光影: ${escapeHtml(s.lighting)} | 情绪: ${escapeHtml(s.mood)}</span>
        <span>镜头设计: ${escapeHtml(s.lens || "35mm Prime")}</span>
      </div>
    `;
    container.appendChild(card);
  });
}

function renderContinuityAlerts(issues) {
  const box = document.getElementById("continuity-alert-box");
  if (!issues || issues.length === 0) {
    box.style.display = "none";
    return;
  }
  box.style.display = "block";
  box.innerHTML = "";
  issues.forEach(iss => {
    const d = document.createElement("div");
    d.className = `status-badge badge-${iss.severity === "error" ? "error" : "warning"}`;
    d.style.display = "block";
    d.style.padding = "0.5rem 1rem";
    d.innerText = `⚠️ 连续性提醒 [镜头 ${iss.shot_ids.join(",")}] ${iss.explanation} (建议: ${iss.suggested_fix})`;
    box.appendChild(d);
  });
}

async function handleConfirmShots() {
  if (!currentProjectId) return;

  try {
    await apiJson(`/api/projects/${encodeURIComponent(currentProjectId)}/shots/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" }
    });
    alert("✅ 镜头表已确认！正在编译 PromptPackage 与 PatchMap 注入工作流...");
    await loadPackages(currentProjectId);
    switchStep(4);
  } catch (err) {
    alert("确认镜头失败: " + err.message);
  }
}

async function loadPackages(projectId) {
  const encodedProjectId = encodeURIComponent(projectId);
  const data = await apiJson(`/api/projects/${encodedProjectId}/packages`);

  const container = document.getElementById("packages-container");
  container.innerHTML = "";

  const plans = data.workflow_plans || [];
  const pkgs = data.prompt_packages || [];

  pkgs.forEach((p, idx) => {
    const plan = plans[idx] || {};
    const card = document.createElement("div");
    card.className = "package-card";

    const isMatched = plan.status === "matched";
    const previewId = `preview-box-${idx}`;

    card.innerHTML = `
      <div class="package-info">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <strong style="color: #38bdf8; font-size: 1.1rem;">${escapeHtml(p.shot_id)}</strong>
            <span class="status-badge ${isMatched ? "badge-success" : "badge-error"}">
              ${isMatched ? `适配工作流: ${escapeHtml(plan.workflow_id)}` : `未适配: ${escapeHtml(plan.reason)}`}
            </span>
          </div>
          <a href="/api/projects/${encodedProjectId}/workflow/${encodeURIComponent(p.shot_id)}" download class="btn btn-sm" ${!isMatched ? "disabled" : ""}>
            💾 下载 Patched Workflow JSON
          </a>
        </div>
        <div style="margin-top: 0.5rem;">
          <label style="font-size: 0.75rem; color: var(--text-muted);">正向提示词 (Positive Prompt - 分层编译):</label>
          <div class="prompt-display">${escapeHtml(p.positive_prompt)}</div>
        </div>
        <div style="margin-top: 0.3rem;">
          <label style="font-size: 0.75rem; color: var(--text-muted);">负向提示词 (Negative Prompt - 去重合并):</label>
          <div class="prompt-display" style="max-height: 40px;">${escapeHtml(p.negative_prompt)}</div>
        </div>
        <div style="display: flex; gap: 1rem; font-size: 0.8rem; color: var(--text-muted); margin-top: 0.5rem;">
          <span>尺寸: <strong>${escapeHtml(p.width)}x${escapeHtml(p.height)}</strong></span>
          <span>帧数: <strong>${escapeHtml(p.frame_count)}帧</strong></span>
          <span>FPS: <strong>${escapeHtml(p.fps)}</strong></span>
          <span>Seed: <strong>${escapeHtml(p.seed)}</strong></span>
        </div>
      </div>
      <div class="package-preview">
        <div id="${previewId}" style="width: 100%; text-align: center;">
          <span style="font-size: 0.8rem; color: var(--text-muted);">未生成</span>
        </div>
        <button class="btn btn-primary btn-sm render-shot" style="margin-top: 0.75rem; width: 100%;">
          ⚡ 渲染镜头
        </button>
      </div>
    `;
    card.querySelector(".render-shot").addEventListener("click", () => handleRenderSingleShot(p.shot_id, previewId));
    container.appendChild(card);
  });
}

async function handleRenderSingleShot(shotId, previewId) {
  if (!currentProjectId) return;
  const box = document.getElementById(previewId);
  box.textContent = "⏳ 正在渲染中...";

  try {
    const run = await apiJson(`/api/shots/${encodeURIComponent(shotId)}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: currentProjectId })
    });
    if (run.status === "success") {
      box.replaceChildren();
      const video = document.createElement("video");
      video.className = "video-player";
      video.src = `/api/projects/${encodeURIComponent(currentProjectId)}/outputs/${encodeURIComponent(shotId)}.mp4`;
      video.controls = true;
      video.autoplay = true;
      video.loop = true;
      video.muted = true;
      const status = document.createElement("div");
      status.style.cssText = "font-size: 0.75rem; color: #34d399; margin-top: 0.2rem;";
      status.textContent = "✅ 渲染成功";
      box.append(video, status);
    } else {
      box.textContent = `❌ 渲染失败: ${run.error_json?.message || "未知错误"}`;
    }
  } catch (err) {
    box.textContent = `❌ 请求失败: ${err.message}`;
  }
}

async function handleBatchRender() {
  if (!currentProjectId) return;
  if (!confirm("确定开始批量渲染所有镜头吗？")) return;

  try {
    alert("🚀 批量渲染任务已启动！");
    await apiJson(`/api/projects/${encodeURIComponent(currentProjectId)}/render_all`, {
      method: "POST"
    });
    alert("✅ 批量渲染已执行完毕！");
    await loadPackages(currentProjectId);
  } catch (err) {
    alert("批量渲染发生错误: " + err.message);
  }
}

async function handleRoughCut() {
  if (!currentProjectId) return;

  try {
    await apiJson(`/api/projects/${encodeURIComponent(currentProjectId)}/rough_cut`, {
      method: "POST"
    });
    alert("🎉 粗剪短片合成完毕！");

    const card = document.getElementById("rough-cut-card");
    card.style.display = "block";
    const player = document.getElementById("rough-cut-player");
    player.src = `/api/projects/${encodeURIComponent(currentProjectId)}/outputs/rough_cut.mp4?t=${Date.now()}`;
    player.load();
    document.getElementById("rough-cut-download-btn").href = `/api/projects/${encodeURIComponent(currentProjectId)}/rough_cut/download`;
  } catch (err) {
    alert("粗剪合成失败: " + err.message);
  }
}

async function openProductionReportModal() {
  if (!currentProjectId) return;
  const data = await apiJson(`/api/projects/${encodeURIComponent(currentProjectId)}/packages`);
  document.getElementById("report-markdown-body").innerText = data.production_report || "暂无报告";
  document.getElementById("report-modal").classList.add("active");
}

function closeProductionReportModal() {
  document.getElementById("report-modal").classList.remove("active");
}
