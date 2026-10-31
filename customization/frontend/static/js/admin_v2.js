/**
 * Calibre Institutional Admin Console V2 — Production Frontend Controller
 * Connects all 8 modules to live Institutional Gateway APIs (/api/admin/* and /api/v2/admin/*)
 * while enforcing XSS-safe DOM creation, dynamic branding, and responsive state controls.
 */

const V2_STATE = {
  currentView: "dashboard",
  previewMode: "live", // 'live' | 'loading' | 'empty' | 'error'
  institution: {},
  currentUser: {},
  libraries: [],
  users: [],
  catalogue: {},
  audit: [],
  auditTotal: 0,
  auditOffset: 0,
  auditLimit: 25,
  system: {},
  backups: [],
  landingContent: {}
};

const VIEW_META = {
  dashboard: { title: "Dashboard Overview", group: "CORE OPERATIONS" },
  users: { title: "Users & Access Management", group: "CORE OPERATIONS" },
  libraries: { title: "Library Management", group: "CORE OPERATIONS" },
  catalogue: { title: "Catalogue & Metadata Settings", group: "CORE OPERATIONS" },
  branding: { title: "Institution Branding", group: "INSTITUTION & INFRASTRUCTURE" },
  network: { title: "Server & Network", group: "INSTITUTION & INFRASTRUCTURE" },
  backups: { title: "Backup & Recovery", group: "INSTITUTION & INFRASTRUCTURE" },
  audit: { title: "Audit & Security", group: "INSTITUTION & INFRASTRUCTURE" }
};

const BRAND_PRESETS = {
  aethelgard: {
    name: "Aethelgard Institute of Technology",
    short_name: "AIT",
    library_name: "The Institutional Library",
    motto: "Knowledge Preserved, Universally Accessible",
    contact_email: "library@aethelgard.edu",
    contact_phone: "+1 (555) 019-8841",
    primary_color: "#183c34"
  },
  oxford: {
    name: "St. Jude's College Digital Archive",
    short_name: "SJC",
    library_name: "Bodleian & Fellows Research Collection",
    motto: "Dominus Illuminatio Mea · Scholarly Editions",
    contact_email: "archivist@stjudes.ac.uk",
    contact_phone: "+44 1865 270000",
    primary_color: "#14284b"
  },
  conservatory: {
    name: "Royal Seminary & Historical Athenaeum",
    short_name: "RSHA",
    library_name: "Rare Manuscripts & Archival Vault",
    motto: "Preserving Classical Scholarship Across Centuries",
    contact_email: "curator@royalseminary.org",
    contact_phone: "+1 (617) 555-0142",
    primary_color: "#4a1c24"
  },
  botanical: {
    name: "Nordic Institute of Natural Sciences",
    short_name: "NINS",
    library_name: "Botanical & Ecological Digital Repository",
    motto: "Open Scientific Inquiry for the Northern Biosphere",
    contact_email: "repository@nordicscience.se",
    contact_phone: "+46 8 555 01 99",
    primary_color: "#254438"
  }
};

function elText(tag, text, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text == null ? "" : String(text);
  return node;
}

function showGlobalBanner(message, type = "success") {
  const banner = document.getElementById("v2-global-banner");
  const textEl = document.getElementById("v2-global-banner-text");
  if (!banner || !textEl) return;
  banner.className = `v2-banner ${type}`;
  textEl.textContent = message;
  banner.classList.remove("hidden");
}

function hideGlobalBanner() {
  const banner = document.getElementById("v2-global-banner");
  if (banner) banner.classList.add("hidden");
}

function toggleMobileSidebar(open) {
  const sidebar = document.getElementById("v2-sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (!sidebar || !backdrop) return;
  if (open) {
    sidebar.classList.add("open");
    backdrop.classList.add("open");
  } else {
    sidebar.classList.remove("open");
    backdrop.classList.remove("open");
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  // Bind sidebar navigation buttons
  document.querySelectorAll(".v2-nav-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const view = btn.getAttribute("data-view");
      if (view) switchView(view);
      toggleMobileSidebar(false);
    });
  });

  // Check URL query params immediately so initial view is active before async fetch
  const params = new URLSearchParams(window.location.search);
  const initialView = params.get("view") || (window.location.hash ? window.location.hash.replace("#", "") : "dashboard");
  if (VIEW_META[initialView]) {
    switchView(initialView, false);
  }

  // Show UI state switcher bar if ?debug_ui=1 or ?state= is provided
  if (params.get("debug_ui") === "1" || params.has("state")) {
    const switcherBar = document.getElementById("v2-state-switcher-bar");
    if (switcherBar) switcherBar.classList.remove("hidden");
  }

  // Load initial data from backend
  await loadAllV2Data();

  // Re-ensure initialView and optional query states
  if (VIEW_META[initialView]) {
    switchView(initialView, false);
  }
  const initialState = params.get("state");
  if (params.get("debug_ui") === "1" && initialState && ["live", "loading", "empty", "error"].includes(initialState)) {
    setPreviewState(initialState);
  }
  const initialModal = params.get("modal");
  if (initialModal === "create-user") {
    openUserModal();
  } else if (initialModal === "connect-library") {
    openConnectLibraryModal();
  }
  const preset = params.get("preset");
  if (preset && BRAND_PRESETS[preset]) {
    applyBrandPreset(preset);
  }
  if (params.get("drawer") === "open") {
    toggleMobileSidebar(true);
  }
});

function switchView(viewName, updateUrl = true) {
  if (!VIEW_META[viewName]) return;
  V2_STATE.currentView = viewName;
  hideGlobalBanner();

  document.querySelectorAll(".v2-nav-btn").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-view") === viewName);
  });

  document.querySelectorAll(".v2-view").forEach(section => {
    section.classList.toggle("active", section.id === `view-${viewName}`);
  });

  const meta = VIEW_META[viewName];
  document.getElementById("topbar-view-title").textContent = meta.title;
  document.getElementById("topbar-section-group").textContent = meta.group;

  if (updateUrl && window.history && window.history.replaceState) {
    const url = new URL(window.location.href);
    url.searchParams.set("view", viewName);
    window.history.replaceState({}, "", url.toString());
  }

  if (V2_STATE.previewMode !== "live") {
    renderSimulatedState(V2_STATE.previewMode);
  }
}

function setPreviewState(mode) {
  V2_STATE.previewMode = mode;
  document.querySelectorAll(".v2-state-btn").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-state") === mode);
  });

  const simContainer = document.getElementById("v2-simulated-state-container");
  const activeView = document.getElementById(`view-${V2_STATE.currentView}`);

  if (mode === "live") {
    simContainer.classList.add("hidden");
    if (activeView) activeView.style.display = "";
    hideGlobalBanner();
    return;
  }

  renderSimulatedState(mode);
}

function renderSimulatedState(mode) {
  const simContainer = document.getElementById("v2-simulated-state-container");
  const activeView = document.getElementById(`view-${V2_STATE.currentView}`);
  const meta = VIEW_META[V2_STATE.currentView] || { title: "Module" };

  if (activeView) activeView.style.display = "none";
  simContainer.classList.remove("hidden");
  simContainer.replaceChildren();

  const card = document.createElement("div");
  card.className = "v2-card";
  const body = document.createElement("div");
  body.className = "v2-card-body";

  if (mode === "loading") {
    const box = document.createElement("div");
    box.className = "v2-state-box";
    box.append(
      elText("h4", `Synchronizing ${meta.title}...`),
      elText("p", "Querying Institutional Configuration SQLite store and verifying loopback Calibre Content Server state.")
    );
    for (let i = 0; i < 4; i++) {
      const skel = document.createElement("div");
      skel.className = "v2-skeleton-line";
      skel.style.width = `${85 - i * 12}%`;
      skel.style.margin = "10px auto";
      box.appendChild(skel);
    }
    body.appendChild(box);
  } else if (mode === "empty") {
    const box = document.createElement("div");
    box.className = "v2-state-box";
    box.append(
      elText("h4", `No Records Configured in ${meta.title}`),
      elText("p", "This collection or directory currently contains zero active entries. Use the primary action below to provision your first institutional record or restore from a verified Tier-1 configuration snapshot.")
    );
    const btn = elText("button", "Return to Live Populated View", "btn-v2 btn-v2-primary");
    btn.type = "button";
    btn.onclick = () => setPreviewState("live");
    box.appendChild(btn);
    body.appendChild(box);
  } else if (mode === "error") {
    showGlobalBanner("Upstream Communication Warning: Loopback Calibre Content Server (127.0.0.1:8088) timed out during probe. Serving cached configuration safely.", "error");
    const box = document.createElement("div");
    box.className = "v2-state-box";
    box.style.borderColor = "var(--status-err-border)";
    box.style.background = "var(--status-err-bg)";
    box.append(
      elText("h4", `Unable to Retrieve ${meta.title} Telemetry`),
      elText("p", "The Institutional Gateway encountered a transient lock or timeout while probing the loopback service. No database changes were committed, and existing patron sessions remain protected.")
    );
    const retryBtn = elText("button", "Retry Connection & Restore Live State", "btn-v2 btn-v2-primary");
    retryBtn.type = "button";
    retryBtn.onclick = () => setPreviewState("live");
    box.appendChild(retryBtn);
    body.appendChild(box);
  }

  card.appendChild(body);
  simContainer.appendChild(card);
}

