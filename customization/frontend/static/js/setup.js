function escapeText(value) { const el = document.createElement("span"); el.textContent = String(value); return el.innerHTML; }
// First-Time Setup Wizard Controller
let currentStep = 1;
let envStatus = null;
let libraryValidated = false;

document.addEventListener("DOMContentLoaded", () => {
  checkPrerequisites();
});

function showAlert(msg, isError = true) {
  const el = document.getElementById("setup-alert");
  if (!el) return;
  el.className = `setup-alert ${isError ? "error" : "success"}`;
  el.textContent = msg;
  el.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function clearAlert() {
  const el = document.getElementById("setup-alert");
  if (el) el.classList.add("hidden");
}

async function checkPrerequisites() {
  clearAlert();
  try {
    const res = await fetch("/api/setup/status?t=" + Date.now());
    const data = await res.json();
    envStatus = data;

    // 1. Calibre Binary Check
    const calEl = document.getElementById("check-calibre-bin");
    const calBadge = document.getElementById("badge-calibre-bin");
    if (data.calibre_installed) {
      calEl.className = "check-item";
      calBadge.className = "badge badge-success";
      calBadge.textContent = "Verified " + (data.calibre_version || "7.x");
    } else {
      calEl.className = "check-item";
      calBadge.className = "badge badge-danger";
      calBadge.textContent = "Not Found";
    }

    // 2. Gateway Status
    const gwEl = document.getElementById("check-gateway");
    const gwBadge = document.getElementById("badge-gateway");
    gwEl.className = "check-item";
    gwBadge.className = "badge badge-success";
    gwBadge.textContent = "Active (Port " + (data.gateway_port || 8085) + ")";

    // 3. Storage Mode
    const stEl = document.getElementById("check-storage");
    const stBadge = document.getElementById("badge-storage");
    stEl.className = "check-item";
    stBadge.className = "badge badge-success";
    stBadge.textContent = data.storage_mode || "AppData (Ready)";

  } catch (err) {
    showAlert("Failed to connect to setup prerequisites endpoint: " + err.message);
  }
}

function goToStep(step) {
  clearAlert();
  document.querySelectorAll(".step-panel").forEach(p => p.classList.add("hidden"));
  const targetPanel = document.getElementById("panel-step-" + step);
  if (targetPanel) targetPanel.classList.remove("hidden");

  // Update Stepper indicators
  document.querySelectorAll(".step-item").forEach(item => {
    const s = parseInt(item.getAttribute("data-step"), 10);
    item.classList.remove("active", "completed");
    if (s === step) {
      item.classList.add("active");
    } else if (s < step) {
      item.classList.add("completed");
    }
  });

  currentStep = step;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function nextStep(step) {
  goToStep(step);
}

function prevStep(step) {
  goToStep(step);
}

function validateStep2() {
  clearAlert();
  const name = document.getElementById("inst-name").value.trim();
  const shortName = document.getElementById("inst-short-name").value.trim();
  const libName = document.getElementById("inst-library-name").value.trim();

  if (!name) return showAlert("Institution Name is required.");
  if (!shortName) return showAlert("Acronym / Short Name is required.");
  if (!libName) return showAlert("Library Display Name is required.");

  goToStep(3);
}

function validateStep3() {
  clearAlert();
  const user = document.getElementById("admin-username").value.trim();
  const name = document.getElementById("admin-fullname").value.trim();
  const pass = document.getElementById("admin-password").value;
  const confirm = document.getElementById("admin-password-confirm").value;

  if (!user || user.length < 3) return showAlert("Administrator username must be at least 3 characters.");
  if (!name) return showAlert("Administrator full name is required.");
  if (!pass || pass.length < 8) return showAlert("Administrator password must be at least 8 characters long.");
  if (pass !== confirm) return showAlert("Administrator passwords do not match.");

  goToStep(4);
}

async function validateLibraryPath() {
  clearAlert();
  const path = document.getElementById("lib-path").value.trim();
  const resCard = document.getElementById("lib-validation-result");
  const btn = document.getElementById("btn-validate-lib");

  if (!path) return showAlert("Please specify a Calibre library folder path.");

  btn.disabled = true;
  btn.textContent = "Verifying...";

  try {
    const res = await fetch("/api/setup/validate-library", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ library_path: path })
    });
    const data = await res.json();
    btn.disabled = false;
    btn.textContent = "Verify Path";

    if (data.valid) {
      libraryValidated = true;
      resCard.className = "lib-validation-card";
      resCard.innerHTML = `
        <div style="font-size: 1.5rem;">âœ…</div>
        <div>
          <strong>Valid Calibre Library Confirmed</strong>
          <p style="margin: 0; font-size: 0.85rem; color: #94a3b8;">Found metadata.db with ${data.books_count || 0} registered volumes.</p>
        </div>
      `;
      resCard.classList.remove("hidden");
    } else {
      libraryValidated = false;
      resCard.className = "lib-validation-card error";
      resCard.innerHTML = `
        <div style="font-size: 1.5rem;">âŒ</div>
        <div>
          <strong>Invalid Library Directory</strong>
          <p style="margin: 0; font-size: 0.85rem; color: #fca5a5;">${escapeText(data.error || "metadata.db not found in specified directory.")}</p>
        </div>
      `;
      resCard.classList.remove("hidden");
    }
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Verify Path";
    showAlert("Library validation failed: " + err.message);
  }
}

