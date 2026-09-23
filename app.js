let currentQrUrl = "";
let qrcodeObj = null;
let isServerConnected = false;
let pollTimer = null;

// Reusable SVG Icons
const SVG_ICONS = {
  download: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`,
  copy: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`,
  clock: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>`,
  cloud: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/></svg>`,
  file: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/></svg>`,
  hash: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/></svg>`,
  bolt: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`,
  pause: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>`
};

// Universal API fetcher that works seamlessly whether served via HTTP or opened directly as file://
async function apiFetch(endpoint, options = {}) {
  const candidates = [];
  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    candidates.push(endpoint);
    candidates.push(`${window.location.origin}${endpoint}`);
  }
  candidates.push(`http://127.0.0.1:8765${endpoint}`);
  candidates.push(`http://localhost:8765${endpoint}`);

  let lastErr = null;
  for (const url of candidates) {
    try {
      const res = await fetch(url, options);
      if (res && (res.ok || res.status < 500)) return res;
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr || new Error("Failed to reach server");
}

// Ensure startup runs regardless of when script loads
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp);
} else {
  initApp();
}

function initApp() {
  pollStatus();
  if (pollTimer) clearInterval(pollTimer);
  // Auto-connect and live poll every 1.5 seconds
  pollTimer = setInterval(pollStatus, 1500);

  // Close dropdown when clicking outside
  document.addEventListener("click", function(e) {
    const wrap = document.getElementById("projectSelectorWrap");
    if (wrap && !wrap.contains(e.target)) {
      closeProjectDropdown();
    }
  });
}

let lastSeenBuildSignatures = {};
let latestDetectedApk = null;
let activeProjectIdCached = "sina-admin-android";

// Web Audio synthesizer for pleasant notification chime
function playChime() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const audioCtx = new AudioCtx();
    const now = audioCtx.currentTime;
    
    // Tone 1: 587.33 Hz (D5)
    const osc1 = audioCtx.createOscillator();
    const gain1 = audioCtx.createGain();
    osc1.type = "sine";
    osc1.frequency.setValueAtTime(587.33, now);
    gain1.gain.setValueAtTime(0.12, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.28);
    osc1.connect(gain1);
    gain1.connect(audioCtx.destination);
    osc1.start(now);
    osc1.stop(now + 0.28);

    // Tone 2: 880 Hz (A5)
    const osc2 = audioCtx.createOscillator();
    const gain2 = audioCtx.createGain();
    osc2.type = "sine";
    osc2.frequency.setValueAtTime(880, now + 0.12);
    gain2.gain.setValueAtTime(0.18, now + 0.12);
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.5);
    osc2.connect(gain2);
    gain2.connect(audioCtx.destination);
    osc2.start(now + 0.12);
    osc2.stop(now + 0.5);
  } catch (e) {
    // Audio context may require user interaction
  }
}

function triggerNewBuildNotification(currentApk) {
  latestDetectedApk = currentApk;
  playChime();

  const banner = document.getElementById("newBuildNotificationBanner");
  const title = document.getElementById("bannerTitle");
  const details = document.getElementById("bannerDetails");

  const ver = currentApk.version_label || ('v' + (currentApk.version || '1.0.0'));
  if (title) title.textContent = `New APK Available: ${ver}!`;
  if (details) details.textContent = `Build updated (${currentApk.build_time || currentApk.uploaded_at_formatted || 'recently'}). Size: ${currentApk.file_size_mb || '--'} MB.`;
  if (banner) banner.classList.remove("hidden");

  const qrBox = document.getElementById("qrcodeCanvas");
  if (qrBox) {
    qrBox.classList.remove("flash-highlight");
    void qrBox.offsetWidth;
    qrBox.classList.add("flash-highlight");
  }

  showToast(`🔔 New APK Detected: ${ver}`);
}