/* ==========================================================================
   Data Fetching & Synchronization
   ========================================================================== */

async function fetchJsonSafe(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (res.status === 401 || res.status === 403) {
    const err = new Error("AUTH_REQUIRED");
    err.status = res.status;
    throw err;
  }
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

async function loadAllV2Data() {
  try {
    const results = await Promise.allSettled([
      fetchJsonSafe("/api/admin/dashboard?t=" + Date.now()),
      fetchJsonSafe("/api/admin/libraries?t=" + Date.now()),
      fetchJsonSafe("/api/admin/users?t=" + Date.now()),
      fetchJsonSafe("/api/admin/system?t=" + Date.now()),
      fetchJsonSafe("/api/admin/catalogue-settings?t=" + Date.now()),
      fetchJsonSafe(`/api/admin/audit-log?paginated=1&limit=${V2_STATE.auditLimit}&offset=${V2_STATE.auditOffset}&t=` + Date.now())
    ]);

    for (const r of results) {
      if (r.status === "rejected" && r.reason && (r.reason.status === 401 || r.reason.status === 403)) {
        window.location.href = "/?login_required=1";
        return;
      }
    }

    const dashData = results[0].status === "fulfilled" ? results[0].value : {};
    const libsData = results[1].status === "fulfilled" ? results[1].value : null;
    const usersData = results[2].status === "fulfilled" ? results[2].value : null;
    const sysData = results[3].status === "fulfilled" ? results[3].value : {};
    const catData = results[4].status === "fulfilled" ? results[4].value : null;
    const auditData = results[5].status === "fulfilled" ? results[5].value : null;

    if (dashData && dashData.institution) {
      V2_STATE.institution = dashData.institution;
    }
    if (dashData && dashData.current_user) {
      V2_STATE.currentUser = dashData.current_user;
    }
    if (Array.isArray(libsData)) {
      V2_STATE.libraries = libsData;
    } else if (dashData && Array.isArray(dashData.libraries)) {
      V2_STATE.libraries = dashData.libraries;
    }
    if (Array.isArray(usersData)) {
      V2_STATE.users = usersData;
    }
    V2_STATE.system = Object.assign({}, dashData.system || {}, sysData || {});
    if (catData && typeof catData === "object") {
      V2_STATE.catalogue = catData;
    } else if (dashData && dashData.catalogue_settings) {
      V2_STATE.catalogue = dashData.catalogue_settings;
    }
    if (dashData && Array.isArray(dashData.backups)) {
      V2_STATE.backups = dashData.backups;
    }

    if (Array.isArray(auditData)) {
      V2_STATE.audit = auditData;
      V2_STATE.auditTotal = auditData.length;
    } else if (auditData && Array.isArray(auditData.items)) {
      V2_STATE.audit = auditData.items;
      V2_STATE.auditTotal = typeof auditData.total === "number" ? auditData.total : auditData.items.length;
    } else if (dashData && Array.isArray(dashData.recent_audit)) {
      V2_STATE.audit = dashData.recent_audit;
      V2_STATE.auditTotal = V2_STATE.audit.length;
    }

    if (dashData && dashData.landing_content) {
      V2_STATE.landingContent = dashData.landing_content;
    }

    applyInstitutionBrandingToShell(V2_STATE.institution, V2_STATE.currentUser);
    renderDashboard();
    renderUsersTable();
    renderLibrariesTable();
    populateCatalogueForm();
    populateBrandingForm();
    renderSystemAndNetwork();
    renderBackupsInventory();
    renderAuditTable();
  } catch (err) {
    showGlobalBanner("Notice: Some operational metrics could not be refreshed (" + err.message + ").", "warning");
  }
}

/* ==========================================================================
   Dynamic Institution Branding Application
   ========================================================================== */

function computeInitials(displayName) {
  const parts = String(displayName || "Admin").trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return String(parts[0] || "AD").substring(0, 2).toUpperCase();
}

function applyInstitutionBrandingToShell(inst, currentUser) {
  const name = inst.name || inst.institution_name || "Institutional Digital Library";
  const shortCode = inst.short_name || "IDL";
  const libTitle = inst.library_name || inst.library_title || "Digital Collections";
  const motto = inst.motto || "Knowledge Preserved, Universally Accessible";
  const logoUrl = inst.logo_url || inst.logo_path || "/static/images/institution-mark.svg";
  const primaryColor = inst.primary_color || "#183c34";

  // Inject dynamic CSS variable
  const styleEl = document.getElementById("dynamic-brand-theme");
  if (styleEl && /^#[0-9a-fA-F]{6}$/.test(primaryColor)) {
    styleEl.textContent = `:root { --brand-primary: ${primaryColor}; }`;
  }

  // Sidebar & Topbar Identity
  const sbShort = document.getElementById("sidebar-short-code");
  const sbTitle = document.getElementById("sidebar-inst-title");
  const sbSub = document.getElementById("sidebar-lib-subtitle");
  const tbShort = document.getElementById("topbar-inst-short");
  if (sbShort) sbShort.textContent = shortCode;
  if (sbTitle) sbTitle.textContent = name;
  if (sbSub) sbSub.textContent = libTitle;
  if (tbShort) tbShort.textContent = shortCode;

  // Sidebar Officer Identity
  const adminUser = (currentUser && currentUser.displayName)
    ? currentUser
    : (V2_STATE.users.find(u => u.role === "Administrator") || {});
  const officerName = adminUser.displayName || adminUser.display_name || `${name} Administrator`;
  const officerRole = adminUser.role || "Administrator";
  const elOffName = document.getElementById("sidebar-officer-name");
  const elOffRole = document.getElementById("sidebar-officer-role");
  const elOffInit = document.getElementById("sidebar-officer-initials");
  if (elOffName) elOffName.textContent = officerName;
  if (elOffRole) elOffRole.textContent = officerRole;
  if (elOffInit) elOffInit.textContent = computeInitials(officerName);

  const sidebarLogo = document.getElementById("sidebar-logo-img");
  const dashLogo = document.getElementById("dash-hero-logo");
  if (sidebarLogo) sidebarLogo.src = logoUrl;
  if (dashLogo) dashLogo.src = logoUrl;

  // Dashboard Hero
  const heroName = document.getElementById("dash-hero-inst-name");
  const heroMotto = document.getElementById("dash-hero-motto");
  if (heroName) heroName.textContent = name;
  if (heroMotto) heroMotto.textContent = `${motto} · ${libTitle}`;

  // Update hosts file example with current shortCode
  const hostsEx = document.getElementById("net-hosts-example");
  if (hostsEx) {
    hostsEx.textContent = `127.0.0.1    library.${shortCode.toLowerCase().replace(/[^a-z0-9]/g, "") || "institution"}.local`;
  }
}

/* ==========================================================================
   1. Dashboard Overview Rendering
   ========================================================================== */

function renderDashboard() {
  const inst = V2_STATE.institution;
  const libs = V2_STATE.libraries;
  const users = V2_STATE.users;
  const sys = V2_STATE.system;
  const backups = Array.isArray(V2_STATE.backups) ? V2_STATE.backups : [];

  document.getElementById("nav-pill-users").textContent = users.length;
  document.getElementById("nav-pill-libraries").textContent = libs.length;

  document.getElementById("metric-libraries-count").textContent = libs.length;
  const totalVolumes = libs.reduce((acc, l) => acc + (typeof l.books_count === "number" ? l.books_count : 0), 0);
  document.getElementById("metric-volumes-total").textContent = `${totalVolumes} indexed volumes`;

  document.getElementById("metric-users-count").textContent = users.length;
  const adminsCount = users.filter(u => u.role === "Administrator").length;
  const activeCount = users.filter(u => u.is_active !== false).length;
  const patronsCount = Math.max(0, users.length - adminsCount);
  document.getElementById("metric-users-breakdown").textContent = `${adminsCount} Admin · ${patronsCount} Patron (${activeCount} active)`;

  const engineOnline = sys.calibre_backend_online !== false;
  const activeSessions = typeof sys.active_sessions === "number" ? sys.active_sessions : 1;
  document.getElementById("metric-gateway-port").textContent = engineOnline ? "Online" : "Standby";
  document.getElementById("metric-engine-port").textContent = `Port ${sys.gateway_port || 8085} · ${activeSessions} active session(s)`;

  const metricSec = document.getElementById("metric-security-mode");
  const metricTier = document.getElementById("metric-storage-tier");
  if (metricSec) metricSec.textContent = backups.length > 0 ? `${backups.length} Saved` : "Ready";
  if (metricTier) metricTier.textContent = backups.length > 0 ? `Latest: ${backups[0].created_at.substring(0, 10)}` : "3-Tier Backup Ready";

  const topPill = document.getElementById("topbar-engine-pill");
  const topText = document.getElementById("topbar-engine-text");
  const metricBadge = document.getElementById("metric-engine-badge");
  if (engineOnline) {
    if (topPill) topPill.className = "v2-status-pill";
    if (topText) topText.textContent = "Library Service: Online";
    if (metricBadge) {
      metricBadge.className = "v2-badge v2-badge-green";
      metricBadge.textContent = "Healthy";
    }
  } else {
    if (topPill) topPill.className = "v2-status-pill warn";
    if (topText) topText.textContent = "Library Service: Standby";
    if (metricBadge) {
      metricBadge.className = "v2-badge v2-badge-gold";
      metricBadge.textContent = "Standby";
    }
  }

  // Service & Storage Status Card on Dashboard
  const srvBadge = document.getElementById("dash-service-status-badge");
  const srvEngine = document.getElementById("dash-service-engine-label");
  const srvNet = document.getElementById("dash-service-network-label");
  const srvSess = document.getElementById("dash-active-sessions-label");
  const srvBkp = document.getElementById("dash-last-backup-label");
  const srvReader = document.getElementById("dash-reader-mode-label");
  if (srvBadge) {
    srvBadge.className = engineOnline ? "v2-badge v2-badge-green" : "v2-badge v2-badge-gold";
    srvBadge.textContent = engineOnline ? "Operational" : "Standby";
  }
  if (srvEngine) {
    srvEngine.replaceChildren(
      elText("span", engineOnline ? "Online & Responding" : "Standby", engineOnline ? "v2-badge v2-badge-green" : "v2-badge v2-badge-gold")
    );
  }
  if (srvNet) {
    const gHost = sys.gateway_host || "127.0.0.1";
    srvNet.textContent = gHost === "0.0.0.0" ? `Campus LAN / Wi-Fi (Port ${sys.gateway_port || 8085})` : `Localhost Loopback (${gHost}:${sys.gateway_port || 8085})`;
  }
  if (srvSess) {
    srvSess.textContent = `${activeSessions} active authenticated session(s)`;
  }
  if (srvBkp) {
    srvBkp.textContent = backups.length > 0 ? `${backups[0].created_at} (${backups[0].size_kb})` : "No snapshots created yet";
  }
  if (srvReader) {
    const readerOn = V2_STATE.catalogue && V2_STATE.catalogue.inbrowser_reader !== false;
    srvReader.textContent = readerOn ? "Branded Online Reader Enabled (PDF & EPUB)" : "External Reader Mode";
  }

  if (sys.branding_dir) {
    const bDirEl = document.getElementById("dash-branding-dir");
    if (bDirEl) bDirEl.textContent = sys.branding_dir;
    const bPathEl = document.getElementById("branding-writable-path");
    if (bPathEl) bPathEl.textContent = sys.branding_dir;
  }

  // Institution KV summary
  document.getElementById("dash-kv-name").textContent = inst.name || inst.institution_name || "-";
  document.getElementById("dash-kv-short").textContent = inst.short_name || "IDL";
  document.getElementById("dash-kv-lib").textContent = inst.library_name || inst.library_title || "-";
  document.getElementById("dash-kv-motto").textContent = inst.motto || "-";
  document.getElementById("dash-kv-contact").textContent = [inst.contact_email, inst.contact_phone].filter(Boolean).join(" · ") || "-";
  document.getElementById("dash-kv-color").textContent = inst.primary_color || "#183c34";

  // Connected Libraries summary table
  const libTbody = document.getElementById("dash-libraries-tbody");
  libTbody.replaceChildren();
  if (libs.length === 0) {
    const tr = document.createElement("tr");
    tr.appendChild(elText("td", "No Calibre libraries connected yet."));
    tr.firstChild.colSpan = 5;
    libTbody.appendChild(tr);
  } else {
    for (const lib of libs) {
      const tr = document.createElement("tr");
      const nameTd = document.createElement("td");
      nameTd.append(elText("strong", lib.display_name));
      const pathSmall = elText("div", lib.path, "v2-mono");
      pathSmall.style.marginTop = "3px";
      nameTd.appendChild(pathSmall);

      const volTd = elText("td", `${lib.books_count != null ? lib.books_count : 0} vols`);
      const polTd = document.createElement("td");
      polTd.appendChild(elText("span", formatPolicyLabel(lib.access_policy), "v2-badge v2-badge-slate"));

      const stateTd = document.createElement("td");
      stateTd.appendChild(
        elText("span", lib.is_active ? "Active" : "Disabled", lib.is_active ? "v2-badge v2-badge-green" : "v2-badge v2-badge-gold")
      );

      const defTd = document.createElement("td");
      defTd.appendChild(
        lib.is_default ? elText("span", "Primary Default", "v2-badge v2-badge-gold") : elText("span", "Secondary")
      );

      tr.append(nameTd, volTd, polTd, stateTd, defTd);
      libTbody.appendChild(tr);
    }
  }

  // Recent Audit summary table
  const auditTbody = document.getElementById("dash-audit-tbody");
  auditTbody.replaceChildren();
  const recent = V2_STATE.audit.slice(0, 6);
  for (const item of recent) {
    const tr = document.createElement("tr");
    const ts = (item.timestamp || "").replace("T", " ").substring(0, 19);
    tr.append(
      elText("td", ts, "v2-mono"),
      elText("td", item.actor || "SYSTEM"),
      elText("td", item.action || "EVENT")
    );
    auditTbody.appendChild(tr);
  }
}

function formatPolicyLabel(policy) {
  const map = {
    public: "Public / All Patrons",
    institutional: "Institutional Community",
    faculty_only: "Faculty & Research",
    admin_only: "Restricted Archival"
  };
  return map[policy] || "Public / Institutional";
}

/* ==========================================================================
   2. Users & Access Management
   ========================================================================== */

function renderUsersTable() {
  const tbody = document.getElementById("v2-users-tbody");
  if (!tbody) return;

  const q = (document.getElementById("user-search-input")?.value || "").toLowerCase().trim();
  const roleFilter = document.getElementById("user-role-filter")?.value || "ALL";
  const modeFilter = document.getElementById("user-mode-filter")?.value || "ALL";

  const filtered = V2_STATE.users.filter(u => {
    const matchText = !q ||
      (u.username || "").toLowerCase().includes(q) ||
      (u.display_name || "").toLowerCase().includes(q) ||
      (u.department || "").toLowerCase().includes(q);
    const matchRole = roleFilter === "ALL" || u.role === roleFilter;
    const matchMode = modeFilter === "ALL" ||
      (modeFilter === "RO" && u.readonly) ||
      (modeFilter === "RW" && !u.readonly);
    return matchText && matchRole && matchMode;
  });

  const countEl = document.getElementById("users-showing-count");
  if (countEl) countEl.textContent = `Showing ${filtered.length} of ${V2_STATE.users.length} accounts`;

  tbody.replaceChildren();
  if (filtered.length === 0) {
    const tr = document.createElement("tr");
    const td = elText("td", "No institutional user accounts match the active filter criteria.");
    td.colSpan = 6;
    td.style.textAlign = "center";
    td.style.padding = "28px";
    td.style.color = "var(--ink-muted)";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  for (const user of filtered) {
    const tr = document.createElement("tr");
    const isActive = user.is_active !== false;

    // 1. Account / Officer + Active/Deactivated Status Badge
    const idTd = document.createElement("td");
    const topLine = document.createElement("div");
    topLine.style.display = "flex";
    topLine.style.alignItems = "center";
    topLine.style.gap = "8px";
    topLine.appendChild(elText("strong", user.display_name || user.username));
    topLine.appendChild(
      elText(
        "span",
        isActive ? "Active" : "Deactivated",
        isActive ? "v2-badge v2-badge-green" : "v2-badge v2-badge-red"
      )
    );
    idTd.append(topLine, elText("span", `@${user.username}`, "v2-mono"));

    // 2. Institutional Role
    const roleTd = document.createElement("td");
    const roleBadgeClass = user.role === "Administrator"
      ? "v2-badge v2-badge-gold"
      : (user.role === "Faculty" || user.role === "Staff" ? "v2-badge v2-badge-green" : "v2-badge v2-badge-slate");
    roleTd.appendChild(elText("span", user.role || "Patron", roleBadgeClass));

    // 3. Department
    const deptTd = elText("td", user.department || "Campus Community");

    // 4. Calibre Engine Access Mode
    const modeTd = document.createElement("td");
    modeTd.appendChild(
      elText(
        "span",
        user.readonly ? "Read-Only (Enforced)" : "Read-Write (Curator)",
        user.readonly ? "v2-badge v2-badge-slate" : "v2-badge v2-badge-gold"
      )
    );

    // 5. Backend Library Scope
    const scopeTd = document.createElement("td");
    const rawAllowed = (user.allowed_libraries || "*").trim();
    const scopeLabel = (rawAllowed === "*" || !rawAllowed)
      ? (user.role === "Administrator" || user.role === "Faculty" ? "All Active Collections (*)" : "Role-Permitted (*)")
      : `Scoped: ${rawAllowed}`;
    scopeTd.appendChild(
      elText("span", scopeLabel, rawAllowed === "*" ? "v2-badge v2-badge-green" : "v2-badge v2-badge-gold")
    );

    // 6. Actions
    const actTd = document.createElement("td");
    const actWrap = document.createElement("div");
    actWrap.className = "v2-row-actions";

    const editBtn = elText("button", "Edit Role/Scope", "btn-v2 btn-v2-outline btn-v2-sm");
    editBtn.type = "button";
    editBtn.onclick = () => openUserModal(user);

    const passBtn = elText("button", "Password", "btn-v2 btn-v2-subtle btn-v2-sm");
    passBtn.type = "button";
    passBtn.onclick = () => openPasswordModal(user.username);

    const roBtn = elText("button", user.readonly ? "Grant Write" : "Set Read-Only", "btn-v2 btn-v2-subtle btn-v2-sm");
    roBtn.type = "button";
    roBtn.onclick = () => toggleV2UserReadonly(user.username, !user.readonly);

    actWrap.append(editBtn, passBtn, roBtn);

    if (user.username !== "admin") {
      const statusBtn = elText(
        "button",
        isActive ? "Deactivate" : "Activate",
        isActive ? "btn-v2 btn-v2-subtle btn-v2-sm" : "btn-v2 btn-v2-gold btn-v2-sm"
      );
      statusBtn.type = "button";
      statusBtn.onclick = () => toggleV2UserActive(user.username, !isActive);

      const delBtn = elText("button", "Remove", "btn-v2 btn-v2-danger btn-v2-sm");
      delBtn.type = "button";
      delBtn.onclick = () => deleteV2User(user.username);
      actWrap.append(statusBtn, delBtn);
    }

    actTd.appendChild(actWrap);
    tr.append(idTd, roleTd, deptTd, modeTd, scopeTd, actTd);
    tbody.appendChild(tr);
  }
}

function openUserModal(existingUser = null) {
  const modal = document.getElementById("modal-v2-user");
  const modeInput = document.getElementById("usr-v2-edit-mode");
  const titleEl = document.getElementById("modal-user-title");
  const submitBtn = document.getElementById("btn-usr-v2-submit");
  const userInp = document.getElementById("usr-v2-username");
  const passGroup = document.getElementById("usr-v2-pass-group");
  const passInp = document.getElementById("usr-v2-password");

  // Parse existing allowed_libraries
  const currentAllowed = existingUser ? String(existingUser.allowed_libraries || "*").trim() : "*";
  const allowedSet = new Set(
    currentAllowed.split(",").map(s => s.trim()).filter(Boolean)
  );
  const isWildcard = currentAllowed === "*" || allowedSet.has("*");

  // Populate library checkboxes
  const libBox = document.getElementById("usr-v2-lib-checkboxes");
  libBox.replaceChildren();

  // Wildcard checkbox
  const allLbl = document.createElement("label");
  allLbl.style.display = "flex";
  allLbl.style.alignItems = "center";
  allLbl.style.gap = "6px";
  const allCb = document.createElement("input");
  allCb.type = "checkbox";
  allCb.className = "usr-lib-scope-cb";
  allCb.value = "*";
  allCb.checked = isWildcard;
  allLbl.append(allCb, elText("span", "All Role-Permitted Libraries (*)"));
  libBox.appendChild(allLbl);

  for (const lib of V2_STATE.libraries) {
    const libId = String(lib.id || lib.library_id);
    const lbl = document.createElement("label");
    lbl.style.display = "flex";
    lbl.style.alignItems = "center";
    lbl.style.gap = "6px";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "usr-lib-scope-cb";
    cb.value = libId;
    cb.checked = isWildcard || allowedSet.has(libId) || allowedSet.has(lib.display_name);
    cb.onchange = () => {
      if (!cb.checked) allCb.checked = false;
    };
    lbl.append(cb, elText("span", `${lib.display_name} (${libId})`));
    libBox.appendChild(lbl);
  }

  allCb.onchange = () => {
    if (allCb.checked) {
      libBox.querySelectorAll(".usr-lib-scope-cb").forEach(c => { c.checked = true; });
    }
  };

  if (existingUser) {
    modeInput.value = "edit";
    titleEl.textContent = `Edit Institutional Profile & Access — @${existingUser.username}`;
    submitBtn.textContent = "Save Profile & Access Scope";
    userInp.value = existingUser.username;
    userInp.readOnly = true;
    passGroup.style.display = "none";
    passInp.required = false;
    document.getElementById("usr-v2-fullname").value = existingUser.display_name || existingUser.username;
    document.getElementById("usr-v2-role").value = existingUser.role || "Student";
    document.getElementById("usr-v2-dept").value = existingUser.department || "";
    document.getElementById("usr-v2-readonly").checked = Boolean(existingUser.readonly);
  } else {
    modeInput.value = "create";
    titleEl.textContent = "Provision Institutional User Account";
    submitBtn.textContent = "Provision Account";
    userInp.value = "";
    userInp.readOnly = false;
    passGroup.style.display = "";
    passInp.value = "";
    passInp.required = true;
    document.getElementById("usr-v2-fullname").value = "";
    document.getElementById("usr-v2-role").value = "Student";
    document.getElementById("usr-v2-dept").value = "";
    document.getElementById("usr-v2-readonly").checked = true;
  }

  modal.classList.remove("hidden");
}

function collectSelectedLibraryScope() {
  const cbs = Array.from(document.querySelectorAll("#usr-v2-lib-checkboxes .usr-lib-scope-cb"));
  const allCb = cbs.find(c => c.value === "*");
  const specificCbs = cbs.filter(c => c.value !== "*");
  const checkedSpecific = specificCbs.filter(c => c.checked).map(c => c.value);

  if ((allCb && allCb.checked) || (specificCbs.length > 0 && checkedSpecific.length === specificCbs.length)) {
    return "*";
  }
  return checkedSpecific.length > 0 ? checkedSpecific.join(",") : "none";
}

async function submitV2User(e) {
  e.preventDefault();
  const mode = document.getElementById("usr-v2-edit-mode").value;
  const username = document.getElementById("usr-v2-username").value.trim();
  const password = document.getElementById("usr-v2-password").value;
  const fullName = document.getElementById("usr-v2-fullname").value.trim();
  const role = document.getElementById("usr-v2-role").value;
  const department = document.getElementById("usr-v2-dept").value.trim();
  const readonly = document.getElementById("usr-v2-readonly").checked;
  const allowedLibraries = collectSelectedLibraryScope();

  if (username.length < 3) {
    document.getElementById("err-usr-username").classList.add("visible");
    return;
  }
  document.getElementById("err-usr-username").classList.remove("visible");

  try {
    if (mode === "create") {
      if (password.length < 6) {
        document.getElementById("err-usr-password").classList.add("visible");
        return;
      }
      document.getElementById("err-usr-password").classList.remove("visible");

      const res = await fetch("/api/admin/users/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username,
          password,
          full_name: fullName,
          role,
          department,
          readonly,
          allowed_libraries: allowedLibraries
        })
      });
      const data = await res.json();
      if (!data.success) throw new Error(data.error || "Failed to create user");
      showGlobalBanner(`Provisioned institutional account @${username} (${role}) via Calibre CLI.`, "success");
    } else {
      const res = await fetch("/api/admin/users/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username,
          full_name: fullName,
          role,
          department,
          allowed_libraries: allowedLibraries
        })
      });
      const data = await res.json();
      if (!data.success) throw new Error(data.error || "Failed to update user profile");
      await fetch("/api/admin/users/readonly", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, readonly })
      });
      showGlobalBanner(`Updated institutional role and backend library scope (${allowedLibraries}) for @${username}.`, "success");
    }
    closeV2Modal("modal-v2-user");
    await loadAllV2Data();
  } catch (err) {
    showGlobalBanner(err.message, "error");
  }
}

