// Institutional Portal Client-Side Controller
document.addEventListener('DOMContentLoaded', () => {
  initSession();
  setupEventListeners();
});

function checkUrlParams() {
  const params = new URLSearchParams(window.location.search);
  const alertContainer = document.getElementById('status-alert-container');
  if (!alertContainer) return;

  if (params.get('logged_out') === '1') {
    alertContainer.innerHTML = `
      <div class="status-alert logged-out" id="alert-logged-out">
        <div>
          <strong>Signed Out:</strong> You have been successfully signed out of the institutional library session.
        </div>
        <button class="btn btn-gold" style="padding: 0.35rem 0.85rem;" onclick="openLoginModal()">Sign In Again</button>
      </div>
    `;
    window.history.replaceState({}, document.title, window.location.pathname);
  } else if (params.get('login_required') === '1') {
    alertContainer.innerHTML = `
      <div class="status-alert warning" id="alert-login-required">
        <div>
          <strong>Authentication Required:</strong> Please sign in with your institutional credentials to access protected library volumes and features.
        </div>
        <button class="btn btn-gold" style="padding: 0.35rem 0.85rem;" onclick="openLoginModal()">Sign In Now</button>
      </div>
    `;
    setTimeout(() => openLoginModal(), 200);
    window.history.replaceState({}, document.title, window.location.pathname);
  }
}

async function initSession() {
  try {
    const res = await fetch('/api/auth/status?t=' + Date.now(), { cache: 'no-store' });
    const data = await res.json();
    renderAuthUI(data);
    checkUrlParams();
    loadCatalog(data.authenticated);
  } catch (err) {
    console.error('Session verification failed:', err);
  }
}

function renderAuthUI(status) {
  const userControls = document.getElementById('user-controls');
  const alertContainer = document.getElementById('status-alert-container');
  
  if (status.authenticated) {
    const isAdmin = (status.user.role === 'Administrator');
    const adminBtn = isAdmin ? `<a href="/admin" class="btn btn-outline" id="btn-admin-portal" style="border-color: #c99738; color: #fbbf24;">Admin Portal</a>` : '';
    userControls.innerHTML = `
      <div class="session-indicator">
        <span class="session-dot active"></span>
        <span><strong>${status.user.displayName || status.user.username}</strong> (${status.user.role})</span>
      </div>
      ${adminBtn}
      <a href="/calibre/" class="btn btn-gold" id="btn-full-calibre">Enter Full Library</a>
      <button class="btn btn-outline" id="btn-portal-logout" onclick="handleLogout()">Sign Out</button>
    `;
    alertContainer.innerHTML = `
      <div class="status-alert success">
        <div>
          <strong>Authenticated Session Active:</strong> Welcome, ${status.user.displayName || status.user.username}. You have authorized institutional access to all protected volumes.
        </div>
        <span class="tag tag-auth">Authorized</span>
      </div>
    `;
  } else {
    userControls.innerHTML = `
      <div class="session-indicator">
        <span class="session-dot"></span>
        <span>Guest (Authentication Required)</span>
      </div>
      <button class="btn btn-gold" onclick="openLoginModal()">Sign In</button>
    `;
    alertContainer.innerHTML = `
      <div class="status-alert warning">
        <div>
          <strong>Institutional Login Required:</strong> Protected digital volumes require individual authentication before browsing, searching, or reading.
        </div>
        <button class="btn btn-gold" style="padding: 0.35rem 0.85rem;" onclick="openLoginModal()">Sign In Now</button>
      </div>
    `;
  }
}