function dismissBanner(apply = false) {
  const banner = document.getElementById("newBuildNotificationBanner");
  if (banner) banner.classList.add("hidden");
  if (apply && latestDetectedApk) {
    updateLatestApk(latestDetectedApk);
    const container = document.getElementById("activeRelease");
    if (container) container.scrollIntoView({ behavior: "smooth" });
  }
}

async function pollStatus() {
  try {
    const res = await apiFetch("/api/status");
    if (!res.ok) {
      setServerConnectionState(false);
      await syncWithGitHubReleases(false);
      return;
    }
    const data = await res.json();

    setServerConnectionState(true, data.watcher?.status);
    updateBadges(data);
    updateProjectsUI(data.config);
    if (data.config?.active_project_id) {
      activeProjectIdCached = data.config.active_project_id;
    }
    updateLatestApk(data.current_apk, data.config);
    renderHistory(data.history || []);
    renderLogs(data.watcher?.logs || []);

  } catch (err) {
    setServerConnectionState(false);
    setWatcherBadge("offline", "Server Offline (Using Cloud Sync)");
    // Fallback: fetch directly from GitHub Releases for standalone live hosting
    await syncWithGitHubReleases(false);
  }
}

// Standalone Cloud Sync for GitHub Pages or Remote Live Site
async function syncWithGitHubReleases(isManual = false) {
  try {
    const res = await fetch("https://api.github.com/repos/mdyahhya/app-releases/releases");
    if (!res.ok) return;
    const releases = await res.json();
    if (!Array.isArray(releases) || releases.length === 0) return;

    // Map releases by tag
    const releaseMap = {};
    releases.forEach(r => {
      if (r.tag_name) releaseMap[r.tag_name] = r;
    });

    const activeTag = activeProjectIdCached || "sina-admin-android";
    const matchedRelease = releaseMap[activeTag] || releaseMap["latest"] || releases[0];

    if (!matchedRelease) return;

    const asset = (matchedRelease.assets && matchedRelease.assets.length > 0) ? matchedRelease.assets[0] : null;
    const downloadUrl = asset ? asset.browser_download_url : `https://github.com/mdyahhya/app-releases/releases/download/${matchedRelease.tag_name}/app-release.apk`;
    const sizeMb = asset ? (asset.size / (1024 * 1024)).toFixed(2) : "22.5";
    const dateFormatted = new Date(matchedRelease.published_at || Date.now()).toLocaleDateString([], {
      day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit"
    });

    const cloudApk = {
      id: matchedRelease.id,
      project_id: activeTag,
      project_name: matchedRelease.name || activeTag,
      filename: asset ? asset.name : "app-release.apk",
      version: matchedRelease.tag_name,
      version_label: matchedRelease.name || matchedRelease.tag_name,
      file_size_mb: sizeMb,
      download_url: downloadUrl,
      provider: "github",
      build_time: dateFormatted,
      uploaded_at: matchedRelease.published_at,
      uploaded_at_formatted: dateFormatted,
      is_latest: true
    };

    updateLatestApk(cloudApk);
    if (isManual) {
      showToast("Cloud sync complete: Live release fetched from GitHub!");
    }
  } catch (e) {
    console.warn("GitHub Releases cloud sync error:", e);
  }
}

async function checkForNewApks(manual = false) {
  const btn = document.getElementById("refreshUpdatesBtn");
  const icon = document.getElementById("refreshIcon");
  const btnText = document.getElementById("refreshBtnText");

  if (manual) {
    if (icon) icon.classList.add("spin");
    if (btnText) btnText.textContent = "Checking...";
    if (btn) btn.disabled = true;
    showToast("Scanning for new APK builds from PC & Cloud...");
  }

  try {
    let connected = false;
    try {
      const res = await apiFetch("/api/status");
      if (res && res.ok) {
        const data = await res.json();
        setServerConnectionState(true, data.watcher?.status);
        updateBadges(data);
        updateProjectsUI(data.config);
        updateLatestApk(data.current_apk, data.config);
        renderHistory(data.history || []);
        renderLogs(data.watcher?.logs || []);
        connected = true;
        if (manual) showToast("Checked: Live local PC & GitHub sync up-to-date!");
      }
    } catch (e) {
      // Offline fallback
    }

    if (!connected) {
      await syncWithGitHubReleases(manual);
    }
  } catch (err) {
    if (manual) showToast("Error checking updates: " + err.message);
  } finally {
    if (manual) {
      setTimeout(() => {
        if (icon) icon.classList.remove("spin");
        if (btnText) btnText.textContent = "Check for Updates";
        if (btn) btn.disabled = false;
      }, 700);
    }
  }
}