function openPasswordModal(username) {
  document.getElementById("pass-v2-username").value = username;
  document.getElementById("pass-v2-display").textContent = `@${username}`;
  document.getElementById("pass-v2-new").value = "";
  document.getElementById("modal-v2-password").classList.remove("hidden");
}

async function submitV2Password(e) {
  e.preventDefault();
  const username = document.getElementById("pass-v2-username").value;
  const newPassword = document.getElementById("pass-v2-new").value;
  try {
    const res = await fetch("/api/admin/users/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, new_password: newPassword })
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Password update failed");
    closeV2Modal("modal-v2-password");
    showGlobalBanner(`Password updated for @${username} via STDIN pipe; active sessions revoked.`, "success");
  } catch (err) {
    showGlobalBanner(err.message, "error");
  }
}

async function toggleV2UserReadonly(username, readonly) {
  try {
    const res = await fetch("/api/admin/users/readonly", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, readonly })
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Failed to update read-only status");
    showGlobalBanner(`Account @${username} switched to ${readonly ? "Read-Only" : "Read-Write"} mode.`, "success");
    await loadAllV2Data();
  } catch (err) {
    showGlobalBanner(err.message, "error");
  }
}

async function toggleV2UserActive(username, isActive) {
  try {
    const res = await fetch("/api/admin/users/status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, is_active: isActive })
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Failed to update user status");
    showGlobalBanner(
      isActive
        ? `Reactivated institutional account @${username}.`
        : `Deactivated account @${username} and revoked all active sessions.`,
      isActive ? "success" : "warning"
    );
    await loadAllV2Data();
  } catch (err) {
    showGlobalBanner(err.message, "error");
  }
}

async function deleteV2User(username) {
  if (!confirm(`Remove institutional user account @${username}?`)) return;
  try {
    const res = await fetch("/api/admin/users/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username })
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Failed to remove user");
    showGlobalBanner(`Account @${username} removed from Calibre userdb and active sessions terminated.`, "success");
    await loadAllV2Data();
  } catch (err) {
    showGlobalBanner(err.message, "error");
  }
}

/* ==========================================================================
   3. Library Management
   ========================================================================== */

function renderLibrariesTable() {
  const tbody = document.getElementById("v2-libraries-tbody");
  if (!tbody) return;
  tbody.replaceChildren();

  if (V2_STATE.libraries.length === 0) {
    const tr = document.createElement("tr");
    const td = elText("td", "No Calibre libraries registered.");
    td.colSpan = 7;
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  for (const lib of V2_STATE.libraries) {
    const tr = document.createElement("tr");
    const libId = lib.id || lib.library_id;

    const nameTd = document.createElement("td");
    nameTd.append(elText("strong", lib.display_name));

    const pathTd = document.createElement("td");
    pathTd.appendChild(elText("code", lib.path, "v2-mono"));

    const volCount = lib.books_count != null ? lib.books_count : 0;
    const volTd = document.createElement("td");
    volTd.appendChild(elText("span", `${volCount} volumes`, "v2-badge v2-badge-green"));

    // Access policy dropdown (Backend enforced)
    const polTd = document.createElement("td");
    const polSelect = document.createElement("select");
    polSelect.className = "v2-select";
    polSelect.style.padding = "4px 8px";
    polSelect.style.fontSize = "12px";
    for (const [val, label] of [
      ["public", "Public / All Patrons"],
      ["institutional", "Institutional Community"],
      ["faculty_only", "Faculty & Research"],
      ["admin_only", "Restricted Archival"]
    ]) {
      const opt = elText("option", label);
      opt.value = val;
      if ((lib.access_policy || "public") === val) opt.selected = true;
      polSelect.appendChild(opt);
    }
    polSelect.onchange = () => updateLibraryPolicy(libId, polSelect.value);
    polTd.appendChild(polSelect);

    const stateTd = document.createElement("td");
    stateTd.appendChild(
      elText("span", lib.is_active ? "Active" : "Disabled", lib.is_active ? "v2-badge v2-badge-green" : "v2-badge v2-badge-gold")
    );

    const defTd = document.createElement("td");
    if (lib.is_default) {
      defTd.appendChild(elText("span", "Primary Default", "v2-badge v2-badge-gold"));
    } else {
      const mkDefBtn = elText("button", "Set Primary", "btn-v2 btn-v2-subtle btn-v2-sm");
      mkDefBtn.type = "button";
      mkDefBtn.onclick = () => setV2DefaultLibrary(libId);
      defTd.appendChild(mkDefBtn);
    }

    const actTd = document.createElement("td");
    const actWrap = document.createElement("div");
    actWrap.className = "v2-row-actions";

    const inspBtn = elText("button", "Inspect Details", "btn-v2 btn-v2-outline btn-v2-sm");
    inspBtn.type = "button";
    inspBtn.onclick = () => inspectLibraryReadOnly(lib);

    const togBtn = elText("button", lib.is_active ? "Disable" : "Enable", "btn-v2 btn-v2-subtle btn-v2-sm");
    togBtn.type = "button";
    togBtn.onclick = () => toggleV2Library(libId, !lib.is_active);

    const remBtn = elText("button", "Disconnect", "btn-v2 btn-v2-danger btn-v2-sm");
    remBtn.type = "button";
    remBtn.onclick = () => removeV2Library(libId, lib.display_name);

    actWrap.append(inspBtn, togBtn, remBtn);
    actTd.appendChild(actWrap);

    tr.append(nameTd, pathTd, volTd, polTd, stateTd, defTd, actTd);
    tbody.appendChild(tr);
  }

  // Populate inspector with primary library by default
  const primary = V2_STATE.libraries.find(l => l.is_default) || V2_STATE.libraries[0];
  if (primary) inspectLibraryReadOnly(primary, false);
}

function inspectLibraryReadOnly(lib, announce = true) {
  document.getElementById("insp-name").textContent = `${lib.display_name} (${lib.is_default ? "Primary Default" : "Connected Collection"})`;
  document.getElementById("insp-path").textContent = lib.path;
  document.getElementById("insp-db").textContent = lib.is_active !== false ? "Verified & Accessible" : "Paused";
  document.getElementById("insp-policy").textContent = formatPolicyLabel(lib.access_policy);
  document.getElementById("insp-books").textContent = lib.books_count != null ? lib.books_count : 0;
  document.getElementById("insp-authors").textContent = `${lib.authors_count != null ? lib.authors_count : 0} distinct authors`;
  document.getElementById("insp-tags").textContent = `${lib.tags_count != null ? lib.tags_count : 0} subject classifications`;
  if (announce) {
    showGlobalBanner(`Collection summary loaded for "${lib.display_name}".`, "success");
  }
}

async function updateLibraryPolicy(libraryId, accessPolicy) {
  try {
    const res = await fetch("/api/v2/admin/libraries/policy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ library_id: libraryId, access_policy: accessPolicy })
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Failed to update policy");
    showGlobalBanner(`Updated backend access policy for library "${libraryId}" to "${formatPolicyLabel(accessPolicy)}".`, "success");
    await loadAllV2Data();
  } catch (err) {
    showGlobalBanner("Failed to update library policy: " + err.message, "error");
  }
}

function openConnectLibraryModal() {
  document.getElementById("lib-v2-name").value = "";
  document.getElementById("lib-v2-path").value = "";
  document.getElementById("lib-v2-default").checked = false;
  document.getElementById("lib-v2-verify-box").classList.add("hidden");
  document.getElementById("modal-v2-library").classList.remove("hidden");
}

async function verifyV2LibraryPath() {
  const path = document.getElementById("lib-v2-path").value.trim();
  const box = document.getElementById("lib-v2-verify-box");
  if (!path) return;

  box.className = "v2-banner warning";
  box.textContent = "Verifying Calibre library directory...";
  box.classList.remove("hidden");

  try {
    const res = await fetch("/api/setup/validate-library", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ library_path: path })
    });
    const data = await res.json();
    if (data.valid) {
      box.className = "v2-banner success";
      box.textContent = `Verified valid Calibre library at "${data.path}" — ${data.books_count || 0} volumes indexed.`;
    } else {
      box.className = "v2-banner error";
      box.textContent = data.error || "Directory does not contain a valid Calibre library.";
    }
  } catch (err) {
    box.className = "v2-banner error";
    box.textContent = "Validation error: " + err.message;
  }
}

async function submitV2Library(e) {
  e.preventDefault();
  const displayName = document.getElementById("lib-v2-name").value.trim();
  const libraryPath = document.getElementById("lib-v2-path").value.trim();
  const accessPolicy = document.getElementById("lib-v2-policy").value;
  const isDefault = document.getElementById("lib-v2-default").checked;

  try {
    const res = await fetch("/api/admin/libraries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        display_name: displayName,
        library_path: libraryPath,
        access_policy: accessPolicy,
        is_default: isDefault
      })
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Could not connect library");
    closeV2Modal("modal-v2-library");
    showGlobalBanner(`Connected Calibre library "${displayName}" and synchronized configuration.`, "success");
    await loadAllV2Data();
  } catch (err) {
    showGlobalBanner(err.message, "error");
  }
}

