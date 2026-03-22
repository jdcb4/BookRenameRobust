/* BookTidy — Frontend Application */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let ws = null;
let currentTab = 'dashboard';
let selectedBookId = null;
let allModels = [];
let bookCounts = {};

// ---------------------------------------------------------------------------
// Theme
// ---------------------------------------------------------------------------
function initTheme() {
  const saved = localStorage.getItem('booktidy-theme');
  if (saved) {
    document.documentElement.setAttribute('data-theme', saved);
  } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
  updateThemeButton();
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('booktidy-theme', next);
  updateThemeButton();
}

function updateThemeButton() {
  const btn = document.getElementById('theme-toggle');
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  btn.textContent = isDark ? 'Light' : 'Dark';
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws/progress`);

  ws.onopen = () => {
    document.getElementById('ws-status').textContent = 'Connected';
    document.getElementById('ws-status').style.color = 'var(--success)';
  };

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      handleWSMessage(msg);
    } catch (err) { /* ignore */ }
  };

  ws.onclose = () => {
    document.getElementById('ws-status').textContent = 'Disconnected';
    document.getElementById('ws-status').style.color = 'var(--danger)';
    setTimeout(connectWS, 3000);
  };

  ws.onerror = () => ws.close();
}

let scanState = { phase: 'idle', total: 0, done: 0, errors: 0, epubCount: 0, dupeCount: 0, nonEpubCount: 0 };

function handleWSMessage(msg) {
  if (msg.type === 'scan_started') {
    scanState = { phase: 'scanning', total: 0, done: 0, errors: 0, epubCount: 0, dupeCount: 0, nonEpubCount: 0 };
    showProgress();
    setPhase('Scanning input folder...', false);
    appendLog(`Scan started (Job #${msg.job_id})`);
    document.getElementById('btn-scan').disabled = true;
    document.getElementById('btn-scan').textContent = 'Scanning...';
  } else if (msg.type === 'scan_classified') {
    scanState.epubCount = msg.epub_count;
    scanState.dupeCount = msg.duplicate_count;
    scanState.nonEpubCount = msg.non_epub_count;
    scanState.total = msg.epub_count;
    scanState.phase = 'processing';
    setPhase(`Processing ${msg.epub_count} books with LLM...`, false);
    setDetail(`0 of ${msg.epub_count} complete`, '');
    appendLog(`Found ${msg.epub_count} EPUBs, ${msg.non_epub_count} non-EPUB files, ${msg.duplicate_count} duplicates`);
    refreshCounts();
  } else if (msg.type === 'progress') {
    scanState.done = msg.done;
    scanState.errors = msg.errors;
    const pct = scanState.total > 0 ? Math.round((msg.done / scanState.total) * 100) : 0;
    setBar(pct, false);
    const errorText = msg.errors > 0 ? ` (${msg.errors} errors)` : '';
    setPhase(`Processing books... ${pct}%`, false);
    setDetail(`${msg.done} of ${scanState.total} complete${errorText}`, `${scanState.total - msg.done} remaining`);
    refreshCounts();
  } else if (msg.type === 'scan_completed') {
    scanState.phase = 'done';
    setPhase('Scan complete!', true);
    setBar(100, true);
    setDetail(`${scanState.done} books processed`, scanState.errors > 0 ? `${scanState.errors} errors` : 'No errors');
    appendLog('Scan completed!');
    document.getElementById('btn-scan').disabled = false;
    document.getElementById('btn-scan').textContent = 'Scan Input Folder';
    refreshCounts();
    refreshCurrentView();
    showCTABanner();
  } else if (msg.type === 'book_update') {
    const stateLabel = {
      'review': 'Needs review', 'auto_accepted': 'Auto-accepted',
      'flagged_quality': 'Quality flagged', 'non_english': 'Non-English',
      'error': 'Error', 'processing': 'Processing...'
    }[msg.state] || msg.state;
    appendLog(`${msg.file_name}: ${stateLabel}${msg.error ? ' - ' + msg.error : ''}`);
    if (msg.state !== 'processing') {
      refreshCounts();
    }
  }
}

function setPhase(text, done) {
  const el = document.getElementById('progress-phase');
  el.className = 'progress-phase' + (done ? ' done' : '');
  el.innerHTML = (done ? '&#10003; ' : '<span class="spinner"></span> ') + esc(text);
}

function setBar(pct, complete) {
  const bar = document.getElementById('progress-bar');
  bar.style.width = pct + '%';
  bar.className = 'progress-bar-inner' + (complete ? ' complete' : '');
}

