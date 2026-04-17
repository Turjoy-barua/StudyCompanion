(function () {
  const timerDisplay = document.getElementById("timerDisplay");
  const timerPhase = document.getElementById("timerPhase");
  const timerHint = document.getElementById("timerHint");
  const timerStatus = document.getElementById("timerStatus");
  const focusTargetSelect = document.getElementById("focusTargetSelect");
  const timerSubject = document.getElementById("timerSubject");
  const timerMode = document.getElementById("timerMode");
  const startButton = document.getElementById("startTimer");
  const pauseButton = document.getElementById("pauseTimer");
  const resetButton = document.getElementById("resetTimer");
  const saveButton = document.getElementById("saveTimerSession");
  const focusToggle = document.getElementById("focusToggle");
  const focusOverlay = document.getElementById("focusOverlay");
  const focusDisplay = document.getElementById("focusDisplay");
  const focusPhase = document.getElementById("focusPhase");
  const focusThemeLabel = document.getElementById("focusThemeLabel");
  const focusThemeOptions = document.getElementById("focusThemeOptions");
  const closeFocus = document.getElementById("closeFocus");
  const accountToggle = document.getElementById("accountToggle");
  const accountModal = document.getElementById("accountModal");
  const closeAccount = document.getElementById("closeAccount");
  const weeklyChart = document.getElementById("weeklyChart");
  const appThemeOptions = document.getElementById("appThemeOptions");
  const navItems = Array.from(document.querySelectorAll(".sidebar-nav-item"));
  const appViews = Array.from(document.querySelectorAll(".app-view"));
  const accountOpenButtons = Array.from(document.querySelectorAll("[data-open-account='true']"));
  const confidenceSliders = Array.from(document.querySelectorAll("[data-confidence-slider]"));
  const today = document.querySelector(".timer-shell")?.dataset.today;

  const pomodoroFocusSeconds = 25 * 60;
  const pomodoroBreakSeconds = 5 * 60;
  const appThemes = [
    { id: "ivory", label: "Ivory", description: "Soft white study board" },
    { id: "rose", label: "Rose", description: "Warm pastel workspace" },
    { id: "slate", label: "Slate", description: "Cool clean planner" },
  ];
  const focusThemes = [
    { id: "midnight-orbit", label: "Midnight Orbit" },
    { id: "aurora-drift", label: "Aurora Drift" },
    { id: "sunset-grid", label: "Sunset Grid" },
    { id: "forest-bloom", label: "Forest Bloom" },
    { id: "ember-night", label: "Ember Night" },
    { id: "ocean-depth", label: "Ocean Depth" },
    { id: "violet-mist", label: "Violet Mist" },
    { id: "mono-zen", label: "Mono Zen" },
    { id: "golden-hour", label: "Golden Hour" },
    { id: "cosmic-wave", label: "Cosmic Wave" },
  ];
  const defaultFocusTheme = focusThemes[0].id;
  const defaultAppTheme = appThemes[0].id;
  const defaultView = "dashboard";

  let timerId = null;
  let elapsedSeconds = 0;
  let pomodoroSecondsRemaining = pomodoroFocusSeconds;
  let pomodoroPhase = "focus";
  let focusSecondsEarned = 0;
  let activeFocusTheme = defaultFocusTheme;

  function applyAppView(viewId) {
    const targetView = appViews.find((view) => view.dataset.view === viewId) || appViews[0];
    if (!targetView) {
      return;
    }

    for (const view of appViews) {
      view.classList.toggle("is-active", view === targetView);
    }

    for (const item of navItems) {
      const isActive = item.dataset.viewTarget === targetView.dataset.view;
      item.classList.toggle("is-active", isActive);
      item.setAttribute("aria-pressed", String(isActive));
    }

    window.localStorage.setItem("study-companion-active-view", targetView.dataset.view);
  }

  function initializeNavigation() {
    if (!navItems.length || !appViews.length) {
      return;
    }

    for (const item of navItems) {
      item.addEventListener("click", () => applyAppView(item.dataset.viewTarget || defaultView));
    }

    const savedView = window.localStorage.getItem("study-companion-active-view");
    applyAppView(savedView || defaultView);
  }

  function initializeConfidenceSliders() {
    for (const slider of confidenceSliders) {
      const valueNode = slider.parentElement?.querySelector("[data-confidence-value]");
      const renderValue = () => {
        if (valueNode) {
          valueNode.textContent = `${slider.value}%`;
        }
      };
      slider.addEventListener("input", renderValue);
      renderValue();
    }
  }

  function initializeFlashMessages() {
    const flashStack = document.querySelector(".flash-stack");
    if (!flashStack) {
      return;
    }

    window.setTimeout(() => {
      flashStack.classList.add("is-dismissing");
      for (const flash of flashStack.querySelectorAll(".flash")) {
        flash.classList.add("is-dismissing");
      }
      window.setTimeout(() => {
        flashStack.remove();
      }, 220);
    }, 3000);
  }

  function applyAppTheme(themeId) {
    const matchedTheme = appThemes.find((theme) => theme.id === themeId) || appThemes[0];
    document.body.dataset.appTheme = matchedTheme.id;

    if (appThemeOptions) {
      for (const option of appThemeOptions.querySelectorAll(".app-theme-option")) {
        const isActive = option.dataset.theme === matchedTheme.id;
        option.classList.toggle("is-active", isActive);
        option.setAttribute("aria-pressed", String(isActive));
      }
    }

    window.localStorage.setItem("study-companion-app-theme", matchedTheme.id);
  }

  function renderAppThemes() {
    if (!appThemeOptions) {
      return;
    }

    appThemeOptions.innerHTML = appThemes
      .map(
        (theme) => `
          <button
            type="button"
            class="app-theme-option"
            data-theme="${theme.id}"
            aria-pressed="false"
            aria-label="Use ${theme.label} app theme"
          >
            <span class="app-theme-preview" data-theme="${theme.id}"></span>
            <span class="app-theme-copy">
              <strong>${theme.label}</strong>
              <small>${theme.description}</small>
            </span>
          </button>
        `
      )
      .join("");

    appThemeOptions.addEventListener("click", (event) => {
      const option = event.target.closest(".app-theme-option");
      if (!option) {
        return;
      }
      applyAppTheme(option.dataset.theme || defaultAppTheme);
    });

    const savedTheme = window.localStorage.getItem("study-companion-app-theme");
    applyAppTheme(savedTheme || defaultAppTheme);
  }

  function formatSeconds(totalSeconds) {
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return [hours, minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
  }

  function renderTimer() {
    const inPomodoro = timerMode.value === "pomodoro";
    const shownSeconds = inPomodoro ? pomodoroSecondsRemaining : elapsedSeconds;
    const phaseText = inPomodoro
      ? pomodoroPhase === "focus"
        ? "Pomodoro focus block"
        : "Pomodoro break"
      : "Regular session";

    timerDisplay.textContent = formatSeconds(shownSeconds);
    timerPhase.textContent = phaseText;
    timerHint.textContent = inPomodoro
      ? "Focus time adds XP. Break time helps you reset without closing the session."
      : "Use this like a stopwatch and save when the study block ends.";

    if (focusDisplay && focusPhase) {
      focusDisplay.textContent = timerDisplay.textContent;
      focusPhase.textContent = timerPhase.textContent;
    }
  }

  function tick() {
    if (timerMode.value === "pomodoro") {
      pomodoroSecondsRemaining -= 1;
      if (pomodoroPhase === "focus") {
        focusSecondsEarned += 1;
      }

      if (pomodoroSecondsRemaining <= 0) {
        if (pomodoroPhase === "focus") {
          pomodoroPhase = "break";
          pomodoroSecondsRemaining = pomodoroBreakSeconds;
          timerStatus.textContent = "Focus block complete. Break started.";
        } else {
          pomodoroPhase = "focus";
          pomodoroSecondsRemaining = pomodoroFocusSeconds;
          timerStatus.textContent = "Break finished. New focus block started.";
        }
      }
    } else {
      elapsedSeconds += 1;
      focusSecondsEarned += 1;
    }

    renderTimer();
  }

  function startTimer() {
    if (timerId) {
      return;
    }
    timerId = window.setInterval(tick, 1000);
    timerStatus.textContent = "Timer running.";
  }

  function pauseTimer() {
    if (!timerId) {
      return;
    }
    window.clearInterval(timerId);
    timerId = null;
    timerStatus.textContent = "Timer paused.";
  }

  function resetTimer() {
    pauseTimer();
    elapsedSeconds = 0;
    focusSecondsEarned = 0;
    pomodoroPhase = "focus";
    pomodoroSecondsRemaining = pomodoroFocusSeconds;
    timerStatus.textContent = "Timer reset.";
    renderTimer();
  }

  async function saveSession() {
    const subject = timerSubject.value.trim();
    if (!subject) {
      timerStatus.textContent = "Add a subject before saving.";
      return;
    }

    const durationMinutes = Math.max(1, Math.round(focusSecondsEarned / 60));
    if (!focusSecondsEarned) {
      timerStatus.textContent = "Run the timer before saving the session.";
      return;
    }

    saveButton.disabled = true;
    timerStatus.textContent = "Saving session...";

    try {
      const response = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          subject,
          duration_minutes: durationMinutes,
          session_date: today,
        }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "Unable to save session.");
      }

      timerStatus.textContent = payload.message + " Refreshing dashboard...";
      window.setTimeout(() => window.location.reload(), 500);
    } catch (error) {
      timerStatus.textContent = error.message;
    } finally {
      saveButton.disabled = false;
    }
  }

  function toggleFocus(show) {
    if (!focusOverlay) {
      return;
    }
    focusOverlay.hidden = !show;
  }

  function applyFocusTheme(themeId) {
    if (!focusOverlay) {
      return;
    }

    const matchedTheme = focusThemes.find((theme) => theme.id === themeId) || focusThemes[0];
    activeFocusTheme = matchedTheme.id;
    focusOverlay.dataset.theme = matchedTheme.id;

    if (focusThemeLabel) {
      focusThemeLabel.textContent = matchedTheme.label;
    }

    if (focusThemeOptions) {
      for (const option of focusThemeOptions.querySelectorAll(".focus-theme-option")) {
        const isActive = option.dataset.theme === matchedTheme.id;
        option.classList.toggle("is-active", isActive);
        option.setAttribute("aria-pressed", String(isActive));
      }
    }

    window.localStorage.setItem("study-companion-focus-theme", matchedTheme.id);
  }

  function renderFocusThemes() {
    if (!focusThemeOptions) {
      return;
    }

    focusThemeOptions.innerHTML = focusThemes
      .map(
        (theme) => `
          <button
            type="button"
            class="focus-theme-option"
            data-theme="${theme.id}"
            aria-pressed="false"
            aria-label="Use ${theme.label} wallpaper"
          >
            <span class="focus-theme-swatch" data-theme="${theme.id}"></span>
            <span class="focus-theme-name">${theme.label}</span>
          </button>
        `
      )
      .join("");

    focusThemeOptions.addEventListener("click", (event) => {
      const option = event.target.closest(".focus-theme-option");
      if (!option) {
        return;
      }
      applyFocusTheme(option.dataset.theme || defaultFocusTheme);
    });

    const savedTheme = window.localStorage.getItem("study-companion-focus-theme");
    applyFocusTheme(savedTheme || defaultFocusTheme);
  }

  function toggleAccount(show) {
    if (!accountModal) {
      return;
    }
    accountModal.hidden = !show;
  }

  function renderWeeklyChart() {
    if (!weeklyChart) {
      return;
    }

    const data = JSON.parse(weeklyChart.dataset.chart || "[]");
    const maxMinutes = Math.max(...data.map((item) => item.minutes), 1);
    weeklyChart.innerHTML = data
      .map((item) => {
        const height = Math.max((item.minutes / maxMinutes) * 100, item.minutes ? 14 : 6);
        return `
          <article class="chart-day">
            <span class="chart-value">${item.minutes} min</span>
            <div class="chart-bar" style="height:${height}%"></div>
            <span class="chart-label">${item.label}</span>
          </article>
        `;
      })
      .join("");
  }

  startButton?.addEventListener("click", startTimer);
  pauseButton?.addEventListener("click", pauseTimer);
  resetButton?.addEventListener("click", resetTimer);
  saveButton?.addEventListener("click", saveSession);
  focusTargetSelect?.addEventListener("change", () => {
    if (!timerSubject || !focusTargetSelect.value) {
      return;
    }
    timerSubject.value = focusTargetSelect.value;
    timerStatus.textContent = `Focus target selected: ${focusTargetSelect.value}.`;
  });
  timerMode?.addEventListener("change", resetTimer);
  focusToggle?.addEventListener("click", () => toggleFocus(true));
  closeFocus?.addEventListener("click", () => toggleFocus(false));
  accountToggle?.addEventListener("click", () => toggleAccount(true));
  for (const button of accountOpenButtons) {
    button.addEventListener("click", () => toggleAccount(true));
  }
  closeAccount?.addEventListener("click", () => toggleAccount(false));
  focusOverlay?.addEventListener("click", (event) => {
    if (event.target === focusOverlay) {
      toggleFocus(false);
    }
  });
  accountModal?.addEventListener("click", (event) => {
    if (event.target === accountModal) {
      toggleAccount(false);
    }
  });

  initializeNavigation();
  initializeFlashMessages();
  initializeConfidenceSliders();
  renderAppThemes();
  renderFocusThemes();
  renderWeeklyChart();
  renderTimer();
})();