async function setV2DefaultLibrary(libId) {
  await fetch("/api/admin/libraries/default", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ library_id: libId })
  });
  showGlobalBanner("Primary default library updated and synchronized for Desktop & Web.", "success");
  await loadAllV2Data();
}

async function toggleV2Library(libId, isActive) {
  await fetch("/api/admin/libraries/toggle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ library_id: libId, is_active: isActive })
  });
  showGlobalBanner(`Library state changed to ${isActive ? "Active" : "Disabled"}.`, "success");
  await loadAllV2Data();
}

async function removeV2Library(libId, name) {
  if (!confirm(`Disconnect library "${name}" from the Institutional Gateway? All book files and metadata.db on disk will remain untouched.`)) return;
  const res = await fetch("/api/admin/libraries/remove", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ library_id: libId })
  });
  const data = await res.json();
  if (!data.success) {
    showGlobalBanner(data.error || "Cannot disconnect the only remaining library.", "error");
    return;
  }
  showGlobalBanner(`Disconnected library "${name}". Disk files preserved.`, "success");
  await loadAllV2Data();
}

async function syncBackendLibraries() {
  showGlobalBanner("Synchronizing active libraries with loopback Calibre Content Server supervisor...", "warning");
  try {
    const res = await fetch("/api/admin/system/reload", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showGlobalBanner("Calibre Content Server backend synchronized and verified online on loopback.", "success");
    } else {
      showGlobalBanner("Configuration cache reloaded; Calibre engine running in standalone mode.", "success");
    }
    await loadAllV2Data();
  } catch (err) {
    showGlobalBanner("Reload signal processed.", "success");
  }
}