function updateProjectsUI(configData) {
  if (!configData) return;
  const activeNameEl = document.getElementById("activeProjectName");
  const sidebarNameEl = document.getElementById("sidebarProjectName");
  const sidebarPathEl = document.getElementById("sidebarProjectPath");

  if (activeNameEl) activeNameEl.textContent = configData.project_name || "SINA User Android";
  if (sidebarNameEl) sidebarNameEl.textContent = configData.project_name || "SINA User Android";
  if (sidebarPathEl) {
    const relPath = configData.apk_file_path || "build/app/outputs/flutter-apk/app-release.apk";
    sidebarPathEl.textContent = relPath;
    sidebarPathEl.title = relPath;
  }

  renderProjectDropdownItems(configData.projects || [], configData.active_project_id);
  renderProjectTabs(configData.projects || [], configData.active_project_id);
}

function renderProjectTabs(projects, activeId) {
  const container = document.getElementById("projectTabsList");
  if (!container) return;

  if (projects.length === 0) {
    container.innerHTML = `<div class="project-tab disabled">No projects</div>`;
    return;
  }

  container.innerHTML = projects.map(proj => {
    const isActive = proj.id === activeId;
    return `
      <button class="project-tab ${isActive ? 'active' : ''}" onclick="switchProject('${proj.id}')" title="${escapeHtml(proj.apk_path || '')}">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="5" y="2" width="14" height="20" rx="2" ry="2"/>
          <line x1="12" y1="18" x2="12.01" y2="18"/>
        </svg>
        <span class="tab-title">${escapeHtml(proj.name)}</span>
        ${isActive ? `<span class="tab-indicator"></span>` : ''}
      </button>
    `;
  }).join("");
}

function renderProjectDropdownItems(projects, activeId) {
  const container = document.getElementById("projectListItems");
  if (!container) return;

  if (projects.length === 0) {
    container.innerHTML = `<div class="dropdown-item disabled">No projects configured</div>`;
    return;
  }

  container.innerHTML = projects.map(proj => {
    const isActive = proj.id === activeId;
    return `
      <button class="dropdown-item ${isActive ? 'active' : ''}" onclick="switchProject('${proj.id}')">
        <div class="dropdown-item-left">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="5" y="2" width="14" height="20" rx="2" ry="2"/>
            <line x1="12" y1="18" x2="12.01" y2="18"/>
          </svg>
          <span>${escapeHtml(proj.name)}</span>
        </div>
        ${isActive ? `<span class="check-mark">✓</span>` : ''}
      </button>
    `;
  }).join("");
}

function toggleProjectDropdown(event) {
  if (event) event.stopPropagation();
  const dropdown = document.getElementById("projectDropdownMenu");
  if (dropdown) {
    dropdown.classList.toggle("hidden");
  }
}

function closeProjectDropdown() {
  const dropdown = document.getElementById("projectDropdownMenu");
  if (dropdown && !dropdown.classList.contains("hidden")) {
    dropdown.classList.add("hidden");
  }
}