function setDetail(left, right) {
  document.getElementById('progress-detail').innerHTML =
    `<span>${esc(left)}</span><span>${esc(right)}</span>`;
}

function showProgress() {
  document.getElementById('progress-container').classList.add('visible');
  document.getElementById('log-panel').style.display = 'block';
  document.getElementById('cta-banner').style.display = 'none';
}

function showCTABanner() {
  const banner = document.getElementById('cta-banner');
  const reviewCount = (bookCounts.review || 0) + (bookCounts.approved || 0);
  const flaggedCount = bookCounts.flagged_quality || 0;
  const nonEngCount = bookCounts.non_english || 0;
  const autoCount = (bookCounts.auto_accepted || 0) + (bookCounts.committed || 0);
  const errorCount = bookCounts.error || 0;

  // Only show if there's something to act on
  if (reviewCount + flaggedCount + nonEngCount + autoCount + errorCount === 0) {
    banner.style.display = 'none';
    return;
  }

  let items = [];
  if (reviewCount > 0) {
    items.push(`<div class="cta-item" onclick="switchTab('review')">
      <span class="cta-count review">${reviewCount}</span>
      <span>books need your review — click to open the Review Queue</span>
    </div>`);
  }
  if (flaggedCount > 0) {
    items.push(`<div class="cta-item" onclick="switchTab('flagged')">
      <span class="cta-count flagged">${flaggedCount}</span>
      <span>books have quality issues — review in Flagged Quality</span>
    </div>`);
  }
  if (nonEngCount > 0) {
    items.push(`<div class="cta-item" onclick="switchTab('non-english')">
      <span class="cta-count non-english">${nonEngCount}</span>
      <span>non-English books detected — review or skip</span>
    </div>`);
  }
  if (autoCount > 0) {
    items.push(`<div class="cta-item" onclick="switchTab('auto-processed')">
      <span class="cta-count auto">${autoCount}</span>
      <span>books auto-accepted with high confidence</span>
    </div>`);
  }
  if (errorCount > 0) {
    items.push(`<div class="cta-item" onclick="appendLog('Check errors in the log below')">
      <span class="cta-count error">${errorCount}</span>
      <span>books had errors during processing</span>
    </div>`);
  }

  banner.innerHTML = `<h3>Next Steps</h3><div class="cta-items">${items.join('')}</div>`;
  banner.style.display = 'block';

  // Show commit button if there are approved books
  const commitBtn = document.getElementById('btn-commit-all');
  if ((bookCounts.approved || 0) + (bookCounts.auto_accepted || 0) > 0) {
    commitBtn.style.display = 'inline-flex';
  }
}

function switchTab(tabName) {
  document.querySelectorAll('.tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === tabName);
  });
  currentTab = tabName;
  showView(tabName);
}

function appendLog(text) {
  const panel = document.getElementById('log-panel');
  panel.style.display = 'block';
  const time = new Date().toLocaleTimeString();
  panel.textContent += `[${time}] ${text}\n`;
  panel.scrollTop = panel.scrollHeight;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(err);
  }
  return resp.json();
}

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------
function toast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------
function initTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      currentTab = tab.dataset.tab;
      showView(currentTab);
    });
  });
}

function showView(name) {
  document.querySelectorAll('[id^="view-"]').forEach(v => v.style.display = 'none');
  const el = document.getElementById('view-' + name);
  if (el) el.style.display = 'block';
  closeSidePanel();
  refreshCurrentView();
}

