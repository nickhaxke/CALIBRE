// External values are inserted as text, never executable markup.
function textCell(value) { const cell = document.createElement('td'); cell.textContent = value == null ? '' : String(value); return cell; }
function actionButton(label, action) { const button = document.createElement('button'); button.type = 'button'; button.className = 'btn btn-outline btn-sm'; button.textContent = label; button.addEventListener('click', action); return button; }
// Institutional Administration Controller
let adminState = {
  institution: {},
  libraries: [],
  users: [],
  system: {}
};

document.addEventListener("DOMContentLoaded", () => {
  setupNavigation();
  loadDashboard();
});

function showAlert(msg, isError = true) {
  const el = document.getElementById("admin-alert");
  if (!el) return;
  el.className = `admin-alert ${isError ? "error" : "success"}`;
  el.textContent = msg;
  el.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function clearAlert() {
  const el = document.getElementById("admin-alert");
  if (el) el.classList.add("hidden");
}

function setupNavigation() {
  document.querySelectorAll(".nav-item").forEach(btn => {
    btn.addEventListener("click", () => {
      const tab = btn.getAttribute("data-tab");
      switchTab(tab);
    });
  });
}

function switchTab(tab) {
  clearAlert();
  document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));

  const targetBtn = document.querySelector(`.nav-item[data-tab="${tab}"]`);
  const targetPane = document.getElementById("pane-" + tab);

  if (targetBtn) targetBtn.classList.add("active");
  if (targetPane) targetPane.classList.add("active");

  const titles = {
    dashboard: "Dashboard Overview",
    settings: "Institution Identity & Settings",
    libraries: "Connected Calibre Libraries",
    users: "Calibre User Administration",
    system: "System Diagnostics & Controls",
    audit: "Administrative Audit Trail"
  };
  document.getElementById("section-title").textContent = titles[tab] || "Administration";

  if (tab === "dashboard") loadDashboard();
  if (tab === "settings") loadSettingsForm();
  if (tab === "libraries") loadLibraries();
  if (tab === "users") loadUsers();
  if (tab === "system") loadSystemDiagnostics();
  if (tab === "audit") loadAuditLog();
}

async function loadDashboard() {
  try {
    const res = await fetch("/api/admin/dashboard?t=" + Date.now());
    if (res.status === 401 || res.status === 403) {
      window.location.href = "/?login_required=1";
      return;
    }
    const data = await res.json();
    adminState = data;

    // Institution Branding
    const inst = data.institution || {};
    document.getElementById("sidebar-seal").textContent = inst.short_name || "CIV";
    document.getElementById("sidebar-inst-name").textContent = inst.name || "Calibre Institutional";
    document.getElementById("dash-inst-name").textContent = inst.name || "-";
    document.getElementById("dash-inst-short").textContent = inst.short_name || "-";
    document.getElementById("dash-inst-lib").textContent = inst.library_name || "-";
    document.getElementById("dash-inst-motto").textContent = inst.motto || "(None)";
    document.getElementById("dash-inst-contact").textContent = (inst.contact_email || "") + " " + (inst.contact_phone || "");

    // Stats
    document.getElementById("stat-libraries-count").textContent = (data.libraries || []).length;
    document.getElementById("stat-users-count").textContent = data.users_count || 0;
    document.getElementById("stat-gateway-port").textContent = data.system?.gateway_port || 8085;
    document.getElementById("stat-storage-mode").textContent = data.system?.storage_mode || "SQLite";

    // Backend status badge
    const bgBadge = document.getElementById("backend-status-badge");
    if (data.system?.calibre_backend_online) {
      bgBadge.textContent = "Calibre Backend: Online (Port 8088)";
      bgBadge.className = "topbar-badge";
    } else {
      bgBadge.textContent = "Calibre Backend: Unreachable";
      bgBadge.className = "topbar-badge";
      bgBadge.style.borderColor = "#ef4444";
      bgBadge.style.color = "#f87171";
    }

    // Recent Audit preview
    const recentAuditDiv = document.getElementById("dash-recent-audit");
    if (data.recent_audit && data.recent_audit.length > 0) {
      recentAuditDiv.replaceChildren();
      for (const entry of data.recent_audit.slice(0, 5)) {
        const row = document.createElement('div'); row.className = 'recent-audit-item';
        row.textContent = `${entry.action} by ${entry.actor} · ${entry.timestamp.substring(11, 19)}`;
        recentAuditDiv.append(row);
      }
    } else {
      recentAuditDiv.innerHTML = "<p style='color: #64748b; font-size: 0.9rem;'>No recent audit entries.</p>";
    }

  } catch (err) {
    showAlert("Failed to load dashboard data: " + err.message);
  }
}