async function switchProject(projectId) {
  closeProjectDropdown();
  // Force reset QR cache so the newly selected tab always regenerates its QR code
  currentQrUrl = "";
  
  showToast("Switching project tab...");
  try {
    const res = await apiFetch("/api/projects/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message || "Switched active project tab!");
      if (data.config) updateProjectsUI(data.config);
      if (data.current_apk) updateLatestApk(data.current_apk, data.config);
      if (data.history) renderHistory(data.history);
      await pollStatus();
    } else {
      showToast("Error switching project tab: " + (data.error || "Failed"));
    }
  } catch (err) {
    showToast("Failed to switch project tab: " + err.message);
  }
}

function openAddProjectModal() {
  closeProjectDropdown();
  const modal = document.getElementById("addProjectModal");
  if (modal) modal.classList.remove("hidden");
}

function closeAddProjectModal() {
  const modal = document.getElementById("addProjectModal");
  if (modal) modal.classList.add("hidden");
}

function handleModalOverlayClick(e) {
  if (e.target && e.target.id === "addProjectModal") {
    closeAddProjectModal();
  }
}

async function browseNativeFolder() {
  showToast("Opening Windows File Explorer folder picker...");
  try {
    const res = await apiFetch("/api/browse-folder", { method: "POST" });
    const data = await res.json();
    if (data.success && data.folder_path) {
      const folderInput = document.getElementById("projFolderInput");
      const nameInput = document.getElementById("projNameInput");
      const apkInput = document.getElementById("projApkInput");

      if (folderInput) folderInput.value = data.folder_path;
      if (nameInput && (!nameInput.value || nameInput.value.trim() === "")) {
        nameInput.value = data.project_name || "";
      }
      if (apkInput && data.auto_apk_path) {
        apkInput.value = data.auto_apk_path;
      }
      showToast(`Selected project folder: ${data.project_name}`);
    } else {
      showToast("Folder selection cancelled.");
    }
  } catch (err) {
    showToast("Error opening folder picker: " + err.message);
  }
}

async function handleAddProjectSubmit(event) {
  event.preventDefault();
  const nameInput = document.getElementById("projNameInput");
  const folderInput = document.getElementById("projFolderInput");
  const apkInput = document.getElementById("projApkInput");

  const name = nameInput ? nameInput.value.trim() : "";
  const folder = folderInput ? folderInput.value.trim() : "";
  const apk = apkInput ? apkInput.value.trim() : "";

  if (!name || !folder) {
    showToast("Project Name and Folder Path are required!");
    return;
  }

  const saveBtn = document.getElementById("saveProjBtn");
  if (saveBtn) saveBtn.disabled = true;

  try {
    const res = await apiFetch("/api/projects/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        flutter_project_root: folder,
        apk_path: apk || null
      })
    });
    const data = await res.json();
    if (data.success) {
      closeAddProjectModal();
      showToast(data.message || `Project '${name}' added & activated!`);
      if (nameInput) nameInput.value = "";
      if (folderInput) folderInput.value = "";
      if (apkInput) apkInput.value = "";
      await pollStatus();
    } else {
      showToast("Error adding project: " + (data.error || "Failed"));
    }
  } catch (err) {
    showToast("Error creating project: " + err.message);
  } finally {
    if (saveBtn) saveBtn.disabled = false;
  }
}

function setServerConnectionState(isOnline, statusText = "") {
  isServerConnected = isOnline;
  const connBtn = document.getElementById("serverConnBtn");
  const connDot = document.getElementById("serverConnDot");
  const connText = document.getElementById("serverConnText");

  if (!connBtn) return;

  if (isOnline) {
    connBtn.classList.remove("offline");
    if (connDot) {
      connDot.className = "status-indicator dot-active";
    }
    if (connText) {
      connText.textContent = "Server Online";
    }
  } else {
    connBtn.classList.add("offline");
    if (connDot) {
      connDot.className = "status-indicator dot-offline";
    }
    if (connText) {
      connText.textContent = "Offline (Click to Connect)";
    }
  }
}