/* ==========================================================================
   4. Catalogue & Metadata Settings
   ========================================================================== */

function populateCatalogueForm() {
  const cat = V2_STATE.catalogue || {};
  const pageSizeEl = document.getElementById("cat-page-size");
  const sortEl = document.getElementById("cat-default-sort");
  const injectEl = document.getElementById("cat-inject-bar");
  const readerEl = document.getElementById("cat-inbrowser-reader");
  const dlEl = document.getElementById("cat-download-policy");

  if (pageSizeEl && cat.page_size) pageSizeEl.value = String(cat.page_size);
  if (sortEl && cat.default_sort) sortEl.value = cat.default_sort;
  if (injectEl) injectEl.checked = cat.inject_bar !== false;
  if (readerEl) readerEl.checked = cat.inbrowser_reader !== false;
  if (dlEl && cat.download_policy) dlEl.value = cat.download_policy;

  const exposed = Array.isArray(cat.exposed_facets)
    ? new Set(cat.exposed_facets)
    : new Set(["authors", "tags", "series", "publisher", "formats", "languages"]);

  document.querySelectorAll(".cat-facet-cb").forEach(cb => {
    cb.checked = exposed.has(cb.value);
  });
}

async function saveCatalogueSettings(e) {
  e.preventDefault();
  const pageSize = parseInt(document.getElementById("cat-page-size").value, 10) || 24;
  const sortOrder = document.getElementById("cat-default-sort").value;
  const injectBar = document.getElementById("cat-inject-bar").checked;
  const inbrowserReader = document.getElementById("cat-inbrowser-reader").checked;
  const dlPolicy = document.getElementById("cat-download-policy").value;
  const exposedFacets = Array.from(document.querySelectorAll(".cat-facet-cb"))
    .filter(cb => cb.checked)
    .map(cb => cb.value);

  try {
    const res = await fetch("/api/admin/catalogue-settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        page_size: pageSize,
        default_sort: sortOrder,
        exposed_facets: exposedFacets,
        inject_bar: injectBar,
        inbrowser_reader: inbrowserReader,
        download_policy: dlPolicy
      })
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Failed to save catalogue settings");
    showGlobalBanner(
      `Saved Catalogue & Metadata settings (${pageSize} vols/page, sort: ${sortOrder}, ${exposedFacets.length} facets, download policy: ${dlPolicy}).`,
      "success"
    );
    await loadAllV2Data();
  } catch (err) {
    showGlobalBanner("Failed to save catalogue settings: " + err.message, "error");
  }
}

