'use strict';

(function () {
  const params = new URLSearchParams(location.search);
  const bookId = params.get('book_id') || '';
  const libraryId = params.get('library_id') || '';

  let savedScrollPref = false;
  try {
    savedScrollPref = localStorage.getItem('inst_pdf_scroll_mode') === '1';
  } catch (_) {}

  const state = {
    bookId,
    libraryId,
    title: '',
    totalPages: 0,
    currentPage: 1,
    zoom: 100,
    fitMode: 'width', // 'width' | 'page' | 'custom'
    scrollMode: savedScrollPref, // false = Single Page, true = Continuous Vertical Scroll
    sidebarOpen: false,
    activeTab: 'pages',
    loadingPage: false,
    scrollBuilt: false
  };

  let scrollObserver = null;
  let visibilityObserver = null;

  const $ = id => document.getElementById(id);

  const catalogueUrl = libraryId
    ? `/calibre/institutional?library_id=${encodeURIComponent(libraryId)}`
    : '/calibre/institutional';

  if ($('btn-back-catalogue')) $('btn-back-catalogue').href = catalogueUrl;
  if ($('error-back-link')) $('error-back-link').href = catalogueUrl;

  function showError(title, message) {
    if ($('reader-loading')) $('reader-loading').hidden = true;
    if ($('page-viewport')) $('page-viewport').hidden = true;
    if ($('scroll-viewport')) $('scroll-viewport').hidden = true;
    if ($('reader-bottom-bar')) $('reader-bottom-bar').hidden = true;
    if ($('floating-prev-btn')) $('floating-prev-btn').hidden = true;
    if ($('floating-next-btn')) $('floating-next-btn').hidden = true;
    if ($('error-title')) $('error-title').textContent = title || 'Unable to Open Publication';
    if ($('error-message')) $('error-message').textContent = message || 'The requested PDF document could not be loaded.';
    if ($('reader-error')) $('reader-error').hidden = false;
  }

  function applyBranding(b) {
    if (!b) return;
    if (b.primary_color && /^#[0-9a-f]{6}$/i.test(b.primary_color)) {
      document.documentElement.style.setProperty('--green', b.primary_color);
    }
    if (b.logo_url && $('reader-logo')) {
      $('reader-logo').src = b.logo_url;
      $('reader-logo').style.display = '';
      if ($('reader-seal-text')) $('reader-seal-text').style.display = 'none';
    } else if (b.short_name && $('reader-seal-text')) {
      $('reader-seal-text').textContent = b.short_name;
      $('reader-seal-text').style.display = 'inline';
    }
  }

  function getTargetSheetWidthPx() {
    const baseWidth = 860;
    return Math.round((baseWidth * state.zoom) / 100);
  }

  function applyZoomGeometry() {
    const sheet = $('page-sheet');
    if ($('zoom-level')) $('zoom-level').textContent = `${state.zoom}%`;
    if ($('btn-fit-width')) $('btn-fit-width').classList.toggle('active', state.fitMode === 'width');
    if ($('btn-fit-page')) $('btn-fit-page').classList.toggle('active', state.fitMode === 'page');

    const targetPx = getTargetSheetWidthPx();

    if (sheet) {
      if (state.fitMode === 'page' && !state.scrollMode) {
        sheet.classList.add('fit-page');
        sheet.style.width = 'auto';
        sheet.style.maxWidth = '100%';
      } else {
        sheet.classList.remove('fit-page');
        sheet.style.width = `${targetPx}px`;
        sheet.style.maxWidth = state.zoom <= 100 ? '100%' : 'none';
      }
    }

    const scrollCards = document.querySelectorAll('.scroll-page-card');
    scrollCards.forEach(card => {
      card.style.width = `${targetPx}px`;
      card.style.maxWidth = state.zoom <= 100 ? '100%' : 'none';
    });
  }

  function updateControls() {
    const atStart = state.currentPage <= 1;
    const atEnd = state.currentPage >= state.totalPages;

    if ($('page-input')) $('page-input').value = String(state.currentPage);
    if ($('page-total')) $('page-total').textContent = String(state.totalPages || 0);
    if ($('bottom-page-status')) {
      $('bottom-page-status').textContent = `Page ${state.currentPage} of ${state.totalPages || 1}`;
    }

    ['btn-prev-page', 'floating-prev-btn', 'bottom-prev-btn'].forEach(id => {
      if ($(id)) $(id).disabled = atStart;
    });
    ['btn-next-page', 'floating-next-btn', 'bottom-next-btn'].forEach(id => {
      if ($(id)) $(id).disabled = atEnd;
    });

    if ($('btn-scroll-mode')) {
      $('btn-scroll-mode').classList.toggle('active', state.scrollMode);
      $('btn-scroll-mode').setAttribute('aria-pressed', state.scrollMode ? 'true' : 'false');
    }
    if ($('scroll-mode-label')) {
      $('scroll-mode-label').textContent = state.scrollMode ? 'Scroll Mode: ON' : 'Continuous Scroll';
    }
    if ($('bottom-mode-btn')) {
      $('bottom-mode-btn').classList.toggle('active', state.scrollMode);
      $('bottom-mode-btn').textContent = state.scrollMode ? 'Scroll Down Mode: ON' : 'Scroll Down Mode: OFF';
    }

    const navBtns = document.querySelectorAll('.page-nav-item');
    navBtns.forEach(btn => {
      const p = Number(btn.getAttribute('data-page'));
      btn.classList.toggle('active', p === state.currentPage);
    });
  }

  function buildPageList() {
    const list = $('page-list');
    if (!list) return;
    list.replaceChildren();
    for (let p = 1; p <= state.totalPages; p++) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'page-nav-item' + (p === state.currentPage ? ' active' : '');
      btn.setAttribute('data-page', String(p));
      btn.textContent = `Page ${p}`;
      btn.onclick = () => {
        goToPage(p);
        if (window.innerWidth <= 900) toggleSidebar(false);
      };
      list.appendChild(btn);
    }
  }

  function buildPageUrl(pageNum, dpi) {
    const q = new URLSearchParams({
      book_id: state.bookId,
      library_id: state.libraryId,
      page: String(pageNum),
      dpi: String(dpi || 150)
    });
    return `/api/reader/page?${q.toString()}`;
  }

  function preloadAdjacentPage(pageNum) {
    if (pageNum < 1 || pageNum > state.totalPages) return;
    const pre = new Image();
    pre.src = buildPageUrl(pageNum, 150);
  }

  function buildContinuousScrollDOM() {
    const container = $('scroll-viewport');
    if (!container) return;
    container.replaceChildren();

    if (scrollObserver) scrollObserver.disconnect();
    if (visibilityObserver) visibilityObserver.disconnect();

    const stage = $('reader-stage');
    const dpi = state.zoom > 150 ? 200 : 150;
    const targetPx = getTargetSheetWidthPx();

    scrollObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        const card = entry.target;
        const img = card.querySelector('img[data-src]');
        if (img && !img.getAttribute('src')) {
          img.src = img.getAttribute('data-src');
        }
      });
    }, {
      root: stage,
      rootMargin: '600px 0px 600px 0px',
      threshold: 0.01
    });

    visibilityObserver = new IntersectionObserver(entries => {
      let bestPage = null;
      let bestRatio = 0;
      entries.forEach(entry => {
        if (entry.isIntersecting && entry.intersectionRatio >= bestRatio) {
          bestRatio = entry.intersectionRatio;
          bestPage = Number(entry.target.getAttribute('data-page'));
        }
      });
      if (bestPage && bestPage !== state.currentPage) {
        state.currentPage = bestPage;
        updateControls();
      }
    }, {
      root: stage,
      threshold: [0.25, 0.5, 0.75]
    });

    for (let p = 1; p <= state.totalPages; p++) {
      const card = document.createElement('div');
      card.className = 'scroll-page-card';
      card.id = `scroll-page-card-${p}`;
      card.setAttribute('data-page', String(p));
      card.style.width = `${targetPx}px`;
      card.style.maxWidth = state.zoom <= 100 ? '100%' : 'none';

      const badge = document.createElement('span');
      badge.className = 'scroll-page-badge';
      badge.textContent = `Page ${p} of ${state.totalPages}`;

      const img = document.createElement('img');
      img.alt = `${state.title} — Page ${p} of ${state.totalPages}`;
      img.draggable = false;
      const url = buildPageUrl(p, dpi);
      if (p <= 2 || Math.abs(p - state.currentPage) <= 1) {
        img.src = url;
      } else {
        img.setAttribute('data-src', url);
      }

      card.append(badge, img);
      container.appendChild(card);
      scrollObserver.observe(card);
      visibilityObserver.observe(card);
    }

    state.scrollBuilt = true;
  }

  function renderSinglePage(pageNum) {
    if (!state.totalPages) return;
    const target = Math.max(1, Math.min(state.totalPages, Number(pageNum) || 1));
    state.currentPage = target;
    updateControls();

    const img = $('pdf-page-img');
    if (!img) return;

    const dpi = state.zoom > 150 ? 200 : 150;
    const url = buildPageUrl(target, dpi);

    if ($('page-viewport').hidden) {
      $('reader-loading').hidden = false;
      $('loading-message').textContent = `Rendering page ${target} of ${state.totalPages}…`;
    }

    img.onload = () => {
      $('reader-loading').hidden = true;
      $('reader-error').hidden = true;
      if (!state.scrollMode) {
        $('page-viewport').hidden = false;
        if ($('scroll-viewport')) $('scroll-viewport').hidden = true;
      }
      img.alt = `${state.title} — Page ${target} of ${state.totalPages}`;
      applyZoomGeometry();
      if (!state.scrollMode && $('reader-stage')) $('reader-stage').scrollTop = 0;
      preloadAdjacentPage(target + 1);
    };

    img.onerror = async () => {
      try {
        const st = await fetch('/api/auth/status', { cache: 'no-store' });
        const stData = await st.json();
        if (!stData || !stData.authenticated) {
          location.assign('/?login_required=1');
          return;
        }
      } catch (_) {}
      showError(
        'Page Rendering Error',
        `Page ${target} could not be rendered. The document file may be damaged or unavailable.`
      );
    };

    img.src = url;
  }

  function goToPage(pageNum) {
    if (!state.totalPages) return;
    const target = Math.max(1, Math.min(state.totalPages, Number(pageNum) || 1));
    state.currentPage = target;
    updateControls();

    if (state.scrollMode) {
      if (!state.scrollBuilt) buildContinuousScrollDOM();
      $('reader-loading').hidden = true;
      $('page-viewport').hidden = true;
      $('scroll-viewport').hidden = false;
      const card = $(`scroll-page-card-${target}`);
      if (card) {
        const img = card.querySelector('img[data-src]');
        if (img && !img.getAttribute('src')) {
          img.src = img.getAttribute('data-src');
        }
        card.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    } else {
      if ($('scroll-viewport')) $('scroll-viewport').hidden = true;
      renderSinglePage(target);
    }
  }

  function toggleScrollMode(forceMode) {
    state.scrollMode = typeof forceMode === 'boolean' ? forceMode : !state.scrollMode;
    try {
      localStorage.setItem('inst_pdf_scroll_mode', state.scrollMode ? '1' : '0');
    } catch (_) {}
    updateControls();
    goToPage(state.currentPage);
  }

  function toggleSidebar(forceState) {
    const sb = $('reader-sidebar');
    if (!sb) return;
    state.sidebarOpen = typeof forceState === 'boolean' ? forceState : !state.sidebarOpen;
    sb.hidden = !state.sidebarOpen;
    if ($('btn-toggle-sidebar')) {
      $('btn-toggle-sidebar').classList.toggle('active', state.sidebarOpen && state.activeTab === 'pages');
      $('btn-toggle-sidebar').setAttribute('aria-expanded', state.sidebarOpen ? 'true' : 'false');
    }
    if ($('btn-search-toggle')) {
      $('btn-search-toggle').classList.toggle('active', state.sidebarOpen && state.activeTab === 'search');
      $('btn-search-toggle').setAttribute('aria-expanded', state.sidebarOpen && state.activeTab === 'search' ? 'true' : 'false');
    }
  }

  function switchSidebarTab(tabName) {
    state.activeTab = tabName;
    const isPages = tabName === 'pages';
    if ($('tab-pages')) {
      $('tab-pages').classList.toggle('active', isPages);
      $('tab-pages').setAttribute('aria-selected', isPages ? 'true' : 'false');
    }
    if ($('tab-search')) {
      $('tab-search').classList.toggle('active', !isPages);
      $('tab-search').setAttribute('aria-selected', !isPages ? 'true' : 'false');
    }
    if ($('panel-pages')) $('panel-pages').hidden = !isPages;
    if ($('panel-search')) $('panel-search').hidden = isPages;
    toggleSidebar(true);
    if (!isPages && $('pdf-search-input')) {
      $('pdf-search-input').focus();
    }
  }

  async function executePdfSearch(queryText) {
    const q = (queryText || '').trim();
    const statusEl = $('pdf-search-status');
    const resultsEl = $('pdf-search-results');
    if (!statusEl || !resultsEl) return;

    resultsEl.replaceChildren();
    if (!q) {
      statusEl.textContent = 'Enter a word or phrase to search inside this document.';
      return;
    }

    statusEl.textContent = `Searching document for “${q}”…`;
    try {
      const sp = new URLSearchParams({
        book_id: state.bookId,
        library_id: state.libraryId,
        q
      });
      const r = await fetch(`/api/reader/search?${sp.toString()}`, { cache: 'no-store' });
      if (r.status === 401) {
        location.assign('/?login_required=1');
        return;
      }
      const data = await r.json();
      if (!r.ok) {
        statusEl.textContent = data.error || 'Search could not be completed.';
        return;
      }

      const hits = data.results || [];
      if (!hits.length) {
        statusEl.textContent = `No matches found for “${q}”.`;
        return;
      }

      statusEl.textContent = `Found ${data.total_matches} match${data.total_matches === 1 ? '' : 'es'} across ${hits.length} page${hits.length === 1 ? '' : 's'}:`;
      for (const hit of hits) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'search-hit';
        const title = document.createElement('strong');
        title.textContent = `Page ${hit.page}`;
        const snip = document.createElement('p');
        snip.textContent = hit.snippet || '';
        btn.append(title, snip);
        btn.onclick = () => {
          goToPage(hit.page);
          if (window.innerWidth <= 900) toggleSidebar(false);
        };
        resultsEl.appendChild(btn);
      }
    } catch (err) {
      statusEl.textContent = 'Error searching document. Please try again.';
    }
  }

  async function initReader() {
    if (!state.bookId || !/^\d+$/.test(state.bookId)) {
      showError('Invalid Publication Reference', 'No valid book identifier was provided.');
      return;
    }

    try {
      const q = new URLSearchParams({
        book_id: state.bookId,
        library_id: state.libraryId
      });
      const r = await fetch(`/api/reader/info?${q.toString()}`, { cache: 'no-store' });
      if (r.status === 401) {
        location.assign('/?login_required=1');
        return;
      }

      const data = await r.json().catch(() => ({}));
      if (!r.ok) {
        if (r.status === 403) {
          showError('Access Restricted', data.error || 'Your institutional account does not have permission to read this publication.');
        } else if (r.status === 404) {
          showError('PDF Not Available', data.error || 'This publication does not have a PDF file available for online reading.');
        } else if (r.status === 422) {
          showError('Corrupt or Unreadable PDF', data.error || 'The PDF file for this publication could not be parsed or is damaged.');
        } else {
          showError('Unable to Open Publication', data.error || 'An unexpected error occurred while loading the document.');
        }
        return;
      }

      state.title = data.title || 'Untitled Publication';
      state.libraryId = data.library_id || state.libraryId;
      state.totalPages = Number(data.page_count) || 1;

      applyBranding(data.branding);

      if ($('reader-book-title')) $('reader-book-title').textContent = state.title;
      const authorLine = Array.isArray(data.authors) && data.authors.length ? data.authors.join(', ') : '';
      const instName = data.branding?.institution_name || 'Digital Library';
      if ($('reader-book-subtitle')) {
        $('reader-book-subtitle').textContent = [authorLine, instName].filter(Boolean).join(' · ');
      }
      document.title = `${state.title} · ${instName}`;

      if ($('page-input')) {
        $('page-input').max = String(state.totalPages);
        $('page-input').value = '1';
      }
      if ($('page-total')) {
        $('page-total').textContent = String(state.totalPages);
      }

      if ($('btn-download-pdf')) {
        if (data.can_download) {
          const dlParams = new URLSearchParams({
            book_id: state.bookId,
            library_id: state.libraryId,
            download: '1'
          });
          $('btn-download-pdf').href = `/api/reader/stream?${dlParams.toString()}`;
          $('btn-download-pdf').hidden = false;
        } else {
          $('btn-download-pdf').hidden = true;
        }
      }

      buildPageList();
      goToPage(1);
    } catch (e) {
      showError('Connection Error', 'Could not reach the Institutional Library server. Please verify your connection.');
    }
  }

  // Event Listeners for Previous / Next across Topbar, Side Floating Arrows, and Bottom Bar
  ['btn-prev-page', 'floating-prev-btn', 'bottom-prev-btn'].forEach(id => {
    if ($(id)) {
      $(id).onclick = () => {
        if (state.currentPage > 1) goToPage(state.currentPage - 1);
      };
    }
  });

  ['btn-next-page', 'floating-next-btn', 'bottom-next-btn'].forEach(id => {
    if ($(id)) {
      $(id).onclick = () => {
        if (state.currentPage < state.totalPages) goToPage(state.currentPage + 1);
      };
    }
  });

  if ($('btn-scroll-mode')) {
    $('btn-scroll-mode').onclick = () => toggleScrollMode();
  }
  if ($('bottom-mode-btn')) {
    $('bottom-mode-btn').onclick = () => toggleScrollMode();
  }

  if ($('page-jump-form')) {
    $('page-jump-form').addEventListener('submit', e => {
      e.preventDefault();
      const val = Number($('page-input').value);
      if (val >= 1 && val <= state.totalPages) {
        goToPage(val);
      } else {
        $('page-input').value = String(state.currentPage);
      }
    });
  }

  if ($('page-input')) {
    $('page-input').addEventListener('change', () => {
      const val = Number($('page-input').value);
      if (val >= 1 && val <= state.totalPages) {
        goToPage(val);
      } else {
        $('page-input').value = String(state.currentPage);
      }
    });
  }

  if ($('btn-zoom-in')) {
    $('btn-zoom-in').onclick = () => {
      state.fitMode = 'custom';
      state.zoom = Math.min(250, state.zoom + 25);
      applyZoomGeometry();
    };
  }

  if ($('btn-zoom-out')) {
    $('btn-zoom-out').onclick = () => {
      state.fitMode = 'custom';
      state.zoom = Math.max(50, state.zoom - 25);
      applyZoomGeometry();
    };
  }

  if ($('btn-fit-width')) {
    $('btn-fit-width').onclick = () => {
      state.fitMode = 'width';
      state.zoom = 100;
      applyZoomGeometry();
    };
  }

  if ($('btn-fit-page')) {
    $('btn-fit-page').onclick = () => {
      state.fitMode = 'page';
      state.zoom = 100;
      if (state.scrollMode) toggleScrollMode(false);
      else applyZoomGeometry();
    };
  }

  if ($('btn-toggle-sidebar')) {
    $('btn-toggle-sidebar').onclick = () => {
      if (state.sidebarOpen && state.activeTab === 'pages') {
        toggleSidebar(false);
      } else {
        switchSidebarTab('pages');
      }
    };
  }

  if ($('btn-search-toggle')) {
    $('btn-search-toggle').onclick = () => {
      if (state.sidebarOpen && state.activeTab === 'search') {
        toggleSidebar(false);
      } else {
        switchSidebarTab('search');
      }
    };
  }

  if ($('btn-share-link')) {
    $('btn-share-link').onclick = () => {
      const shareUrl = location.href;
      const shareText = $('share-btn-text');
      navigator.clipboard?.writeText(shareUrl).then(() => {
        if (shareText) shareText.textContent = 'Copied!';
        setTimeout(() => { if (shareText) shareText.textContent = 'Share'; }, 2500);
      }).catch(() => {
        prompt('Copy direct book link:', shareUrl);
      });
    };
  }

  if ($('tab-pages')) $('tab-pages').onclick = () => switchSidebarTab('pages');
  if ($('tab-search')) $('tab-search').onclick = () => switchSidebarTab('search');

  if ($('pdf-search-form')) {
    $('pdf-search-form').addEventListener('submit', e => {
      e.preventDefault();
      executePdfSearch($('pdf-search-input').value);
    });
  }

  if ($('btn-fullscreen')) {
    $('btn-fullscreen').onclick = () => {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen?.().catch(() => {});
      } else {
        document.exitFullscreen?.().catch(() => {});
      }
    };
  }

  // Keyboard Accessibility
  document.addEventListener('keydown', e => {
    const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
    const inInput = activeTag === 'input' || activeTag === 'textarea' || activeTag === 'select';

    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') {
      e.preventDefault();
      switchSidebarTab('search');
      return;
    }

    if (e.key === 'Escape') {
      if (state.sidebarOpen) {
        toggleSidebar(false);
      }
      return;
    }

    if (inInput) return;

    if (e.key === 'ArrowRight' || (!state.scrollMode && e.key === 'PageDown')) {
      if (state.currentPage < state.totalPages) {
        e.preventDefault();
        goToPage(state.currentPage + 1);
      }
    } else if (e.key === 'ArrowLeft' || (!state.scrollMode && e.key === 'PageUp')) {
      if (state.currentPage > 1) {
        e.preventDefault();
        goToPage(state.currentPage - 1);
      }
    } else if (e.key === '+' || e.key === '=') {
      e.preventDefault();
      state.fitMode = 'custom';
      state.zoom = Math.min(250, state.zoom + 25);
      applyZoomGeometry();
    } else if (e.key === '-') {
      e.preventDefault();
      state.fitMode = 'custom';
      state.zoom = Math.max(50, state.zoom - 25);
      applyZoomGeometry();
    }
  });

  initReader();
})();