function refreshCurrentView() {
  switch (currentTab) {
    case 'dashboard': loadDashboard(); break;
    case 'review': loadBooks('review'); break;
    case 'flagged': loadBooks('flagged_quality'); break;
    case 'non-english': loadBooks('non_english'); break;
    case 'duplicates': loadDuplicates(); break;
    case 'auto-processed': loadBooks('auto_accepted,committed'); break;
    case 'non-epub': loadNonEpub(); break;
    case 'settings': loadSettings(); break;
  }
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
async function loadDashboard() {
  await refreshCounts();
  const grid = document.getElementById('stats-grid');
  const items = [
    { key: 'total', label: 'Total EPUBs' },
    { key: 'auto_accepted', label: 'Auto-Processed', extra: 'committed' },
    { key: 'review', label: 'Pending Review', extra: 'approved' },
    { key: 'flagged_quality', label: 'Flagged Quality' },
    { key: 'non_english', label: 'Non-English' },
    { key: 'error', label: 'Errors' },
  ];
  grid.innerHTML = items.map(item => {
    let count = bookCounts[item.key] || 0;
    if (item.extra) count += (bookCounts[item.extra] || 0);
    return `<div class="stat-card"><div class="number">${count}</div><div class="label">${item.label}</div></div>`;
  }).join('');
}

async function refreshCounts() {
  try {
    bookCounts = await api('GET', '/api/books/counts');
    document.getElementById('badge-review').textContent = (bookCounts.review || 0) + (bookCounts.approved || 0);
    document.getElementById('badge-flagged').textContent = bookCounts.flagged_quality || 0;
    document.getElementById('badge-non-english').textContent = bookCounts.non_english || 0;
    document.getElementById('badge-auto').textContent = (bookCounts.auto_accepted || 0) + (bookCounts.committed || 0);

    // Duplicates and non-epub counts
    try {
      const dupes = await api('GET', '/api/duplicates');
      document.getElementById('badge-duplicates').textContent = dupes.duplicates?.length || 0;
    } catch (e) { /* ok */ }
    try {
      const ne = await api('GET', '/api/non-epub');
      document.getElementById('badge-non-epub').textContent = ne.files?.length || 0;
    } catch (e) { /* ok */ }
  } catch (e) { /* ok */ }
}

// ---------------------------------------------------------------------------
// Book list rendering
// ---------------------------------------------------------------------------
async function loadBooks(stateFilter) {
  try {
    const data = await api('GET', `/api/books?state=${stateFilter}`);
    const books = data.books || [];
    const listId = {
      'review': 'review-list',
      'flagged_quality': 'flagged-list',
      'non_english': 'non-english-list',
      'auto_accepted,committed': 'auto-list',
    }[stateFilter] || 'review-list';

    const container = document.getElementById(listId);
    if (books.length === 0) {
      container.innerHTML = '<p style="color:var(--text-muted);padding:20px">No books in this queue.</p>';
      return;
    }

    container.innerHTML = books.map(book => renderBookRow(book, stateFilter === 'review')).join('');

    // Attach click handlers
    container.querySelectorAll('.book-row').forEach(row => {
      row.addEventListener('click', (e) => {
        if (e.target.type === 'checkbox') return;
        openBookDetail(parseInt(row.dataset.id));
      });
    });
  } catch (e) {
    toast('Failed to load books: ' + e.message, 'error');
  }
}

function renderBookRow(book, showCheckbox = false) {
  const conf = book.overall_confidence || 0;
  const confClass = conf >= 0.9 ? 'conf-high' : conf >= 0.7 ? 'conf-medium' : 'conf-low';
  const confText = (conf * 100).toFixed(0) + '%';
  const secondary = book.llm_secondary_used ? '<span class="secondary-badge">2nd LLM</span>' : '';
  const quality = book.quality_ok === 0 ? '<span class="quality-badge">Quality Issue</span>' : '';
  const checkbox = showCheckbox ? `<input type="checkbox" class="book-checkbox" data-id="${book.id}">` : '<span></span>';
  const actions = renderRowActions(book);

  return `<div class="book-row" data-id="${book.id}">
    ${checkbox}
    <div>
      <div class="proposed">${esc(book.proposed_title || book.orig_title || book.file_name)}</div>
      <div class="filename">${esc(book.file_name)}</div>
    </div>
    <div class="author">${esc(book.proposed_author || book.orig_author || '')}</div>
    <div><span class="confidence-badge ${confClass}">${confText}</span></div>
    <div>${secondary}${quality}</div>
    <div>${actions}</div>
  </div>`;
}

function renderRowActions(book) {
  if (book.state === 'review' || book.state === 'flagged_quality' || book.state === 'non_english') {
    return `<button class="btn btn-success btn-sm" onclick="event.stopPropagation();quickApprove(${book.id})">Approve</button>
            <button class="btn btn-sm" onclick="event.stopPropagation();quickSkip(${book.id})">Skip</button>`;
  }
  if (book.state === 'auto_accepted' || book.state === 'committed') {
    return book.state === 'committed'
      ? `<button class="btn btn-sm" onclick="event.stopPropagation();quickUndo(${book.id})">Undo</button>`
      : '<span style="color:var(--success);font-size:12px">Auto-accepted</span>';
  }
  return '';
}

async function quickApprove(id) {
  try { await api('POST', `/api/books/${id}/approve`); toast('Book approved', 'success'); refreshCurrentView(); refreshCounts(); }
  catch (e) { toast(e.message, 'error'); }
}

async function quickSkip(id) {
  try { await api('POST', `/api/books/${id}/skip`); toast('Book skipped', 'info'); refreshCurrentView(); refreshCounts(); }
  catch (e) { toast(e.message, 'error'); }
}

async function quickUndo(id) {
  try { await api('POST', `/api/books/${id}/undo`); toast('Book undone', 'info'); refreshCurrentView(); refreshCounts(); }
  catch (e) { toast(e.message, 'error'); }
}

// ---------------------------------------------------------------------------
// Book Detail Side Panel
// ---------------------------------------------------------------------------
async function openBookDetail(bookId) {
  try {
    const book = await api('GET', `/api/books/${bookId}`);
    selectedBookId = bookId;
    const panel = document.getElementById('side-panel');
    const content = document.getElementById('side-panel-content');
    content.innerHTML = renderBookDetail(book);
    panel.classList.add('open');
    attachDetailHandlers(book);
  } catch (e) {
    toast('Failed to load book: ' + e.message, 'error');
  }
}

function closeSidePanel() {
  document.getElementById('side-panel').classList.remove('open');
  selectedBookId = null;
}

function renderBookDetail(book) {
  const qi = parseJSON(book.quality_issues);
  const flags = parseJSON(book.flags);
  const sanDiff = parseJSON(book.sanitisation_diff);
  const secondary = book.llm_secondary_used;

  let qualityBox = '';
  if (qi && qi.length > 0) {
    qualityBox = `<div class="warning-box"><strong>Quality Issues:</strong><ul>${qi.map(i => `<li>${esc(i)}</li>`).join('')}</ul></div>`;
  }

  let flagsBox = '';
  if (flags && flags.length > 0) {
    flagsBox = `<div class="warning-box" style="border-color:var(--warning)"><strong>Flags:</strong><ul>${flags.map(f => `<li>${esc(f)}</li>`).join('')}</ul></div>`;
  }

  return `
    <div class="side-panel-header">
      <h2>Book Detail</h2>
      <button class="close-btn" onclick="closeSidePanel()">&times;</button>
    </div>
    ${qualityBox}
    ${flagsBox}
    ${secondary ? '<div style="margin-bottom:12px"><span class="secondary-badge">Secondary LLM Used</span></div>' : ''}
    <table class="meta-table">
      <tr><th>Field</th><th>Original</th><th>Proposed</th></tr>
      ${metaRow('Title', book.orig_title, book.proposed_title, 'proposed_title', sanDiff)}
      ${metaRow('Author', book.orig_author, book.proposed_author, 'proposed_author', sanDiff)}
      ${metaRow('Series', book.orig_series, book.proposed_series, 'proposed_series', sanDiff)}
      ${metaRow('Series #', book.orig_series_index, book.proposed_series_index, 'proposed_series_index')}
      ${metaRow('Year', book.orig_date, book.proposed_year, 'proposed_year')}
      ${metaRow('Language', book.orig_language, book.proposed_language, 'proposed_language')}
      ${metaRow('Publisher', book.orig_publisher, book.proposed_publisher, 'proposed_publisher', sanDiff)}
      ${metaRow('Genre', '', book.proposed_genre, 'proposed_genre')}
      ${metaRow('Subgenre', '', book.proposed_subgenre, 'proposed_subgenre')}
    </table>

    <div style="margin-bottom:12px">
      <strong style="font-size:13px">Proposed Filename:</strong><br>
      <code style="font-size:12px;word-break:break-all">${esc(book.proposed_filename || '')}</code>
    </div>

    <div style="margin-bottom:12px;font-size:13px">
      <strong>Confidence:</strong>
      Title: ${pct(book.title_confidence)} |
      Author: ${pct(book.author_confidence)} |
      Overall: ${pct(book.overall_confidence)}
      ${book.confidence_notes ? `<br><em>${esc(book.confidence_notes)}</em>` : ''}
    </div>

    ${secondary ? renderSecondaryComparison(book) : ''}

    <div class="collapsible" id="text-sample-section">
      <div class="collapsible-header" onclick="toggleCollapsible('text-sample-section')">
        &#9654; Text Sample
      </div>
      <div class="collapsible-body">${esc(book.text_sample || 'No text sample')}</div>
    </div>

    <div class="collapsible" id="ol-data-section">
      <div class="collapsible-header" onclick="toggleCollapsible('ol-data-section')">
        &#9654; Open Library Data
      </div>
      <div class="collapsible-body">${esc(book.open_library_data || 'None')}</div>
    </div>

    <div class="collapsible" id="desc-section">
      <div class="collapsible-header" onclick="toggleCollapsible('desc-section')">
        &#9654; Description
      </div>
      <div class="collapsible-body">${esc(book.proposed_description || book.orig_description || 'None')}</div>
    </div>

    <div class="btn-group" style="margin-top:16px">
      ${book.state === 'review' || book.state === 'flagged_quality' || book.state === 'non_english' ? `
        <button class="btn btn-success" id="btn-detail-approve">Approve</button>
        <button class="btn" id="btn-detail-skip">Skip</button>
        <button class="btn btn-danger" id="btn-detail-reject">Reject</button>
      ` : ''}
      ${book.state === 'approved' ? `<button class="btn btn-primary" id="btn-detail-commit">Commit</button>` : ''}
      ${book.state === 'committed' || book.state === 'auto_accepted' ? `<button class="btn" id="btn-detail-undo">Undo</button>` : ''}
      <button class="btn" id="btn-detail-save">Save Changes</button>
    </div>
  `;
}

function metaRow(label, orig, proposed, field, sanDiff) {
  const diffMark = sanDiff && sanDiff[field] ? ' <span class="diff-marker">ASCII</span>' : '';
  const editableFields = ['proposed_title','proposed_author','proposed_series','proposed_series_index',
    'proposed_year','proposed_language','proposed_publisher','proposed_genre','proposed_subgenre'];
  const isEditable = editableFields.includes(field);
  const val = proposed != null ? proposed : '';
  const inputHtml = isEditable
    ? `<input type="text" class="detail-input" data-field="${field}" value="${esc(String(val))}">`
    : esc(String(val));
  return `<tr>
    <th>${label}</th>
    <td class="original">${esc(String(orig != null ? orig : ''))}</td>
    <td class="suggested">${inputHtml}${diffMark}</td>
  </tr>`;
}

function renderSecondaryComparison(book) {
  const fields = [
    ['Title', 'llm_primary_title', 'llm_secondary_title'],
    ['Author', 'llm_primary_author', 'llm_secondary_author'],
    ['Series', 'llm_primary_series', 'llm_secondary_series'],
    ['Genre', 'llm_primary_genre', 'llm_secondary_genre'],
    ['Subgenre', 'llm_primary_subgenre', 'llm_secondary_subgenre'],
  ];
  let rows = fields.map(([label, pKey, sKey]) => {
    const pVal = book[pKey] || '';
    const sVal = book[sKey] || '';
    const match = pVal.toLowerCase() === sVal.toLowerCase();
    const style = match ? '' : 'style="background:var(--bg-hover)"';
    return `<tr ${style}><th>${label}</th><td>${esc(pVal)}</td><td>${esc(sVal)}</td></tr>`;
  }).join('');
  return `<div class="collapsible" id="secondary-section">
    <div class="collapsible-header" onclick="toggleCollapsible('secondary-section')">
      &#9654; Secondary LLM Comparison
    </div>
    <div class="collapsible-body" style="overflow-x:auto">
      <table class="meta-table"><tr><th>Field</th><th>Primary</th><th>Secondary</th></tr>${rows}</table>
    </div>
  </div>`;
}

function attachDetailHandlers(book) {
  const approveBtn = document.getElementById('btn-detail-approve');
  const skipBtn = document.getElementById('btn-detail-skip');
  const rejectBtn = document.getElementById('btn-detail-reject');
  const commitBtn = document.getElementById('btn-detail-commit');
  const undoBtn = document.getElementById('btn-detail-undo');
  const saveBtn = document.getElementById('btn-detail-save');

  if (approveBtn) approveBtn.onclick = async () => {
    await saveDetailChanges(book.id);
    await quickApprove(book.id);
    closeSidePanel();
  };
  if (skipBtn) skipBtn.onclick = () => { quickSkip(book.id); closeSidePanel(); };
  if (rejectBtn) rejectBtn.onclick = () => {
    if (confirm('Reject this book?')) {
      api('POST', `/api/books/${book.id}/reject`).then(() => { toast('Rejected', 'info'); refreshCurrentView(); refreshCounts(); closeSidePanel(); });
    }
  };
  if (commitBtn) commitBtn.onclick = async () => {
    try {
      await api('POST', `/api/commit/${book.id}`);
      toast('Committed!', 'success');
      refreshCurrentView(); refreshCounts(); closeSidePanel();
    } catch (e) { toast(e.message, 'error'); }
  };
  if (undoBtn) undoBtn.onclick = () => { quickUndo(book.id); closeSidePanel(); };
  if (saveBtn) saveBtn.onclick = () => saveDetailChanges(book.id);
}

async function saveDetailChanges(bookId) {
  const inputs = document.querySelectorAll('.detail-input');
  const updates = {};
  inputs.forEach(input => {
    const field = input.dataset.field;
    const val = input.value.trim();
    if (field === 'proposed_series_index' || field === 'proposed_year') {
      updates[field] = val ? Number(val) : null;
    } else {
      updates[field] = val || null;
    }
  });
  try {
    await api('PUT', `/api/books/${bookId}/metadata`, updates);
    toast('Changes saved', 'success');
  } catch (e) {
    toast('Save failed: ' + e.message, 'error');
  }
}

function toggleCollapsible(id) {
  document.getElementById(id).classList.toggle('open');
}

// ---------------------------------------------------------------------------
// Duplicates
// ---------------------------------------------------------------------------
async function loadDuplicates() {
  try {
    const data = await api('GET', '/api/duplicates');
    const dupes = data.duplicates || [];
    const container = document.getElementById('duplicates-list');
    if (dupes.length === 0) {
      container.innerHTML = '<p style="color:var(--text-muted);padding:20px">No duplicates found.</p>';
      return;
    }
    // Group by md5
    const groups = {};
    dupes.forEach(d => {
      if (!groups[d.md5_hash]) groups[d.md5_hash] = { original: d.original_file_path, duplicates: [] };
      groups[d.md5_hash].duplicates.push(d.file_path);
    });
    container.innerHTML = Object.entries(groups).map(([hash, g]) => `
      <div style="background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:12px;margin-bottom:8px">
        <div style="font-size:12px;color:var(--text-muted)">MD5: ${hash}</div>
        <div style="font-weight:600;font-size:13px;margin:4px 0">Original: ${esc(g.original)}</div>
        ${g.duplicates.map(d => `<div style="font-size:13px;color:var(--danger);padding-left:16px">Duplicate: ${esc(d)}</div>`).join('')}
      </div>
    `).join('');
  } catch (e) {
    toast('Failed to load duplicates', 'error');
  }
}

// ---------------------------------------------------------------------------
// Non-EPUB files
// ---------------------------------------------------------------------------
async function loadNonEpub() {
  try {
    const data = await api('GET', '/api/non-epub');
    const files = data.files || [];
    const container = document.getElementById('non-epub-list');
    if (files.length === 0) {
      container.innerHTML = '<li style="color:var(--text-muted)">No non-EPUB files found.</li>';
      return;
    }
    container.innerHTML = files.map(f =>
      `<li><span>${esc(f.file_path)}</span><span style="color:var(--text-muted);font-size:12px">${f.file_extension} | ${formatBytes(f.file_size_bytes)}</span></li>`
    ).join('');
  } catch (e) {
    toast('Failed to load non-EPUB files', 'error');
  }
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
async function loadSettings() {
  try {
    const s = await api('GET', '/api/settings');
    document.getElementById('set-api-key').value = s.openrouter_api_key || '';
    document.getElementById('set-primary-model').value = s.openrouter_model_primary || '';
    document.getElementById('set-secondary-model').value = s.openrouter_model_secondary || '';
    document.getElementById('set-concurrency').value = s.llm_concurrency || 5;
    document.getElementById('concurrency-value').textContent = s.llm_concurrency || 5;
    document.getElementById('set-threshold').value = Math.round((s.auto_accept_threshold || 0.95) * 100);
    document.getElementById('threshold-value').textContent = (s.auto_accept_threshold || 0.95).toFixed(2);
    document.getElementById('set-input-dir').value = s.input_dir || '/input';
    document.getElementById('set-output-dir').value = s.output_dir || '/output';
  } catch (e) { /* ok */ }

  // Load models
  if (allModels.length === 0) {
    try {
      const data = await api('GET', '/api/models');
      allModels = data.models || [];
    } catch (e) { /* ok */ }
  }
}

async function saveSettings() {
  const data = {
    openrouter_api_key: document.getElementById('set-api-key').value,
    openrouter_model_primary: document.getElementById('set-primary-model').value,
    openrouter_model_secondary: document.getElementById('set-secondary-model').value,
    llm_concurrency: parseInt(document.getElementById('set-concurrency').value),
    auto_accept_threshold: parseInt(document.getElementById('set-threshold').value) / 100,
    input_dir: document.getElementById('set-input-dir').value,
    output_dir: document.getElementById('set-output-dir').value,
  };
  try {
    await api('PUT', '/api/settings', data);
    toast('Settings saved', 'success');
  } catch (e) {
    toast('Failed to save: ' + e.message, 'error');
  }
}

// ---------------------------------------------------------------------------
// Model selector
// ---------------------------------------------------------------------------
const PINNED_MODELS = [
  { id: 'google/gemini-3-flash-preview', name: 'Google - Gemini 3 Flash Preview (pinned default)' },
  { id: 'anthropic/claude-sonnet-4.6', name: 'Anthropic - Claude Sonnet 4.6 (pinned default)' },
];

function initModelSelector(inputId, dropdownId) {
  const input = document.getElementById(inputId);
  const dropdown = document.getElementById(dropdownId);

  input.addEventListener('focus', () => {
    renderModelDropdown(dropdown, input.value, inputId);
    dropdown.classList.add('open');
  });

  input.addEventListener('input', () => {
    renderModelDropdown(dropdown, input.value, inputId);
    dropdown.classList.add('open');
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('.model-selector')) {
      dropdown.classList.remove('open');
    }
  });
}

function renderModelDropdown(dropdown, query, inputId) {
  const q = (query || '').toLowerCase();
  const pinnedFiltered = PINNED_MODELS.filter(m => m.id.includes(q) || m.name.toLowerCase().includes(q));
  const pinnedIds = new Set(PINNED_MODELS.map(m => m.id));
  const othersFiltered = allModels.filter(m => !pinnedIds.has(m.id) && (m.id.includes(q) || (m.name || '').toLowerCase().includes(q)));

  let html = '';
  if (pinnedFiltered.length) {
    html += '<div class="model-group-label">Pinned Models</div>';
    html += pinnedFiltered.map(m =>
      `<div class="model-option" data-id="${m.id}" data-input="${inputId}">${m.name} <span class="context-len">${m.id}</span></div>`
    ).join('');
  }
  if (othersFiltered.length) {
    html += '<div class="model-group-label">All Models</div>';
    html += othersFiltered.map(m =>
      `<div class="model-option" data-id="${m.id}" data-input="${inputId}">${m.name || m.id}</div>`
    ).join('');
  }
  if (!html) html = '<div style="padding:8px;color:var(--text-muted);font-size:13px">No models found</div>';

  dropdown.innerHTML = html;
  dropdown.querySelectorAll('.model-option').forEach(opt => {
    opt.addEventListener('click', () => {
      document.getElementById(opt.dataset.input).value = opt.dataset.id;
      dropdown.classList.remove('open');
    });
  });
}

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------
function showModal(html) {
  document.getElementById('modal-content').innerHTML = html;
  document.getElementById('modal-overlay').classList.add('open');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
}

function showDeleteConfirmModal(title, items, onConfirm) {
  const itemsHtml = items.map(i => esc(i)).join('\n');
  showModal(`
    <h3>${esc(title)}</h3>
    <div class="file-preview">${itemsHtml}</div>
    <p style="font-size:13px;margin-bottom:8px">Type <strong>DELETE</strong> to confirm:</p>
    <input type="text" id="confirm-delete-input" placeholder="Type DELETE">
    <div class="btn-group">
      <button class="btn btn-danger" id="confirm-delete-btn">Delete</button>
      <button class="btn" onclick="closeModal()">Cancel</button>
    </div>
  `);
  document.getElementById('confirm-delete-btn').onclick = () => {
    if (document.getElementById('confirm-delete-input').value === 'DELETE') {
      onConfirm();
      closeModal();
    } else {
      toast('Type DELETE to confirm', 'error');
    }
  };
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------
function esc(str) {
  if (str == null) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}

function pct(val) {
  if (val == null) return 'N/A';
  return (val * 100).toFixed(0) + '%';
}

function parseJSON(str) {
  if (!str) return null;
  if (Array.isArray(str)) return str;
  try { return JSON.parse(str); } catch { return null; }
}

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  initTabs();
  connectWS();
  loadDashboard();

  // Theme toggle
  document.getElementById('theme-toggle').addEventListener('click', toggleTheme);

  // Scan button
  document.getElementById('btn-scan').addEventListener('click', async () => {
    try {
      document.getElementById('log-panel').textContent = '';
      const result = await api('POST', '/api/scan');
      toast(`Scan started (Job #${result.job_id})`, 'info');
      showProgress();
    } catch (e) {
      toast('Scan failed: ' + e.message, 'error');
    }
  });

  // Commit all
  document.getElementById('btn-commit-all').addEventListener('click', async () => {
    try {
      const result = await api('POST', '/api/commit');
      const successes = result.results.filter(r => r.success).length;
      const failures = result.results.filter(r => !r.success).length;
      toast(`Committed ${successes} books${failures > 0 ? `, ${failures} failed` : ''}`, successes > 0 ? 'success' : 'error');
      refreshCurrentView();
      refreshCounts();
    } catch (e) {
      toast('Commit failed: ' + e.message, 'error');
    }
  });

  // Select all / bulk approve
  document.getElementById('btn-select-all-review').addEventListener('click', () => {
    document.querySelectorAll('#review-list .book-checkbox').forEach(cb => cb.checked = !cb.checked);
  });

  document.getElementById('btn-bulk-approve').addEventListener('click', async () => {
    const ids = [];
    document.querySelectorAll('#review-list .book-checkbox:checked').forEach(cb => ids.push(parseInt(cb.dataset.id)));
    if (ids.length === 0) { toast('No books selected', 'info'); return; }
    try {
      await api('POST', '/api/books/bulk-approve', ids);
      toast(`${ids.length} books approved`, 'success');
      refreshCurrentView();
      refreshCounts();
    } catch (e) { toast(e.message, 'error'); }
  });

  // Delete non-epub
  document.getElementById('btn-delete-non-epub').addEventListener('click', async () => {
    try {
      const data = await api('GET', '/api/non-epub');
      const files = (data.files || []).map(f => f.file_path);
      if (files.length === 0) { toast('No files to delete', 'info'); return; }
      showDeleteConfirmModal('Delete Non-EPUB Files', files, async () => {
        try {
          const result = await api('DELETE', '/api/non-epub', { confirmed: true });
          toast(`Deleted ${result.count} files`, 'success');
          loadNonEpub();
          refreshCounts();
        } catch (e) { toast(e.message, 'error'); }
      });
    } catch (e) { toast(e.message, 'error'); }
  });

  // Delete duplicates
  document.getElementById('btn-delete-duplicates').addEventListener('click', async () => {
    try {
      const data = await api('GET', '/api/duplicates');
      const dupes = (data.duplicates || []).map(d => d.file_path);
      if (dupes.length === 0) { toast('No duplicates to delete', 'info'); return; }
      showDeleteConfirmModal('Delete Duplicate Files', dupes, async () => {
        try {
          const result = await api('DELETE', '/api/duplicates', { confirmed: true });
          toast(`Deleted ${result.count} duplicates`, 'success');
          loadDuplicates();
          refreshCounts();
        } catch (e) { toast(e.message, 'error'); }
      });
    } catch (e) { toast(e.message, 'error'); }
  });

  // Settings
  document.getElementById('btn-save-settings').addEventListener('click', saveSettings);

  document.getElementById('set-concurrency').addEventListener('input', (e) => {
    document.getElementById('concurrency-value').textContent = e.target.value;
  });

  document.getElementById('set-threshold').addEventListener('input', (e) => {
    document.getElementById('threshold-value').textContent = (e.target.value / 100).toFixed(2);
  });

  document.getElementById('btn-test-llm').addEventListener('click', async () => {
    const resultEl = document.getElementById('llm-test-result');
    resultEl.innerHTML = 'Testing...';
    try {
      const result = await api('POST', '/api/settings/test-llm');
      let html = '';
      for (const [key, r] of Object.entries(result)) {
        const icon = r.success ? '&#10003;' : '&#10007;';
        const color = r.success ? 'var(--success)' : 'var(--danger)';
        html += `<div style="color:${color}">${icon} ${esc(r.model)}: ${r.success ? r.latency_ms + 'ms' : r.error}</div>`;
      }
      resultEl.innerHTML = html;
    } catch (e) {
      resultEl.innerHTML = `<span style="color:var(--danger)">Test failed: ${esc(e.message)}</span>`;
    }
  });

  document.getElementById('btn-refresh-models').addEventListener('click', async () => {
    try {
      const data = await api('POST', '/api/settings/refresh-models');
      allModels = data.models || [];
      toast(`Loaded ${allModels.length} models`, 'success');
    } catch (e) {
      toast('Failed to refresh models: ' + e.message, 'error');
    }
  });

  // Model selectors
  initModelSelector('set-primary-model', 'primary-model-dropdown');
  initModelSelector('set-secondary-model', 'secondary-model-dropdown');

  // Close modal on overlay click
  document.getElementById('modal-overlay').addEventListener('click', (e) => {
    if (e.target === document.getElementById('modal-overlay')) closeModal();
  });
});