async function loadSettingsForm() {
  clearAlert();
  try {
    const res = await fetch("/api/admin/settings?t=" + Date.now());
    const inst = await res.json();
    document.getElementById("set-name").value = inst.name || "";
    document.getElementById("set-short-name").value = inst.short_name || "";
    document.getElementById("set-library-name").value = inst.library_name || "";
    document.getElementById("set-motto").value = inst.motto || "";
    document.getElementById("set-email").value = inst.contact_email || "";
    document.getElementById("set-phone").value = inst.contact_phone || "";
    document.getElementById("set-logo-url").value = inst.logo_url || "";
  } catch (err) {
    showAlert("Failed to load institution settings: " + err.message);
  }
}

async function saveSettings(e) {
  e.preventDefault();
  clearAlert();
  const btn = document.getElementById("btn-save-settings");
  btn.disabled = true;
  btn.textContent = "Saving...";

  const payload = {
    name: document.getElementById("set-name").value.trim(),
    short_name: document.getElementById("set-short-name").value.trim(),
    library_name: document.getElementById("set-library-name").value.trim(),
    motto: document.getElementById("set-motto").value.trim(),
    contact_email: document.getElementById("set-email").value.trim(),
    contact_phone: document.getElementById("set-phone").value.trim(),
    logo_url: document.getElementById("set-logo-url").value.trim()
  };

  try {
    const res = await fetch("/api/admin/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    btn.disabled = false;
    btn.textContent = "Save Institution Settings";

    if (data.success) {
      showAlert("Institutional identity and branding updated successfully!", false);
      loadDashboard();
    } else {
      showAlert("Failed to update settings: " + (data.error || "Unknown error"));
    }
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Save Institution Settings";
    showAlert("Request failed: " + err.message);
  }
}

async function loadLibraries() {
  clearAlert();
  const tbody = document.getElementById("tbody-libraries");
  try {
    const res = await fetch("/api/admin/libraries?t=" + Date.now());
    const list = await res.json();
    if (!list || list.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: #64748b;">No libraries registered yet.</td></tr>`;
      return;
    }

    tbody.replaceChildren();
    for (const lib of list) {
      const row = document.createElement('tr');
      row.append(textCell(lib.display_name), textCell(lib.path), textCell(lib.is_active ? 'Active' : 'Disabled'));
      const defaults = textCell(lib.is_default ? 'Primary Default' : '');
      if (!lib.is_default) defaults.append(actionButton('Make Default', () => setDefaultLibrary(lib.id)));
      const actions = textCell('');
      actions.append(actionButton(lib.is_active ? 'Disable' : 'Enable', () => toggleLibraryActive(lib.id, !lib.is_active)), actionButton('Remove', () => removeLibrary(lib.id)));
      row.append(defaults, actions); tbody.append(row);
    }
  } catch (err) {
    showAlert("Failed to load libraries: " + err.message);
  }
}

async function setDefaultLibrary(libId) {
  try {
    const res = await fetch("/api/admin/libraries/default", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ library_id: libId })
    });
    const data = await res.json();
    if (data.success) {
      showAlert("Default library updated.", false);
      loadLibraries();
    }
  } catch (err) {
    showAlert("Failed to set default library: " + err.message);
  }
}

async function toggleLibraryActive(libId, isActive) {
  try {
    const res = await fetch("/api/admin/libraries/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ library_id: libId, is_active: isActive })
    });
    const data = await res.json();
    if (data.success) {
      showAlert(`Library ${isActive ? 'enabled' : 'disabled'} safely.`, false);
      loadLibraries();
    }
  } catch (err) {
    showAlert("Failed to toggle library status: " + err.message);
  }
}