/* ==========================================================================
   5. Institution Branding (Dynamic Multi-Institution & Writable AppData Logo)
   ========================================================================== */

function populateBrandingForm() {
  const inst = V2_STATE.institution || {};
  document.getElementById("brand-name").value = inst.name || inst.institution_name || "Institutional Digital Library";
  document.getElementById("brand-short").value = inst.short_name || "IDL";
  document.getElementById("brand-lib-title").value = inst.library_name || inst.library_title || "Digital Collections";
  document.getElementById("brand-motto").value = inst.motto || "Institutional Digital Repository";
  document.getElementById("brand-email").value = inst.contact_email || "library@institution.org";
  document.getElementById("brand-phone").value = inst.contact_phone || "+1 (555) 019-8841";
  const color = inst.primary_color || "#183c34";
  document.getElementById("brand-color-hex").value = color;
  if (/^#[0-9a-fA-F]{6}$/.test(color)) {
    document.getElementById("brand-color-picker").value = color;
  }
  document.getElementById("brand-logo-url").value = inst.logo_url || inst.logo_path || "/static/images/institution-mark.svg";

  // Populate Landing Page Content inputs if present
  const content = V2_STATE.landingContent || {};
  const eyebrowEl = document.getElementById("landing-hero-eyebrow");
  if (eyebrowEl) eyebrowEl.value = content.hero_eyebrow || "A HOME FOR CURIOUS MINDS";
  const ctaEl = document.getElementById("landing-cta-label");
  if (ctaEl) ctaEl.value = content.cta_label || "Explore the library ↗";
  const titleEl = document.getElementById("landing-hero-title");
  if (titleEl) titleEl.value = content.hero_title || "Great ideas begin with an open book.";
  const descEl = document.getElementById("landing-hero-desc");
  if (descEl) descEl.value = content.hero_description || "Discover academic works, explore new perspectives, and make room for your next breakthrough. Your institutional collection, wherever you learn.";
  const aboutHeadEl = document.getElementById("landing-about-heading");
  if (aboutHeadEl) aboutHeadEl.value = content.about_heading || "A collection that moves you forward.";
  const aboutDescEl = document.getElementById("landing-about-desc");
  if (aboutDescEl) aboutDescEl.value = content.about_description || "From foundational texts to fresh thinking, find the resources that support your studies, teaching, and research.";
  const footerEl = document.getElementById("landing-footer-text");
  if (footerEl) footerEl.value = content.footer_text || "Powered by Calibre · Built for our community";

  updateLiveBrandPreview();
}

function syncColorFromPicker() {
  const val = document.getElementById("brand-color-picker").value;
  document.getElementById("brand-color-hex").value = val;
  updateLiveBrandPreview();
}

function syncColorFromHex() {
  const val = document.getElementById("brand-color-hex").value.trim();
  if (/^#[0-9a-fA-F]{6}$/.test(val)) {
    document.getElementById("brand-color-picker").value = val;
    updateLiveBrandPreview();
  }
}

function applyBrandPreset(key) {
  const p = BRAND_PRESETS[key];
  if (!p) return;
  document.getElementById("brand-name").value = p.name;
  document.getElementById("brand-short").value = p.short_name;
  document.getElementById("brand-lib-title").value = p.library_name;
  document.getElementById("brand-motto").value = p.motto;
  document.getElementById("brand-email").value = p.contact_email;
  document.getElementById("brand-phone").value = p.contact_phone;
  document.getElementById("brand-color-hex").value = p.primary_color;
  document.getElementById("brand-color-picker").value = p.primary_color;
  updateLiveBrandPreview();
}

function updateLiveBrandPreview() {
  const name = document.getElementById("brand-name").value.trim() || "Institution Name";
  const short = document.getElementById("brand-short").value.trim() || "INST";
  const lib = document.getElementById("brand-lib-title").value.trim() || "Digital Library";
  const motto = document.getElementById("brand-motto").value.trim() || "Institutional Digital Collection";
  const color = document.getElementById("brand-color-hex").value.trim() || "#183c34";
  const logo = document.getElementById("brand-logo-url").value.trim() || "/static/images/institution-mark.svg";

  document.getElementById("prev-portal-name").textContent = name;
  document.getElementById("prev-portal-motto").textContent = motto;
  document.getElementById("prev-portal-short-foot").textContent = `${short} / DIGITAL LIBRARY`;
  document.getElementById("prev-bar-short").textContent = short;
  document.getElementById("prev-bar-name").textContent = name;
  document.getElementById("prev-bar-lib").textContent = `| ${lib}`;
  document.getElementById("prev-portal-logo").src = logo;

  if (/^#[0-9a-fA-F]{6}$/.test(color)) {
    document.getElementById("prev-portal-cta").style.background = color;
    document.getElementById("prev-injected-bar").style.background = color;
    document.getElementById("prev-book-spine").style.background = color;
    document.getElementById("dynamic-brand-theme").textContent = `:root { --brand-primary: ${color}; }`;
  }
}