function validateStep4() {
  clearAlert();
  const path = document.getElementById("lib-path").value.trim();
  const label = document.getElementById("lib-display-name").value.trim();

  if (!path) return showAlert("Library path is required.");
  if (!label) return showAlert("Library friendly label is required.");
  if (!libraryValidated) return showAlert("Please click 'Verify Path' and ensure a valid Calibre library is confirmed before proceeding.");

  // Populate Review Step
  document.getElementById("rev-inst-name").textContent = document.getElementById("inst-name").value.trim();
  document.getElementById("rev-inst-short").textContent = document.getElementById("inst-short-name").value.trim();
  document.getElementById("rev-inst-library").textContent = document.getElementById("inst-library-name").value.trim();
  document.getElementById("rev-inst-motto").textContent = document.getElementById("inst-motto").value.trim() || "(None)";
  document.getElementById("rev-inst-contact").textContent = document.getElementById("inst-email").value.trim() || "(None)";

  document.getElementById("rev-admin-user").textContent = document.getElementById("admin-username").value.trim();
  document.getElementById("rev-admin-name").textContent = document.getElementById("admin-fullname").value.trim();
  document.getElementById("rev-admin-dept").textContent = document.getElementById("admin-dept").value.trim() || "Administration";

  document.getElementById("rev-lib-name").textContent = label;
  document.getElementById("rev-lib-path").textContent = path;

  goToStep(5);
}

async function finalizeSetup() {
  clearAlert();
  const btn = document.getElementById("btn-finalize");
  btn.disabled = true;
  btn.textContent = "Provisioning Institution & Bootstrapping Administrator...";

  const payload = {
    institution: {
      name: document.getElementById("inst-name").value.trim(),
      short_name: document.getElementById("inst-short-name").value.trim(),
      library_name: document.getElementById("inst-library-name").value.trim(),
      motto: document.getElementById("inst-motto").value.trim(),
      contact_email: document.getElementById("inst-email").value.trim(),
      contact_phone: document.getElementById("inst-phone").value.trim(),
      logo_url: document.getElementById("inst-logo-url").value.trim()
    },
    admin: {
      username: document.getElementById("admin-username").value.trim(),
      password: document.getElementById("admin-password").value,
      full_name: document.getElementById("admin-fullname").value.trim(),
      department: document.getElementById("admin-dept").value.trim()
    },
    library: {
      path: document.getElementById("lib-path").value.trim(),
      display_name: document.getElementById("lib-display-name").value.trim(),
      is_default: document.getElementById("lib-is-default").checked
    }
  };

  try {
    const res = await fetch("/api/setup/complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();

    if (data.success) {
      showAlert("Configuration committed successfully! Redirecting to Institutional Administration...", false);
      setTimeout(() => {
        window.location.href = data.redirect || "/admin";
      }, 1500);
    } else {
      btn.disabled = false;
      btn.textContent = "Finalize & Bootstrap Institution âœ“";
      showAlert("Setup failed: " + (data.error || "Unknown server error"));
    }
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Finalize & Bootstrap Institution âœ“";
    showAlert("Setup request failed: " + err.message);
  }
}
