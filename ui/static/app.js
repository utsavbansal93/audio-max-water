/* Audio Max Water — minimal front-end JS.
 *
 * No build step. No framework. Vanilla DOM + fetch + EventSource.
 * Globally scoped as `AMW` so templates can wire behaviors with one line.
 */
(function () {
  "use strict";

  const AMW = {};

  // --- upload page: drag & drop + file picker ------------------------------

  // Extensions the server accepts. .zip is accepted IFF it contains an
  // EPUB mimetype entry; we let the server sniff and surface its rejection
  // via the inline banner.
  const UPLOAD_OK_EXTS = new Set([".txt", ".md", ".docx", ".epub", ".pdf", ".zip"]);
  const UPLOAD_USER_FACING = [".txt", ".md", ".docx", ".epub", ".pdf"];

  function fileExt(name) {
    const i = name.lastIndexOf(".");
    return i === -1 ? "" : name.substring(i).toLowerCase();
  }

  function initUpload() {
    const form = document.getElementById("upload-form");
    if (!form) return;
    const dropTarget = document.getElementById("drop-target");
    const fileInput = document.getElementById("file-input");
    const browseBtn = document.getElementById("browse-btn");
    const status = document.getElementById("upload-status");
    const errorEl = document.getElementById("upload-error");

    function clearError() {
      if (errorEl) {
        errorEl.hidden = true;
        errorEl.textContent = "";
      }
    }
    function showError(msg) {
      if (errorEl) {
        errorEl.hidden = false;
        errorEl.textContent = msg;
      }
      // Re-enable the picker so the user can try a different file without
      // reloading the page.
      fileInput.disabled = false;
      status.hidden = true;
    }

    browseBtn?.addEventListener("click", () => {
      clearError();
      fileInput.click();
    });

    async function handleUpload() {
      if (!fileInput.files.length) return;
      const f = fileInput.files[0];
      const ext = fileExt(f.name);

      // Client-side extension gate. Keeps the round-trip for genuinely
      // valid-looking files; everything else fails fast with a useful
      // message instead of hitting the server.
      if (!UPLOAD_OK_EXTS.has(ext)) {
        showError(
          `Unsupported format "${ext}". Try one of: ${UPLOAD_USER_FACING.join(", ")}.`
        );
        fileInput.value = "";
        return;
      }

      clearError();
      fileInput.disabled = true;
      status.hidden = false;
      status.textContent = `Uploading ${f.name}…`;

      const fd = new FormData();
      fd.append("file", f);

      let resp;
      try {
        resp = await fetch(form.action, {
          method: "POST",
          body: fd,
          redirect: "follow",
          // Hint to the server that we'll handle failures inline.
          headers: { Accept: "application/json, text/html" },
        });
      } catch (e) {
        showError(`Upload failed: ${e}`);
        return;
      }

      if (resp.ok || resp.redirected) {
        // FastAPI returned a 303 → browser followed it to /parsing/<id>.
        // resp.url is the final URL after redirect.
        window.location.href = resp.url;
        return;
      }

      // Non-OK: try to parse a {detail: "..."} JSON response. If the
      // server returned HTML (e.g. 500 page), show the status text.
      let detail = `Upload rejected (HTTP ${resp.status})`;
      const ctype = resp.headers.get("content-type") || "";
      try {
        if (ctype.includes("application/json")) {
          const body = await resp.json();
          detail = body.detail || JSON.stringify(body);
        } else {
          const text = await resp.text();
          if (text) detail = text.slice(0, 500);
        }
      } catch (_) { /* fallthrough */ }
      showError(detail);
      fileInput.value = "";
    }

    fileInput?.addEventListener("change", handleUpload);

    ["dragover", "dragenter"].forEach((ev) =>
      dropTarget?.addEventListener(ev, (e) => {
        e.preventDefault();
        dropTarget.classList.add("drag-over");
      })
    );
    ["dragleave", "dragend", "drop"].forEach((ev) =>
      dropTarget?.addEventListener(ev, () =>
        dropTarget.classList.remove("drag-over")
      )
    );
    dropTarget?.addEventListener("drop", (e) => {
      e.preventDefault();
      if (!e.dataTransfer?.files?.length) return;
      fileInput.files = e.dataTransfer.files;
      handleUpload();
    });

    // Prevent accidental native submit (e.g. pressing Enter).
    form.addEventListener("submit", (e) => e.preventDefault());
  }

  // --- progress subscription (SSE) -----------------------------------------

  const STAGE_TITLES = {
    ingest:  "Reading the book",
    parse:   "Structuring the script",
    cast:    "Proposing voices",
    render:  "Recording",
    qa:      "Checking the audio",
    package: "Packaging",
  };

  /**
   * @param {string} jobId
   * @param {{
   *   doneRedirect?: string,      // URL to navigate to on terminalStages done
   *   terminalStages?: string[],  // stage names whose "done" completes the page
   *   onError?: (msg: string) => void,
   * }} opts
   */
  AMW.subscribeProgress = function subscribeProgress(jobId, opts = {}) {
    const msgEl = document.getElementById("progress-message");
    const metaEl = document.getElementById("progress-meta");
    const logEl = document.getElementById("log");
    const titleEl = document.getElementById("stage-title");
    const fillEl = document.getElementById("progress-fill");
    const trackerEl = document.getElementById("stage-tracker");

    const terminalStages = new Set(opts.terminalStages || ["package"]);
    const es = new EventSource(`/events/${jobId}`);

    function updateStagePill(stage, status, data) {
      if (!trackerEl) return;
      const pill = trackerEl.querySelector(`[data-stage="${stage}"]`);
      if (!pill) return;
      // Clear old status classes.
      pill.classList.remove(
        "stage-pill--pending",
        "stage-pill--active",
        "stage-pill--done",
        "stage-pill--error",
        "stage-pill--skipped",
      );
      pill.classList.add(`stage-pill--${status}`);
      const indicator = pill.querySelector(".stage-indicator");
      if (indicator) {
        indicator.textContent = (
          status === "done" ? "✓" :
          status === "error" ? "!" :
          status === "active" ? "●" :
          status === "skipped" ? "—" :
          "○"
        );
      }
      // Inline progress bar for active stage with known totals.
      let progWrap = pill.querySelector(".stage-progress-wrap");
      if (status === "active" && data.total > 0) {
        if (!progWrap) {
          progWrap = document.createElement("span");
          progWrap.className = "stage-progress-wrap";
          progWrap.setAttribute("aria-hidden", "true");
          progWrap.innerHTML = `<span class="stage-progress-fill"></span>`;
          pill.appendChild(progWrap);
        }
        const fill = progWrap.querySelector(".stage-progress-fill");
        if (fill) fill.style.width = Math.max(0, Math.min(100, data.ratio * 100)) + "%";
      } else if (progWrap && status !== "active") {
        progWrap.remove();
      }
    }

    function onEvent(evt) {
      const data = JSON.parse(evt.data);
      const key = `${data.stage}:${data.phase}`;

      if (logEl) {
        const t = new Date().toLocaleTimeString();
        logEl.textContent += `[${t}] ${key.padEnd(18)} ${data.message}\n`;
        logEl.scrollTop = logEl.scrollHeight;
      }

      // Update stage tracker.
      if (STAGE_TITLES[data.stage]) {
        const pillStatus = (
          data.phase === "done" ? "done" :
          data.phase === "error" ? "error" :
          "active"
        );
        updateStagePill(data.stage, pillStatus, data);
      }

      // Title + messages.
      if (titleEl && STAGE_TITLES[data.stage]) {
        titleEl.textContent = STAGE_TITLES[data.stage];
      }
      if (msgEl && data.message) msgEl.textContent = data.message;
      if (metaEl && data.total > 0) {
        metaEl.textContent = `step ${data.current} of ${data.total}`;
      }

      // Overall progress bar — weighted per terminal stage.
      if (fillEl && data.total > 0) {
        const pct = Math.min(100, Math.max(0, data.ratio * 100));
        fillEl.style.width = pct + "%";
      }

      // Per-line callback: passes cache_hit, took_s, speaker, text_preview.
      if (data.stage === "render" && data.phase === "progress" && opts.onLineEvent) {
        opts.onLineEvent(data);
      }

      // Navigation on terminal stage completion.
      if (data.phase === "done" && terminalStages.has(data.stage)) {
        const redirect = (data.extra && data.extra.redirect) || opts.doneRedirect;
        if (redirect) {
          setTimeout(() => { window.location.href = redirect; }, 500);
        }
      }
    }

    function onErrorEvt(evt) {
      try {
        const data = JSON.parse(evt.data);
        if (data.stage) updateStagePill(data.stage, "error", data);
        if (opts.onError) opts.onError(data.message);
        AMW.showError(data.message || "Something went wrong. Check History to resume.");
      } catch (e) {
        /* non-JSON error; skip */
      }
    }

    const ALL_PHASES = ["start", "progress", "done", "error"];
    const ALL_STAGES = Object.keys(STAGE_TITLES);
    ALL_STAGES.forEach((s) =>
      ALL_PHASES.forEach((p) => es.addEventListener(`${s}:${p}`, onEvent))
    );
    es.addEventListener("error:error", onErrorEvt);
    es.onmessage = onEvent;
    es.onerror = () => { /* auto-reconnects */ };

    return { close: () => es.close() };
  };

  // Back-compat alias.
  AMW.subscribeRender = AMW.subscribeProgress;

  AMW.showError = function showError(message) {
    let banner = document.getElementById("global-error-banner");
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "global-error-banner";
      banner.style.cssText =
        "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);" +
        "background:var(--danger);color:white;padding:14px 22px;" +
        "border-radius:10px;box-shadow:var(--shadow-md);z-index:1000;" +
        "max-width:90vw;font-size:14px;white-space:pre-wrap;";
      document.body.appendChild(banner);
    }
    banner.textContent = message;
  };

  // --- voice picker sheet --------------------------------------------------

  /**
   * @param {{ jobId: string, backend: string }} opts
   */
  AMW.initVoicePicker = function initVoicePicker(opts) {
    const sheet = document.getElementById("voice-sheet");
    const listEl = document.getElementById("sheet-voices");
    const sampleEl = document.getElementById("sheet-sample");
    const titleEl = document.getElementById("sheet-title");
    const subtitleEl = document.getElementById("sheet-subtitle");
    if (!sheet) return;

    const jobData = JSON.parse(document.getElementById("job-data").textContent);
    const characters = new Map(jobData.characters.map((c) => [c.name, c]));

    // Cache of full voice list per backend (for "show all" fallback).
    let allVoices = null;

    async function getAllVoices() {
      if (allVoices) return allVoices;
      const resp = await fetch(`/api/voices/${opts.backend}`);
      allVoices = await resp.json();
      return allVoices;
    }

    let currentAudio = null;
    let currentPlayingBtn = null;

    async function playSample(voiceId, text, btn) {
      // Stop any currently playing.
      if (currentAudio) {
        currentAudio.pause();
        currentAudio.currentTime = 0;
      }
      if (currentPlayingBtn) {
        currentPlayingBtn.classList.remove("playing");
      }
      btn.classList.add("playing");
      sampleEl.classList.add("active");
      currentPlayingBtn = btn;

      const url =
        `/api/audition?backend=${encodeURIComponent(opts.backend)}` +
        `&voice_id=${encodeURIComponent(voiceId)}` +
        `&text=${encodeURIComponent(text)}`;
      const audio = new Audio(url);
      currentAudio = audio;
      audio.onended = () => {
        btn.classList.remove("playing");
        if (currentPlayingBtn === btn) currentPlayingBtn = null;
      };
      audio.onerror = () => {
        btn.classList.remove("playing");
        AMW.showError("Could not play audition.");
      };
      try {
        await audio.play();
      } catch (e) {
        btn.classList.remove("playing");
      }
    }

    async function openSheet(character, currentVoice) {
      const char = characters.get(character);
      if (!char) return;
      titleEl.textContent = char.name === "narrator" ? "Narrator" : char.name;
      subtitleEl.textContent =
        [char.personality, char.gender !== "neutral" ? char.gender : null, char.accent !== "unspecified" ? char.accent : null]
          .filter(Boolean).join(" · ");
      const sampleText = char.sample_line ||
        "I think I shall take the long way home today.";
      sampleEl.textContent = `"${sampleText}"`;
      sampleEl.classList.remove("active");

      // Start with ranked proposals; lazily load the full list via "Show more".
      listEl.innerHTML = "";
      const proposals = char.proposals || [];
      const shown = new Set(proposals.map((p) => p.id));

      function renderVoice(v) {
        const li = document.createElement("li");
        li.className = "sheet-voice-row";
        if (v.id === currentVoice) li.classList.add("selected");
        li.innerHTML = `
          <div class="voice-meta">
            <strong>${escapeHtml(v.display_name || v.id)}</strong>
            <div class="caption muted">
              ${[v.gender, v.age, v.accent].filter((x) => x && x !== "neutral" && x !== "unspecified").join(" · ")}
              ${v.tags && v.tags.length ? " · " + v.tags.slice(0, 3).join(", ") : ""}
            </div>
          </div>
          <button type="button" class="sheet-play-btn" aria-label="Play sample">▶</button>
        `;
        const playBtn = li.querySelector(".sheet-play-btn");
        playBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          playSample(v.id, sampleText, playBtn);
        });
        li.addEventListener("click", async () => {
          // Select this voice.
          const resp = await fetch(`/api/voice-swap/${opts.jobId}`, {
            method: "POST",
            body: new URLSearchParams({ character: char.name, voice_id: v.id }),
          });
          if (resp.ok) {
            // Reflect in UI and close.
            document.querySelectorAll(".sheet-voice-row").forEach((el) =>
              el.classList.remove("selected")
            );
            li.classList.add("selected");
            const chip = document.querySelector(
              `.voice-chip[data-character="${CSS.escape(char.name)}"]`
            );
            if (chip) {
              chip.dataset.voice = v.id;
              chip.querySelector(".chip-label").textContent = v.display_name || v.id;
            }
            setTimeout(() => sheet.close(), 200);
          } else {
            AMW.showError("Could not change voice.");
          }
        });
        return li;
      }

      proposals.forEach((v) => listEl.appendChild(renderVoice(v)));

      // "Show all voices" button.
      const showAll = document.createElement("li");
      showAll.className = "sheet-voice-row";
      showAll.style.justifyContent = "center";
      showAll.innerHTML = `<span class="caption muted">Show all voices</span>`;
      showAll.addEventListener("click", async () => {
        showAll.remove();
        const all = await getAllVoices();
        all.filter((v) => !shown.has(v.id))
          .forEach((v) => listEl.appendChild(renderVoice(v)));
      });
      listEl.appendChild(showAll);

      if (opts.onSheetOpen) opts.onSheetOpen(character);
      if (!sheet.open) sheet.showModal();
    }

    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, (m) =>
        ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m])
      );
    }

    document.querySelectorAll(".voice-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        openSheet(chip.dataset.character, chip.dataset.voice);
      });
    });

    sheet.querySelector("[data-close-sheet]")?.addEventListener("click", () => {
      sheet.close();
    });
    // Clicking on the backdrop (outside the sheet box) closes it.
    sheet.addEventListener("click", (e) => {
      if (e.target === sheet) sheet.close();
    });
    sheet.addEventListener("close", () => {
      if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
      }
      if (currentPlayingBtn) {
        currentPlayingBtn.classList.remove("playing");
        currentPlayingBtn = null;
      }
    });
  };

  // --- prior-project cast reuse -------------------------------------------

  AMW.initPriorCast = function initPriorCast(opts) {
    const sel = document.getElementById("prior-build-select");
    const applyBtn = document.getElementById("prior-cast-apply");
    const statusEl = document.getElementById("prior-cast-status");
    if (!sel || !applyBtn) return;

    fetch("/api/prior-builds")
      .then((r) => r.json())
      .then((builds) => {
        sel.innerHTML = "";
        if (!builds.length) {
          sel.innerHTML = '<option value="">No prior projects found</option>';
          return;
        }
        sel.innerHTML = '<option value="">— select a prior project —</option>';
        builds.forEach((b) => {
          const opt = document.createElement("option");
          opt.value = b.path;
          opt.textContent = b.title || b.name;
          sel.appendChild(opt);
        });
        applyBtn.disabled = false;
      })
      .catch(() => {
        sel.innerHTML = '<option value="">Could not load prior projects</option>';
      });

    applyBtn.addEventListener("click", async () => {
      const path = sel.value;
      if (!path) return;
      applyBtn.disabled = true;
      statusEl.hidden = false;
      statusEl.textContent = "Applying…";
      const resp = await fetch(`/api/cast-from/${opts.jobId}`, {
        method: "POST",
        body: new URLSearchParams({ prior_path: path }),
      });
      if (resp.ok) {
        const data = await resp.json();
        statusEl.textContent = data.message + " — reloading…";
        setTimeout(() => window.location.reload(), 800);
      } else {
        const err = await resp.json().catch(() => ({}));
        statusEl.textContent = "Error: " + (err.detail || "unknown");
        applyBtn.disabled = false;
      }
    });
  };

  // --- reference clip upload (voice picker sheet) -------------------------

  AMW.initVoiceRefUpload = function initVoiceRefUpload(opts) {
    const input = document.getElementById("sheet-ref-input");
    const label = document.getElementById("sheet-ref-label");
    const btn = document.getElementById("sheet-ref-upload");
    const status = document.getElementById("sheet-ref-status");
    if (!input || !btn) return;

    // character is set when the sheet opens; stored in closure.
    let currentCharacter = null;

    // Called by initVoicePicker when it opens the sheet for a character.
    AMW._setRefCharacter = function(c) { currentCharacter = c; };

    input.addEventListener("change", () => {
      if (input.files.length) {
        label.textContent = input.files[0].name;
        btn.disabled = false;
      } else {
        label.textContent = "Choose WAV / MP3…";
        btn.disabled = true;
      }
      if (status) status.hidden = true;
    });

    btn.addEventListener("click", async () => {
      if (!input.files.length || !currentCharacter) return;
      btn.disabled = true;
      status.hidden = false;
      status.textContent = "Uploading and normalizing…";

      const fd = new FormData();
      fd.append("character", currentCharacter);
      fd.append("file", input.files[0]);

      const resp = await fetch(`/api/voice-reference/${opts.jobId}`, {
        method: "POST",
        body: fd,
      });
      if (resp.ok) {
        const data = await resp.json();
        status.textContent = `Registered as "${data.voice_id}" — reloading…`;
        setTimeout(() => window.location.reload(), 1000);
      } else {
        const err = await resp.json().catch(() => ({}));
        status.textContent = "Error: " + (err.detail || "upload failed");
        btn.disabled = false;
      }
    });
  };

  // --- boot ---------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", () => {
    initUpload();
  });

  window.AMW = AMW;
})();