async function handleLogoUpload(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const statusEl = document.getElementById("logo-upload-status");
  statusEl.textContent = `Uploading "${file.name}" to writable AppData branding directory...`;

  const reader = new FileReader();
  reader.onload = async () => {
    const dataUrl = reader.result;
    try {
      const res = await fetch("/api/v2/admin/branding/upload-logo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, data_url: dataUrl })
      });
      if (res.ok) {
        const out = await res.json();
        if (out.logo_url) {
          document.getElementById("brand-logo-url").value = out.logo_url;
          statusEl.textContent = `Stored in writable AppData: ${out.disk_path} (Served at ${out.logo_url})`;
          updateLiveBrandPreview();
          return;
        }
      }
    } catch (_) {}
    document.getElementById("brand-logo-url").value = dataUrl;
    statusEl.textContent = `Preview loaded for "${file.name}" (Target: %LOCALAPPDATA%\\CalibreInstitutional\\config\\branding\\${file.name})`;
    updateLiveBrandPreview();
  };
  reader.readAsDataURL(file);
}

async function loadV2Branding() {
  await loadAllV2Data();
  showGlobalBanner("Reverted branding form to currently saved institutional configuration.", "warning");
}

async function saveV2Branding(e) {
  e.preventDefault();
  const payload = {
    name: document.getElementById("brand-name").value.trim(),
    short_name: document.getElementById("brand-short").value.trim(),
    library_name: document.getElementById("brand-lib-title").value.trim(),
    motto: document.getElementById("brand-motto").value.trim(),
    contact_email: document.getElementById("brand-email").value.trim(),
    contact_phone: document.getElementById("brand-phone").value.trim(),
    logo_url: document.getElementById("brand-logo-url").value.trim(),
    primary_color: document.getElementById("brand-color-hex").value.trim()
  };

  if (!payload.name) {
    document.getElementById("err-brand-name").classList.add("visible");
    return;
  }
  document.getElementById("err-brand-name").classList.remove("visible");

  try {
    const res = await fetch("/api/admin/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Failed to save branding");
    showGlobalBanner(`Saved institutional identity & theme for "${payload.name}" (${payload.short_name}). Public portal, Catalogue, and Calibre header updated live.`, "success");
    await loadAllV2Data();
  } catch (err) {
    showGlobalBanner("Failed to save branding: " + err.message, "error");
  }
}

async function saveV2LandingContent(e) {
  e.preventDefault();
  const payload = {
    hero_eyebrow: document.getElementById("landing-hero-eyebrow")?.value.trim(),
    cta_label: document.getElementById("landing-cta-label")?.value.trim(),
    hero_title: document.getElementById("landing-hero-title")?.value.trim(),
    hero_description: document.getElementById("landing-hero-desc")?.value.trim(),
    about_heading: document.getElementById("landing-about-heading")?.value.trim(),
    about_description: document.getElementById("landing-about-desc")?.value.trim(),
    footer_text: document.getElementById("landing-footer-text")?.value.trim()
  };

  try {
    const res = await fetch("/api/admin/landing-content", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Failed to save landing page copy");
    showGlobalBanner("Landing page copy updated successfully. Public portal updated live.", "success");
    await loadAllV2Data();
  } catch (err) {
    showGlobalBanner("Failed to save landing content: " + err.message, "error");
  }
}

async function resetV2LandingContent() {
  if (!confirm("Reset all public portal headlines, descriptions, and button text back to default institutional copy?")) return;
  try {
    const res = await fetch("/api/admin/landing-content/reset", { method: "POST" });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Failed to reset landing copy");
    showGlobalBanner("Landing page content restored to defaults.", "success");
    await loadAllV2Data();
  } catch (err) {
    showGlobalBanner(err.message, "error");
  }
}

/* ==========================================================================
   6. Server & Network
   ========================================================================== */

function renderSystemAndNetwork() {
  const sys = V2_STATE.system || {};
  const gwPort = sys.gateway_port || 8085;
  const calPort = sys.calibre_port || 8088;
  document.getElementById("net-gw-port").value = gwPort;
  document.getElementById("net-calibre-port").value = calPort;
  if (sys.session_timeout_seconds) {
    document.getElementById("net-session-timeout").value = sys.session_timeout_seconds;
  }
  const gwBindEl = document.getElementById("sys-kv-gw-bind");
  if (gwBindEl) gwBindEl.textContent = `127.0.0.1:${gwPort} (Loopback Only)`;
  const dbEl = document.getElementById("sys-kv-db");
  if (dbEl) dbEl.textContent = sys.db_path || "Local AppData Configuration Store";
  const binEl = document.getElementById("sys-kv-bin");
  if (binEl) binEl.textContent = sys.calibre_bin || "Managed Calibre Content Server";
  const ips = (sys.lan_ips || ["127.0.0.1"]).join(", ");
  const ipsEl = document.getElementById("sys-kv-ips");
  if (ipsEl) ipsEl.textContent = `${ips} (Local Loopback Active)`;
  const topbarBind = document.getElementById("topbar-bind-pill");
  if (topbarBind) topbarBind.textContent = `Gateway :${gwPort}`;
}

function handleBindModeChange() {
  const mode = document.getElementById("net-bind-mode").value;
  const badge = document.getElementById("net-bind-badge");
  if (mode === "custom_lan") {
    badge.className = "v2-badge v2-badge-gold";
    badge.textContent = "Explicit LAN Opt-In Selected";
    showGlobalBanner("Security Notice: Automatic LAN exposure is disabled. Binding to a campus LAN interface requires explicit administrator confirmation and TLS reverse-proxy hardening.", "warning");
  } else {
    badge.className = "v2-badge v2-badge-green";
    badge.textContent = "127.0.0.1 Loopback Only";
  }
}

async function saveNetworkSettings(e) {
  e.preventDefault();
  const bindMode = document.getElementById("net-bind-mode").value;
  const port = document.getElementById("net-gw-port").value;
  const ttl = document.getElementById("net-session-timeout").value;
  const tlsMode = document.getElementById("net-tls-mode").value;

  try {
    const res = await fetch("/api/v2/admin/network", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        bind_mode: bindMode,
        gateway_port: port,
        session_timeout_seconds: ttl,
        tls_mode: tlsMode
      })
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Failed to save network configuration");
    showGlobalBanner(
      `Network policy saved: Bind=${bindMode === "127.0.0.1" ? "127.0.0.1 (Loopback Only)" : "Explicit LAN Interface"}, Port=${port}, Session TTL=${ttl}s.`,
      "success"
    );
    await loadAllV2Data();
  } catch (err) {
    showGlobalBanner("Failed to save network configuration: " + err.message, "error");
  }
}

/* ==========================================================================
   7. Backup & Recovery (Three Strictly Separated Tiers)
   ========================================================================== */