async function manualReconnect() {
  const icon = document.getElementById("reconnectIcon");
  if (icon) icon.classList.add("spin");

  try {
    const res = await apiFetch("/api/status");
    if (!res.ok) throw new Error("Status " + res.status);
    const data = await res.json();

    setServerConnectionState(true, data.watcher?.status);
    updateBadges(data);
    updateLatestApk(data.current_apk, data.config);
    renderHistory(data.history || []);
    renderLogs(data.watcher?.logs || []);

    showToast(`Connected: CRM Server Online (${data.watcher?.status || 'Active'})`);
  } catch (err) {
    setServerConnectionState(false);
    showToast("Connection failed: Make sure 'python run.py' is running in terminal.");
  } finally {
    setTimeout(() => {
      if (icon) icon.classList.remove("spin");
    }, 600);
  }
}

function updateBadges(data) {
  const providerBadge = document.getElementById("providerBadge");
  if (providerBadge && data.config) {
    providerBadge.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22"/>
      </svg>
      <span>GitHub Releases (${data.config.github_repo || 'app-releases'})</span>
    `;
  }

  const isAuto = data.watcher?.auto_watch_enabled !== false;
  const toggleBtn = document.getElementById("autoWatchToggleBtn");
  if (toggleBtn) {
    if (isAuto) {
      toggleBtn.className = "btn btn-toggle active";
      toggleBtn.innerHTML = `${SVG_ICONS.bolt} <span id="autoWatchText">Auto-Watch: ON</span>`;
    } else {
      toggleBtn.className = "btn btn-toggle disabled";
      toggleBtn.innerHTML = `${SVG_ICONS.pause} <span id="autoWatchText">Manual Mode (OFF)</span>`;
    }
  }

  const watcherStatus = data.watcher?.status || "idle";
  const uploadStatus = data.watcher?.upload_status || "none";

  if (uploadStatus === "uploading") {
    setWatcherBadge("amber", "Uploading to GitHub...");
  } else if (watcherStatus === "building") {
    setWatcherBadge("amber", "Flutter Compiling APK...");
  } else if (watcherStatus === "manual_mode") {
    setWatcherBadge("gray", "Manual Mode Ready");
  } else if (watcherStatus === "monitoring" || watcherStatus === "waiting_for_file") {
    setWatcherBadge("active", isAuto ? "Monitoring PC APK" : "Manual Mode Ready");
  } else {
    setWatcherBadge("gray", watcherStatus);
  }

  if (data.watcher?.last_check_time) {
    const timeEl = document.getElementById("lastCheckTime");
    if (timeEl) timeEl.textContent = `Last checked: ${data.watcher.last_check_time}`;
  }
}

function setWatcherBadge(state, text) {
  const badge = document.getElementById("watcherBadge");
  if (!badge) return;

  let dotClass = "dot-gray";
  if (state === "active") dotClass = "dot-active";
  if (state === "amber") dotClass = "dot-amber";
  if (state === "offline") dotClass = "dot-offline";

  badge.innerHTML = `<span class="status-indicator ${dotClass}"></span> <span>${text}</span>`;
}

function updateLatestApk(currentApk, config) {
  const urlInput = document.getElementById("downloadUrlInput");
  const targetUrl = currentApk?.download_url || config?.download_url || "https://github.com/mdyahhya/app-releases/releases/download/latest/app-release.apk";

  if (urlInput && urlInput.value !== targetUrl) {
    urlInput.value = targetUrl;
  }

  const container = document.getElementById("qrcodeCanvas");
  if (targetUrl && (currentQrUrl !== targetUrl || (container && !container.firstElementChild))) {
    currentQrUrl = targetUrl;
    renderQrCode(targetUrl);
  }

  if (currentApk) {
    const projId = currentApk.project_id || config?.active_project_id || activeProjectIdCached || "default";
    const signature = `${currentApk.id || ''}_${currentApk.sha256 || ''}_${currentApk.mtime_timestamp || currentApk.uploaded_at || ''}`;

    if (lastSeenBuildSignatures[projId] && lastSeenBuildSignatures[projId] !== signature) {
      triggerNewBuildNotification(currentApk);
    }
    lastSeenBuildSignatures[projId] = signature;

    const verEl = document.getElementById("metaVersion");
    const sizeEl = document.getElementById("metaSize");
    const buildTimeEl = document.getElementById("metaBuildTime");
    const timeEl = document.getElementById("metaTime");
    const shaEl = document.getElementById("metaSha");

    if (verEl) verEl.textContent = currentApk.version_label || `v${currentApk.version}`;
    if (sizeEl) sizeEl.textContent = `${currentApk.file_size_mb} MB`;
    if (buildTimeEl) {
      buildTimeEl.textContent = currentApk.build_time || currentApk.file_modified_at || currentApk.uploaded_at_formatted || "Recently";
    }
    if (timeEl) timeEl.textContent = currentApk.uploaded_at_formatted || "Recently";
    if (shaEl) shaEl.textContent = currentApk.sha256 ? currentApk.sha256.substring(0, 20) + "..." : "--";
  }
}

function renderQrCode(url) {
  const container = document.getElementById("qrcodeCanvas");
  if (!container || !url) return;

  container.innerHTML = "";

  if (typeof QRCode !== "undefined") {
    try {
      qrcodeObj = new QRCode(container, {
        text: url,
        width: 175,
        height: 175,
        colorDark: "#0f172a",
        colorLight: "#ffffff",
        correctLevel: QRCode.CorrectLevel.M
      });
    } catch (err) {
      console.warn("QRCode library exception, using fallback renderer:", err);
      container.innerHTML = `<img src="https://api.qrserver.com/v1/create-qr-code/?size=175x175&data=${encodeURIComponent(url)}" alt="QR Code" width="175" height="175" style="display:block; border-radius: 8px;" />`;
    }
  } else {
    container.innerHTML = `<img src="https://api.qrserver.com/v1/create-qr-code/?size=175x175&data=${encodeURIComponent(url)}" alt="QR Code" width="175" height="175" style="display:block; border-radius: 8px;" />`;
  }

  const placeholder = document.getElementById("qrPlaceholder");
  if (placeholder) placeholder.classList.add("hidden");
}

function renderHistory(historyList) {
  const container = document.getElementById("historyTimeline");
  const countBadge = document.getElementById("buildCountBadge");
  const navCount = document.getElementById("navHistoryCount");
  
  if (!container) return;

  if (countBadge) countBadge.textContent = `${historyList.length} Builds`;
  if (navCount) navCount.textContent = `${historyList.length}`;

  if (historyList.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No build history recorded yet. Click <strong>Check & Upload Now</strong> or build in Flutter to populate.</p>
      </div>`;
    return;
  }

  const html = historyList.map((item, index) => {
    const isLatest = index === 0 || item.is_latest;
    const badgeHtml = isLatest
      ? `<span class="badge-latest">LATEST</span>`
      : `<span class="badge-archive">#${historyList.length - index}</span>`;

    const buildTimeStr = item.build_time || item.file_modified_at || item.uploaded_at_formatted;
    const uploadTimeStr = item.uploaded_at_formatted || new Date(item.uploaded_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    return `
      <div class="timeline-item ${isLatest ? 'is-latest' : ''}">
        <div class="timeline-top">
          <div class="timeline-title-wrap">
            ${badgeHtml}
            <span class="version-name">${item.version_label || 'v' + item.version}</span>
          </div>
          <div class="timeline-time-chip" title="File Build Timestamp">
            ${SVG_ICONS.clock} <span>${buildTimeStr}</span>
          </div>
        </div>

        <div class="timeline-specs">
          <div class="spec-inline">
            ${SVG_ICONS.file} <span>Size: <strong>${item.file_size_mb} MB</strong></span>
          </div>
          <div class="spec-inline">
            ${SVG_ICONS.cloud} <span>Uploaded: <strong>${uploadTimeStr}</strong></span>
          </div>
        </div>

        <div class="timeline-checksum">
          ${SVG_ICONS.hash} <code class="code-font">${item.sha256 ? item.sha256.substring(0, 16) : '--'}...</code>
        </div>

        <div class="timeline-btn-row">
          <a href="${item.download_url}" target="_blank" class="btn btn-sm btn-primary">
            ${SVG_ICONS.download} <span>Download APK</span>
          </a>
          <button class="btn btn-sm btn-secondary" onclick="copyCustomUrl('${item.download_url}')">
            ${SVG_ICONS.copy} <span>Copy Link</span>
          </button>
        </div>
      </div>
    `;
  }).join("");

  container.innerHTML = html;
}

function renderLogs(logs) {
  const stream = document.getElementById("logStream");
  if (!stream) return;

  if (logs.length === 0) return;

  stream.innerHTML = logs.map(line => {
    let typeClass = "info";
    if (line.includes("[SUCCESS]") || line.includes("✓")) typeClass = "success";
    if (line.includes("[ERROR]") || line.includes("✕") || line.includes("Failed")) typeClass = "error";
    if (line.includes("[WARN]")) typeClass = "warn";
    
    // Sanitize any remaining emojis from backend log strings
    const cleanLine = line.replace(/[🚀⚡🔨☁️📦🔑📋⬇️🔄🔗⏸️✕✓]/g, "");

    return `<div class="log-line ${typeClass}">${escapeHtml(cleanLine)}</div>`;
  }).join("");

  stream.scrollTop = stream.scrollHeight;
}

async function toggleAutoWatch() {
  try {
    const res = await apiFetch("/api/watcher/toggle", { method: "POST" });
    const data = await res.json();
    showToast(data.message || (data.auto_watch_enabled ? "Auto-Watch Enabled" : "Manual Mode Enabled"));
    pollStatus();
  } catch (err) {
    showToast("Failed to toggle Auto-Watch mode");
  }
}

async function triggerManualCheckAndUpload() {
  const btn = document.getElementById("manualCheckBtn");
  const originalHtml = btn ? btn.innerHTML : "";
  
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `
      <div class="spinner-sm"></div>
      <span>Uploading APK...</span>
    `;
  }

  showToast("Scanning APK & uploading to GitHub Releases...");

  try {
    const res = await apiFetch("/api/watcher/trigger", { method: "POST" });
    const data = await res.json();
    
    if (data.success) {
      showToast("APK Uploaded Successfully! QR & History Updated.");
      await pollStatus();
    } else {
      showToast("Upload Error: " + (data.error || data.message || "Failed to upload APK"));
    }
  } catch (err) {
    showToast("Error uploading APK: " + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = originalHtml;
    }
  }
}

async function triggerManualUpload() {
  await triggerManualCheckAndUpload();
}

async function testConnection() {
  await manualReconnect();
}

function copyDownloadUrl() {
  const input = document.getElementById("downloadUrlInput");
  if (input) {
    copyCustomUrl(input.value);
  }
}

function copyCustomUrl(text) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => {
      showToast("Download URL copied to clipboard!");
    }).catch(() => fallbackCopy(text));
  } else {
    fallbackCopy(text);
  }
}

function fallbackCopy(text) {
  const el = document.createElement("textarea");
  el.value = text;
  document.body.appendChild(el);
  el.select();
  document.execCommand("copy");
  document.body.removeChild(el);
  showToast("Copied to clipboard!");
}

function showToast(msg) {
  const toast = document.getElementById("toast");
  if (!toast) return;

  toast.textContent = msg;
  toast.classList.remove("hidden");
  toast.style.opacity = "1";

  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.classList.add("hidden"), 300);
  }, 2800);
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