async function removeLibrary(libId) {
  if (!confirm("Are you sure you want to remove this library from the configuration? No files on disk will be deleted.")) return;
  try {
    const res = await fetch("/api/admin/libraries/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ library_id: libId })
    });
    const data = await res.json();
    if (data.success) {
      showAlert("Library association removed.", false);
      loadLibraries();
    }
  } catch (err) {
    showAlert("Failed to remove library: " + err.message);
  }
}

async function loadUsers() {
  clearAlert();
  const tbody = document.getElementById("tbody-users");
  try {
    const res = await fetch("/api/admin/users?t=" + Date.now());
    const list = await res.json();
    if (!list || list.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #64748b;">No Calibre users found.</td></tr>`;
      return;
    }

    tbody.replaceChildren();
    for (const user of list) {
      const row = document.createElement('tr');
      row.append(textCell(user.username), textCell(user.display_name || user.username), textCell(user.role), textCell(user.department || 'General'), textCell(user.readonly ? 'Read-Only' : 'Read-Write'));
      const actions = textCell('');
      actions.append(actionButton('Password', () => openChangePassModal(user.username)), actionButton(user.readonly ? 'Allow Write' : 'Make Read-Only', () => toggleUserReadonly(user.username, !user.readonly)), actionButton('Delete', () => removeUser(user.username)));
      row.append(actions); tbody.append(row);
    }
  } catch (err) {
    showAlert("Failed to load users: " + err.message);
  }
}

async function toggleUserReadonly(username, readonly) {
  try {
    const res = await fetch("/api/admin/users/readonly", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, readonly })
    });
    const data = await res.json();
    if (data.success) {
      showAlert(`User ${username} access mode updated.`, false);
      loadUsers();
    } else {
      showAlert("Failed: " + data.error);
    }
  } catch (err) {
    showAlert("Failed to update user readonly status: " + err.message);
  }
}

async function removeUser(username) {
  if (!confirm(`Are you sure you want to permanently delete user account "${username}"?`)) return;
  try {
    const res = await fetch("/api/admin/users/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username })
    });
    const data = await res.json();
    if (data.success) {
      showAlert(`User "${username}" removed successfully.`, false);
      loadUsers();
    } else {
      showAlert("Failed: " + data.error);
    }
  } catch (err) {
    showAlert("Failed to remove user: " + err.message);
  }
}

async function loadSystemDiagnostics() {
  clearAlert();
  try {
    const res = await fetch("/api/admin/system?t=" + Date.now());
    const data = await res.json();

    document.getElementById("sys-gw-port").textContent = data.gateway_port || 8085;
    document.getElementById("sys-lan-ips").textContent = (data.lan_ips || []).join(", ");
    document.getElementById("sys-calibre-port").textContent = data.calibre_port || 8088;
    
    const calStatus = document.getElementById("sys-calibre-status");
    if (data.calibre_backend_online) {
      calStatus.innerHTML = '<span class="badge badge-success">Online & Responding</span>';
    } else {
      calStatus.innerHTML = '<span class="badge badge-danger">Offline / Unreachable</span>';
    }

    document.getElementById("sys-db-path").textContent = data.db_path || "-";
    document.getElementById("sys-storage-mode").textContent = data.storage_mode || "SQLite";

  } catch (err) {
    showAlert("Failed to load diagnostics: " + err.message);
  }
}

async function triggerBackup() {
  clearAlert();
  try {
    const res = await fetch("/api/admin/system/backup", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showAlert(`Snapshot created at: ${data.backup_path}`, false);
    } else {
      showAlert("Backup failed: " + data.error);
    }
  } catch (err) {
    showAlert("Backup request failed: " + err.message);
  }
}

async function reloadConfigCache() {
  clearAlert();
  try {
    const res = await fetch("/api/admin/system/reload", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showAlert("Configuration cache reloaded.", false);
      loadDashboard();
    }
  } catch (err) {
    showAlert("Reload request failed: " + err.message);
  }
}

async function loadAuditLog() {
  clearAlert();
  const tbody = document.getElementById("tbody-audit");
  try {
    const res = await fetch("/api/admin/audit-log?t=" + Date.now());
    const list = await res.json();
    if (!list || list.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: #64748b;">No audit entries found.</td></tr>`;
      return;
    }

    tbody.replaceChildren();
    for (const entry of list) {
      const row = document.createElement('tr');
      row.append(textCell(entry.timestamp), textCell(entry.actor), textCell(entry.action), textCell(JSON.stringify(entry.details)));
      tbody.append(row);
    }
  } catch (err) {
    showAlert("Failed to load audit log: " + err.message);
  }
}