async function loadCatalog(isAuthenticated) {
  const container = document.getElementById('books-grid');
  if (!container) return;

  if (!isAuthenticated) {
    container.innerHTML = `
      <div style="grid-column: 1 / -1; background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 2.5rem 2rem; text-align: center;">
        <div style="font-size: 2.5rem; margin-bottom: 0.75rem;">🔒</div>
        <h3 style="color: #0f172a; margin-bottom: 0.5rem; font-size: 1.25rem;">Institutional Digital Repository Protected</h3>
        <p style="color: #64748b; max-width: 540px; margin: 0 auto 1.25rem; font-size: 0.95rem; line-height: 1.5;">
          In compliance with institutional access policies, repository catalogue metadata, digital volumes, and research editions require patron authentication.
        </p>
        <button class="btn btn-gold" style="padding: 0.65rem 1.5rem; font-size: 0.95rem;" onclick="openLoginModal()">Sign In to View Collection</button>
      </div>
    `;
    return;
  }

  try {
    const res = await fetch('/api/catalog');
    if (res.status === 401 || res.status === 403) {
      container.innerHTML = `
        <div style="grid-column: 1 / -1; background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 2rem; text-align: center; color: #991b1b;">
          <p><strong>Access Restricted:</strong> Please authenticate with an authorized account to access this collection.</p>
        </div>
      `;
      return;
    }
    const books = await res.json();
    if (!Array.isArray(books) || books.length === 0) {
      container.innerHTML = `
        <div style="grid-column: 1 / -1; padding: 2rem; text-align: center; color: #64748b;">
          <p>No volumes currently accessible under your institutional authorization profile.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = books.map(b => `
      <div class="book-card" data-title="${(b.title || '').toLowerCase()}" data-author="${(b.author || '').toLowerCase()}">
        <div>
          <div class="book-badge-row">
            <span class="tag tag-epub">${(b.formats && b.formats[0]) ? b.formats[0].toUpperCase() : 'EPUB'}</span>
            <span class="tag tag-auth">Access Granted</span>
          </div>
          <h3 class="book-title">${b.title}</h3>
          <p class="book-author">By ${b.author}</p>
          <p style="font-size: 0.85rem; color: #475569; line-height: 1.4;">${b.description || 'Institutional research edition deposited in the campus digital library repository.'}</p>
        </div>
        <div class="book-actions">
          <a href="/calibre/#book_id=${b.id}&panel=book_details" class="btn btn-primary">Read Online</a>
          <a href="/calibre/get/${(b.formats && b.formats[0]) ? b.formats[0].toLowerCase() : 'epub'}/${b.id}/library" class="btn btn-secondary" download>Download</a>
        </div>
      </div>
    `).join('');
  } catch (err) {
    container.innerHTML = `<p style="color:#dc2626; padding:1rem; text-align:center;">Failed to connect to repository catalog service.</p>`;
  }
}

function setupEventListeners() {
  const searchInput = document.getElementById('search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      const q = e.target.value.toLowerCase();
      document.querySelectorAll('.book-card').forEach(card => {
        const title = card.getAttribute('data-title') || '';
        const author = card.getAttribute('data-author') || '';
        if (title.includes(q) || author.includes(q)) {
          card.style.display = 'flex';
        } else {
          card.style.display = 'none';
        }
      });
    });
  }
  
  const loginForm = document.getElementById('login-form');
  if (loginForm) {
    loginForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const u = document.getElementById('login-username').value;
      const p = document.getElementById('login-password').value;
      const errorDiv = document.getElementById('login-error');
      errorDiv.style.display = 'none';
      
      try {
        const res = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: u, password: p })
        });
        
        if (res.status === 429) {
          const data = await res.json().catch(() => ({}));
          errorDiv.innerText = data.error || 'Too many failed login attempts. Please wait 60 seconds.';
          errorDiv.style.display = 'block';
          return;
        }

        const data = await res.json();
        if (data.success) {
          closeLoginModal();
          initSession();
        } else {
          errorDiv.innerText = data.error || 'Authentication failed';
          errorDiv.style.display = 'block';
        }
      } catch (err) {
        errorDiv.innerText = 'Network error contacting authentication gateway.';
        errorDiv.style.display = 'block';
      }
    });
  }
}

function openLoginModal(bookContext) {
  const modal = document.getElementById('login-modal');
  modal.classList.add('active');
  const errorDiv = document.getElementById('login-error');
  errorDiv.style.display = 'none';
  if (bookContext) {
    document.getElementById('login-context-msg').innerText = `Sign in to access "${bookContext}"`;
  } else {
    document.getElementById('login-context-msg').innerText = 'Enter your institutional credentials';
  }
}

function closeLoginModal() {
  document.getElementById('login-modal').classList.remove('active');
}

async function handleLogout() {
  try {
    await fetch('/api/auth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'logout' })
    });
    // Invalidate client-side cookie
    document.cookie = 'inst_session_id=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0';
    window.location.href = '/?logged_out=1';
  } catch (err) {
    console.error('Logout error:', err);
    window.location.href = '/?logged_out=1';
  }
}