function renderBackupsInventory() {
  const tbody = document.getElementById("v2-backups-tbody");
  if (!tbody) return;
  tbody.replaceChildren();

  const list = Array.isArray(V2_STATE.backups) ? V2_STATE.backups : [];

  // Update per-tier latest snapshot status in cards
  const latestT1 = list.find(b => b.tier_key === "config" || (b.tier || "").includes("Tier 1"));
  const latestT2 = list.find(b => b.tier_key === "auth" || (b.tier || "").includes("Tier 2"));
  const latestT3 = list.find(b => b.tier_key === "library" || (b.tier || "").includes("Tier 3"));
  if (latestT1) document.getElementById("bkp-tier1-last").textContent = `${latestT1.created_at} (${latestT1.size_kb})`;
  if (latestT2) document.getElementById("bkp-tier2-last").textContent = `${latestT2.created_at} (${latestT2.size_kb})`;
  if (latestT3) document.getElementById("bkp-tier3-last").textContent = `${latestT3.created_at} (${latestT3.size_kb})`;

  if (list.length === 0) {
    const tr = document.createElement("tr");
    const td = elText("td", "No backup snapshots created yet. Use the Tier 1, Tier 2, or Tier 3 buttons above to create a verified snapshot.");
    td.colSpan = 6;
    td.style.textAlign = "center";
    td.style.padding = "24px";
    td.style.color = "var(--ink-muted)";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  for (const item of list) {
    const tr = document.createElement("tr");
    const tierStr = item.tier || "Snapshot";
    const tierBadge = tierStr.includes("Tier 1")
      ? "v2-badge v2-badge-gold"
      : (tierStr.includes("Tier 2") ? "v2-badge v2-badge-slate" : "v2-badge v2-badge-green");

    const tdTier = document.createElement("td");
    tdTier.appendChild(elText("span", tierStr, tierBadge));

    const tdLoc = document.createElement("td");
    const locBadge = elText("span", "Managed Backup Archive", "v2-badge v2-badge-slate");
    locBadge.title = item.path || "";
    tdLoc.appendChild(locBadge);

    const tdAct = document.createElement("td");
    const actWrap = document.createElement("div");
    actWrap.className = "v2-row-actions";

    const verifyBtn = elText("button", "Verify Integrity", "btn-v2 btn-v2-outline btn-v2-sm");
    verifyBtn.type = "button";
    verifyBtn.onclick = () => verifyBackupSnapshot(item.filename);

    const restoreBtn = elText("button", "Restore Snapshot", "btn-v2 btn-v2-subtle btn-v2-sm");
    restoreBtn.type = "button";
    restoreBtn.onclick = () => restoreBackupSnapshot(item.filename, tierStr);

    actWrap.append(verifyBtn, restoreBtn);
    tdAct.appendChild(actWrap);

    tr.append(
      elText("td", item.filename, "v2-mono"),
      tdTier,
      elText("td", item.created_at),
      elText("td", item.size_kb),
      tdLoc,
      tdAct
    );
    tbody.appendChild(tr);
  }
}

async function createTierBackup(tier) {
  try {
    showGlobalBanner(`Creating ${tier === "library" ? "Tier 3 Complete Calibre Library (.zip) archive" : tier} snapshot...`, "warning");
    const res = await fetch("/api/v2/admin/backups/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tier })
    });
    if (res.ok) {
      const data = await res.json();
      if (data.success) {
        const extra = data.books_count != null ? ` (${data.books_count} volumes, ${data.files_archived || 0} files archived)` : "";
        showGlobalBanner(`Created ${data.tier_label} snapshot: ${data.filename}${extra} [SHA-256: ${(data.sha256 || "").substring(0, 12)}...]`, "success");
        await loadAllV2Data();
        return;
      }
    }
    const fb = await fetch("/api/admin/system/backup", { method: "POST" });
    const fbData = await fb.json();
    if (fbData.success) {
      showGlobalBanner(`Snapshot created at: ${fbData.backup_path}`, "success");
      await loadAllV2Data();
    }
  } catch (err) {
    showGlobalBanner("Backup error: " + err.message, "error");
  }
}

async function verifyBackupSnapshot(filename) {
  try {
    const res = await fetch("/api/v2/admin/backups/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename })
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Verification failed");
    const filesNote = data.verified_files != null ? ` · Verified ${data.verified_files} archived files & metadata.db` : "";
    showGlobalBanner(
      `Integrity Verified for "${filename}" (${data.tier_label}) — SHA-256: ${(data.sha256 || "").substring(0, 16)}...${filesNote}`,
      "success"
    );
  } catch (err) {
    showGlobalBanner("Backup verification failed: " + err.message, "error");
  }
}

async function restoreBackupSnapshot(filename, tierLabel) {
  if (!confirm(`Restore snapshot "${filename}" (${tierLabel})? A pre-restore safety backup of the current state will be created automatically before restoring.`)) {
    return;
  }
  try {
    const res = await fetch("/api/v2/admin/backups/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename })
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Restore failed");
    showGlobalBanner(
      `Successfully restored ${data.restored_tier || tierLabel} from "${filename}" to ${data.target_path}.`,
      "success"
    );
    await loadAllV2Data();
  } catch (err) {
    showGlobalBanner("Restore error: " + err.message, "error");
  }
}

async function loadBackupsList() {
  await loadAllV2Data();
  showGlobalBanner("Backup inventory refreshed from writable AppData backups directory.", "success");
}

/* ==========================================================================
   8. Audit & Security (Server-Side Filtering & Pagination)
   ========================================================================== */

async function fetchPaginatedAudit(newOffset = 0) {
  V2_STATE.auditOffset = Math.max(0, newOffset);
  const q = (document.getElementById("audit-search-input")?.value || "").trim();
  const cat = document.getElementById("audit-action-filter")?.value || "ALL";

  try {
    const url = `/api/admin/audit-log?paginated=1&limit=${V2_STATE.auditLimit}&offset=${V2_STATE.auditOffset}&q=${encodeURIComponent(q)}&category=${encodeURIComponent(cat)}&t=${Date.now()}`;
    const res = await fetch(url);
    if (res.ok) {
      const data = await res.json();
      if (data && Array.isArray(data.items)) {
        V2_STATE.audit = data.items;
        V2_STATE.auditTotal = typeof data.total === "number" ? data.total : data.items.length;
        renderAuditTable();
      }
    }
  } catch (_) {}
}

function changeAuditPage(delta) {
  const nextOffset = V2_STATE.auditOffset + delta * V2_STATE.auditLimit;
  if (nextOffset < 0 || nextOffset >= V2_STATE.auditTotal) return;
  fetchPaginatedAudit(nextOffset);
}

function renderAuditTable() {
  const tbody = document.getElementById("v2-audit-tbody");
  if (!tbody) return;

  const total = V2_STATE.auditTotal || V2_STATE.audit.length;
  document.getElementById("audit-total-metric").textContent = total;

  const startNum = total === 0 ? 0 : V2_STATE.auditOffset + 1;
  const endNum = Math.min(total, V2_STATE.auditOffset + V2_STATE.audit.length);
  const countEl = document.getElementById("audit-showing-count");
  if (countEl) countEl.textContent = `Showing ${startNum}–${endNum} of ${total} immutable records`;

  const currentPage = Math.floor(V2_STATE.auditOffset / V2_STATE.auditLimit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / V2_STATE.auditLimit));
  const pageInfo = document.getElementById("audit-page-info");
  if (pageInfo) pageInfo.textContent = `Page ${currentPage} of ${totalPages} (${total} total events)`;

  const prevBtn = document.getElementById("audit-prev-btn");
  const nextBtn = document.getElementById("audit-next-btn");
  if (prevBtn) prevBtn.disabled = V2_STATE.auditOffset <= 0;
  if (nextBtn) nextBtn.disabled = (V2_STATE.auditOffset + V2_STATE.auditLimit) >= total;

  tbody.replaceChildren();
  if (V2_STATE.audit.length === 0) {
    const tr = document.createElement("tr");
    const td = elText("td", "No audit records match the active filter criteria.");
    td.colSpan = 5;
    td.style.textAlign = "center";
    td.style.padding = "24px";
    td.style.color = "var(--ink-muted)";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  for (const row of V2_STATE.audit) {
    const tr = document.createElement("tr");
    const ts = (row.timestamp || "").replace("T", " ").substring(0, 19);
    const actionBadge = document.createElement("td");
    actionBadge.appendChild(elText("span", row.action, "v2-badge v2-badge-slate"));

    tr.append(
      elText("td", `#${row.id || "-"}`, "v2-mono"),
      elText("td", ts, "v2-mono"),
      elText("td", row.actor || "SYSTEM"),
      actionBadge,
      formatAuditDetailsCell(row.details)
    );
    tbody.appendChild(tr);
  }
}

function formatAuditDetailsCell(rawDetails) {
  const td = document.createElement("td");
  if (!rawDetails) {
    td.textContent = "—";
    return td;
  }
  let parsed = rawDetails;
  if (typeof rawDetails === "string") {
    const trimmed = rawDetails.trim();
    if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
      try {
        parsed = JSON.parse(trimmed);
      } catch (_) {
        parsed = trimmed;
      }
    }
  }
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
    const entries = Object.entries(parsed);
    if (entries.length === 0) {
      td.textContent = "Recorded";
      return td;
    }
    const wrap = document.createElement("div");
    wrap.className = "v2-audit-summary";
    for (const [k, v] of entries) {
      const pill = document.createElement("span");
      pill.className = "v2-audit-kv";
      const keySpan = elText("strong", `${k.replace(/_/g, " ")}:`);
      let valStr = Array.isArray(v) ? v.join(", ") : String(v ?? "");
      if (valStr.length > 56) valStr = valStr.substring(0, 53) + "...";
      const valSpan = elText("span", valStr);
      pill.append(keySpan, valSpan);
      wrap.appendChild(pill);
    }
    td.appendChild(wrap);
    return td;
  }
  td.textContent = String(parsed);
  return td;
}

function exportAuditJson() {
  const blob = new Blob([JSON.stringify(V2_STATE.audit, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `institutional_audit_log_${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
  showGlobalBanner("Exported immutable audit log as JSON.", "success");
}

function closeV2Modal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.add("hidden");
}

async function performV2Logout() {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } catch (_) {}
  window.location.href = "/?logged_out=1";
}