function openAddLibraryModal() {
  document.getElementById("modal-lib-name").value = "";
  document.getElementById("modal-lib-path").value = "";
  document.getElementById("modal-lib-validation").classList.add("hidden");
  document.getElementById("modal-add-library").classList.remove("hidden");
}

async function verifyModalLibPath() {
  const path = document.getElementById("modal-lib-path").value.trim();
  const valCard = document.getElementById("modal-lib-validation");
  if (!path) return;

  valCard.className = "lib-validation-card";
  valCard.textContent = "Verifying...";
  valCard.classList.remove("hidden");

  try {
    const res = await fetch("/api/setup/validate-library", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ library_path: path })
    });
    const data = await res.json();
    if (data.valid) {
      valCard.className = "lib-validation-card";
      valCard.innerHTML = `<span>✅ Found metadata.db with ${data.books_count || 0} volumes.</span>`;
    } else {
      valCard.className = "lib-validation-card error";
      valCard.textContent = data.error || "metadata.db not found";
    }
  } catch (err) {
    valCard.className = "lib-validation-card error";
    valCard.textContent = "Validation failed: " + err.message;
  }
}

async function submitAddLibrary(e) {
  e.preventDefault();
  const label = document.getElementById("modal-lib-name").value.trim();
  const path = document.getElementById("modal-lib-path").value.trim();
  const isDef = document.getElementById("modal-lib-default").checked;

  try {
    const res = await fetch("/api/admin/libraries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: label, library_path: path, is_default: isDef })
    });
    const data = await res.json();
    if (data.success) {
      closeModal("modal-add-library");
      showAlert("Library connected successfully.", false);
      loadLibraries();
    } else {
      alert("Error: " + data.error);
    }
  } catch (err) {
    alert("Request error: " + err.message);
  }
}

function openCreateUserModal() {
  document.getElementById("usr-username").value = "";
  document.getElementById("usr-password").value = "";
  document.getElementById("usr-fullname").value = "";
  document.getElementById("usr-department").value = "";
  document.getElementById("usr-readonly").checked = true;
  document.getElementById("modal-create-user").classList.remove("hidden");
}

async function submitCreateUser(e) {
  e.preventDefault();
  const btn = document.getElementById("btn-submit-user");
  btn.disabled = true;

  const payload = {
    username: document.getElementById("usr-username").value.trim(),
    password: document.getElementById("usr-password").value,
    full_name: document.getElementById("usr-fullname").value.trim(),
    role: document.getElementById("usr-role").value,
    department: document.getElementById("usr-department").value.trim(),
    readonly: document.getElementById("usr-readonly").checked
  };

  try {
    const res = await fetch("/api/admin/users/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    btn.disabled = false;
    if (data.success) {
      closeModal("modal-create-user");
      showAlert(`User account "${payload.username}" created successfully.`, false);
      loadUsers();
    } else {
      alert("Error creating user: " + data.error);
    }
  } catch (err) {
    btn.disabled = false;
    alert("Request failed: " + err.message);
  }
}

function openChangePassModal(username) {
  document.getElementById("chpass-username").value = username;
  document.getElementById("chpass-display-user").textContent = username;
  document.getElementById("chpass-new").value = "";
  document.getElementById("modal-change-pass").classList.remove("hidden");
}

async function submitChangePassword(e) {
  e.preventDefault();
  const username = document.getElementById("chpass-username").value;
  const newPass = document.getElementById("chpass-new").value;

  try {
    const res = await fetch("/api/admin/users/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, new_password: newPass })
    });
    const data = await res.json();
    if (data.success) {
      closeModal("modal-change-pass");
      showAlert(`Password for "${username}" updated successfully.`, false);
    } else {
      alert("Error updating password: " + data.error);
    }
  } catch (err) {
    alert("Request failed: " + err.message);
  }
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add("hidden");
}

async function adminLogout() {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } catch (e) {}
  window.location.href = "/?logged_out=1";
}
