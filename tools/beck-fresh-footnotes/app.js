const QUEUE_URL = "../../ocr/beck2020_fresh/review/footnote_review_queue.json";
const ACCEPTED_URL = "../../ocr/beck2020_fresh/review/accepted_footnote_links.csv";
const REJECTED_URL = "../../ocr/beck2020_fresh/review/rejected_footnote_candidates.csv";

const acceptedFields = [
  "page",
  "ref_xml_id",
  "note_xml_id",
  "n",
  "marker_bbox",
  "note_bbox",
  "confidence",
  "method",
  "reviewer",
];
const rejectedFields = [
  "page",
  "ref_xml_id",
  "note_xml_id",
  "n",
  "marker_bbox",
  "note_bbox",
  "reason",
  "method",
  "reviewer",
];

const els = {
  status: document.getElementById("status"),
  typeFilter: document.getElementById("typeFilter"),
  searchInput: document.getElementById("searchInput"),
  reviewerInput: document.getElementById("reviewerInput"),
  queueCount: document.getElementById("queueCount"),
  queueList: document.getElementById("queueList"),
  pageTitle: document.getElementById("pageTitle"),
  pageMeta: document.getElementById("pageMeta"),
  stageViewport: document.getElementById("stageViewport"),
  stage: document.getElementById("stage"),
  pageImage: document.getElementById("pageImage"),
  overlay: document.getElementById("overlay"),
  bodyToggle: document.getElementById("bodyToggle"),
  bottomToggle: document.getElementById("bottomToggle"),
  lowToggle: document.getElementById("lowToggle"),
  markerToggle: document.getElementById("markerToggle"),
  zoomOut: document.getElementById("zoomOut"),
  zoomReset: document.getElementById("zoomReset"),
  zoomIn: document.getElementById("zoomIn"),
  rowStatus: document.getElementById("rowStatus"),
  rowFacts: document.getElementById("rowFacts"),
  candidateList: document.getElementById("candidateList"),
  lineEvidence: document.getElementById("lineEvidence"),
  teiState: document.getElementById("teiState"),
  rejectReason: document.getElementById("rejectReason"),
  acceptButton: document.getElementById("acceptButton"),
  rejectButton: document.getElementById("rejectButton"),
  unresolvedButton: document.getElementById("unresolvedButton"),
  exportAccepted: document.getElementById("exportAccepted"),
  exportRejected: document.getElementById("exportRejected"),
  csvPreview: document.getElementById("csvPreview"),
};

const state = {
  payload: null,
  rows: [],
  filteredRows: [],
  activeIndex: 0,
  selectedCandidate: "",
  zoom: 0.56,
  accepted: [],
  rejected: [],
};

function csvEscape(value) {
  const text = value == null ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function toCsv(fields, rows) {
  return [
    fields.join(","),
    ...rows.map((row) => fields.map((field) => csvEscape(row[field] || "")).join(",")),
  ].join("\n") + "\n";
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (inQuotes && char === '"' && next === '"') {
      cell += '"';
      index += 1;
    } else if (char === '"') {
      inQuotes = !inQuotes;
    } else if (!inQuotes && char === ",") {
      row.push(cell);
      cell = "";
    } else if (!inQuotes && char === "\n") {
      row.push(cell);
      if (row.some(Boolean)) rows.push(row);
      row = [];
      cell = "";
    } else if (char !== "\r") {
      cell += char;
    }
  }
  if (cell || row.length) {
    row.push(cell);
    if (row.some(Boolean)) rows.push(row);
  }
  if (!rows.length) return [];
  const headers = rows.shift();
  return rows.map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] || ""])));
}

async function fetchText(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.text();
}

async function loadCsv(url) {
  try {
    return parseCsv(await fetchText(url));
  } catch (_error) {
    return [];
  }
}

function saveLocal() {
  localStorage.setItem("beckFreshFootnoteAccepted", JSON.stringify(state.accepted));
  localStorage.setItem("beckFreshFootnoteRejected", JSON.stringify(state.rejected));
}

function loadLocal() {
  try {
    const accepted = JSON.parse(localStorage.getItem("beckFreshFootnoteAccepted") || "[]");
    const rejected = JSON.parse(localStorage.getItem("beckFreshFootnoteRejected") || "[]");
    if (Array.isArray(accepted)) state.accepted = mergeRows(state.accepted, accepted, ["page", "ref_xml_id", "note_xml_id"]);
    if (Array.isArray(rejected)) state.rejected = mergeRows(state.rejected, rejected, ["page", "ref_xml_id", "note_xml_id", "reason"]);
  } catch (_error) {
    localStorage.removeItem("beckFreshFootnoteAccepted");
    localStorage.removeItem("beckFreshFootnoteRejected");
  }
}

function mergeRows(baseRows, addRows, keyFields) {
  const merged = [...baseRows];
  const indexByKey = new Map(merged.map((row, index) => [keyOf(row, keyFields), index]));
  for (const row of addRows) {
    const key = keyOf(row, keyFields);
    if (indexByKey.has(key)) {
      merged[indexByKey.get(key)] = row;
    } else {
      indexByKey.set(key, merged.length);
      merged.push(row);
    }
  }
  return merged;
}

function keyOf(row, fields) {
  return fields.map((field) => row[field] || "").join("\u001f");
}

function activeRow() {
  return state.filteredRows[state.activeIndex] || null;
}

function filteredRows() {
  const type = els.typeFilter.value;
  const query = els.searchInput.value.trim().toLowerCase();
  return state.rows.filter((row) => {
    if (type && row.problem_type !== type) return false;
    if (!query) return true;
    const haystack = [
      row.page,
      row.problem_type,
      row.status,
      row.raw_n,
      row.note?.text,
      row.qa?.note_excerpt,
      ...(row.marker_candidates || []).map((candidate) => `${candidate.base_text} ${candidate.marker_text} ${candidate.line_text}`),
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });
}

function renderQueue() {
  state.filteredRows = filteredRows();
  if (state.activeIndex >= state.filteredRows.length) state.activeIndex = Math.max(0, state.filteredRows.length - 1);
  els.queueCount.textContent = `${state.filteredRows.length} rows`;
  const fragment = document.createDocumentFragment();
  state.filteredRows.forEach((row, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `queue-row${index === state.activeIndex ? " is-active" : ""}`;
    button.innerHTML = "";
    const title = document.createElement("strong");
    title.textContent = `Page ${row.page}${row.raw_n ? ` / note ${row.raw_n}` : ""}`;
    const kind = document.createElement("span");
    kind.className = "kind";
    kind.textContent = row.problem_type;
    const excerpt = document.createElement("span");
    excerpt.textContent = row.note?.text || row.qa?.note_excerpt || row.marker_candidates?.[0]?.line_text || "";
    button.append(title, kind, excerpt);
    button.addEventListener("click", () => {
      state.activeIndex = index;
      state.selectedCandidate = row.marker_candidates?.[0]?.ref_xml_id || "";
      render();
    });
    fragment.append(button);
  });
  els.queueList.replaceChildren(fragment);
}

function parseBbox(value) {
  if (!value) return null;
  const parts = value.trim().split(/\s+/).map(Number);
  return parts.length === 4 && parts.every(Number.isFinite) ? parts : null;
}

function addBox(className, bbox, title) {
  const parsed = parseBbox(bbox);
  if (!parsed) return;
  const [left, top, right, bottom] = parsed;
  const box = document.createElement("div");
  box.className = `box ${className}`;
  box.style.left = `${left * state.zoom}px`;
  box.style.top = `${top * state.zoom}px`;
  box.style.width = `${Math.max(1, (right - left) * state.zoom)}px`;
  box.style.height = `${Math.max(1, (bottom - top) * state.zoom)}px`;
  if (title) box.title = title;
  els.overlay.append(box);
}

function renderImage(row) {
  const context = row?.page_context || {};
  const image = context.image || {};
  els.pageImage.src = image.src || "";
  els.pageImage.style.width = `${(image.width || 1) * state.zoom}px`;
  els.pageImage.style.height = `${(image.height || 1) * state.zoom}px`;
  els.overlay.style.width = `${(image.width || 1) * state.zoom}px`;
  els.overlay.style.height = `${(image.height || 1) * state.zoom}px`;
  renderOverlay(row);
}

function renderOverlay(row) {
  els.overlay.replaceChildren();
  if (!row) return;
  const context = row.page_context || {};
  const lines = context.lines || [];
  const selectedMarkerIds = new Set((row.marker_candidates || []).map((candidate) => candidate.ref_xml_id));
  if (els.bodyToggle.checked) {
    for (const line of lines) {
      if (!line.bottom_zone) addBox("line-box", line.bbox, `line ${line.index}`);
    }
  }
  if (els.bottomToggle.checked) {
    for (const separator of context.separators || []) {
      addBox("separator-box", separator, "footnote separator");
    }
    for (const line of lines) {
      if (line.bottom_zone) addBox("bottom-box", line.bbox, `bottom line ${line.index}`);
    }
    if (row.note?.bbox) addBox("note-box", row.note.bbox, row.note.text || "note");
  }
  if (els.lowToggle.checked) {
    for (const line of lines) {
      for (const word of line.words || []) {
        if (word.low_confidence) addBox("low-box", word.bbox, `${word.text} (${word.confidence})`);
      }
    }
  }
  if (els.markerToggle.checked) {
    for (const candidate of context.marker_candidates || []) {
      const visible = selectedMarkerIds.size === 0 || selectedMarkerIds.has(candidate.ref_xml_id);
      if (!visible) continue;
      addBox(`marker-box${candidate.high_confidence ? " is-high" : ""}`, candidate.bbox, candidate.line_text);
    }
  }
}

function renderFacts(row) {
  els.rowStatus.textContent = row ? row.problem_type : "No row";
  const facts = row
    ? [
        ["Page", row.page],
        ["Status", row.status],
        ["Method", row.method],
        ["Raw n", row.raw_n],
        ["Ref", row.qa?.ref_xml_id || ""],
        ["Note", row.note?.xml_id || row.qa?.note_xml_id || ""],
        ["Markers", row.qa?.marker_count || ""],
        ["Auto", row.qa?.auto_marker_count || ""],
      ]
    : [];
  const fragment = document.createDocumentFragment();
  for (const [key, value] of facts) {
    const dt = document.createElement("dt");
    dt.textContent = key;
    const dd = document.createElement("dd");
    dd.textContent = value || "";
    fragment.append(dt, dd);
  }
  els.rowFacts.replaceChildren(fragment);
}

function renderCandidates(row) {
  const fragment = document.createDocumentFragment();
  for (const candidate of row?.marker_candidates || []) {
    const label = document.createElement("label");
    label.className = "candidate";
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "candidate";
    radio.value = candidate.ref_xml_id;
    radio.checked = candidate.ref_xml_id === state.selectedCandidate;
    radio.addEventListener("change", () => {
      state.selectedCandidate = candidate.ref_xml_id;
      renderOverlay(row);
    });
    const body = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = `${candidate.base_text}[${candidate.marker_text}]`;
    const meta = document.createElement("small");
    meta.textContent = `${candidate.ref_xml_id} / line ${candidate.line}, word ${candidate.word} / ${candidate.high_confidence ? "auto" : "review"}`;
    const line = document.createElement("small");
    line.textContent = candidate.line_text || "";
    body.append(title, meta, line);
    label.append(radio, body);
    fragment.append(label);
  }
  if (!fragment.childNodes.length) {
    const empty = document.createElement("small");
    empty.textContent = "No marker candidate on this row.";
    fragment.append(empty);
  }
  els.candidateList.replaceChildren(fragment);
}

function renderLines(row) {
  const context = row?.page_context || {};
  const noteLine = Number(row?.note?.first_line || row?.qa?.note_first_line || 0);
  const candidateLines = new Set((row?.marker_candidates || []).map((candidate) => Number(candidate.line)));
  const wanted = [];
  for (const line of context.lines || []) {
    if (line.bottom_zone || candidateLines.has(Number(line.index)) || Math.abs(Number(line.index) - noteLine) <= 1) {
      wanted.push(line);
    }
  }
  const fragment = document.createDocumentFragment();
  for (const line of wanted) {
    const item = document.createElement("div");
    item.className = `line-row${line.bottom_zone ? " is-bottom" : ""}`;
    const title = document.createElement("strong");
    title.textContent = `Line ${line.index}`;
    const text = document.createElement("small");
    text.textContent = line.text;
    item.append(title, text);
    fragment.append(item);
  }
  els.lineEvidence.replaceChildren(fragment);
}

function renderTei(row) {
  const stateForPage = row?.current_tei || { refs: [], notes: [] };
  const fragment = document.createDocumentFragment();
  for (const ref of stateForPage.refs || []) {
    const item = document.createElement("div");
    item.className = "tei-item";
    item.append(metaLine("ref", `${ref.xml_id} -> ${ref.target} n=${ref.n}`), metaLine("", ref.text || ""));
    fragment.append(item);
  }
  for (const note of stateForPage.notes || []) {
    const item = document.createElement("div");
    item.className = "tei-item";
    item.append(
      metaLine("note", `${note.xml_id} -> ${note.corresp} n=${note.n} ${note.subtype}`),
      metaLine("", note.text || ""),
    );
    fragment.append(item);
  }
  if (!fragment.childNodes.length) fragment.append(metaLine("", "No current footnote TEI on this page."));
  els.teiState.replaceChildren(fragment);
}

function metaLine(label, text) {
  const small = document.createElement("small");
  small.textContent = label ? `${label}: ${text}` : text;
  return small;
}

function selectedCandidate(row) {
  const candidates = row?.marker_candidates || [];
  return candidates.find((candidate) => candidate.ref_xml_id === state.selectedCandidate) || candidates[0] || null;
}

function decisionBase(row, candidate) {
  return {
    page: String(row.page || ""),
    ref_xml_id: candidate?.ref_xml_id || row.qa?.ref_xml_id || "",
    note_xml_id: row.note?.xml_id || row.qa?.note_xml_id || "",
    n: row.raw_n || row.note?.n || row.qa?.raw_n || "",
    marker_bbox: candidate?.bbox || row.qa?.marker_bbox || "",
    note_bbox: row.note?.bbox || row.qa?.note_bbox || "",
  };
}

function acceptCurrent() {
  const row = activeRow();
  const candidate = selectedCandidate(row);
  if (!row || !candidate || !(row.note?.xml_id || row.qa?.note_xml_id)) return;
  const next = {
    ...decisionBase(row, candidate),
    confidence: candidate.high_confidence ? "1.0" : "0.8",
    method: "manual-review",
    reviewer: els.reviewerInput.value.trim() || "local-review",
  };
  state.accepted = mergeRows(state.accepted, [next], ["page", "ref_xml_id", "note_xml_id"]);
  saveLocal();
  previewAccepted();
}

function rejectCurrent(reason) {
  const row = activeRow();
  if (!row) return;
  const candidate = selectedCandidate(row);
  const next = {
    ...decisionBase(row, candidate),
    reason,
    method: "manual-review",
    reviewer: els.reviewerInput.value.trim() || "local-review",
  };
  state.rejected = mergeRows(state.rejected, [next], ["page", "ref_xml_id", "note_xml_id", "reason"]);
  saveLocal();
  previewRejected();
}

function previewAccepted() {
  els.csvPreview.value = toCsv(acceptedFields, state.accepted);
}

function previewRejected() {
  els.csvPreview.value = toCsv(rejectedFields, state.rejected);
}

function downloadCsv(filename, text) {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function render() {
  renderQueue();
  const row = activeRow();
  if (!row) {
    els.pageTitle.textContent = "Page";
    els.pageMeta.textContent = "";
    renderFacts(null);
    renderCandidates(null);
    renderLines(null);
    renderTei(null);
    renderImage(null);
    return;
  }
  if (!state.selectedCandidate) state.selectedCandidate = row.marker_candidates?.[0]?.ref_xml_id || "";
  els.pageTitle.textContent = `Page ${row.page}`;
  const context = row.page_context || {};
  const image = context.image || {};
  els.pageMeta.textContent = `${image.width || ""} x ${image.height || ""} / ${row.status}`;
  renderFacts(row);
  renderCandidates(row);
  renderLines(row);
  renderTei(row);
  renderImage(row);
}

async function boot() {
  const [payload, accepted, rejected] = await Promise.all([
    fetch(QUEUE_URL, { cache: "no-store" }).then((response) => {
      if (!response.ok) throw new Error(`${QUEUE_URL}: ${response.status}`);
      return response.json();
    }),
    loadCsv(ACCEPTED_URL),
    loadCsv(REJECTED_URL),
  ]);
  state.payload = payload;
  state.rows = payload.rows || [];
  state.accepted = accepted;
  state.rejected = rejected;
  loadLocal();
  els.status.textContent = `${state.rows.length} review rows from ${payload.source_files?.footnote_links || ""}`;
  state.filteredRows = filteredRows();
  state.selectedCandidate = state.filteredRows[0]?.marker_candidates?.[0]?.ref_xml_id || "";
  previewAccepted();
  render();
}

for (const control of [els.typeFilter, els.searchInput]) {
  control.addEventListener("input", () => {
    state.activeIndex = 0;
    state.selectedCandidate = "";
    render();
  });
}

for (const toggle of [els.bodyToggle, els.bottomToggle, els.lowToggle, els.markerToggle]) {
  toggle.addEventListener("change", () => renderOverlay(activeRow()));
}

els.zoomIn.addEventListener("click", () => {
  state.zoom = Math.min(2.5, state.zoom + 0.1);
  renderImage(activeRow());
});

els.zoomOut.addEventListener("click", () => {
  state.zoom = Math.max(0.2, state.zoom - 0.1);
  renderImage(activeRow());
});

els.zoomReset.addEventListener("click", () => {
  state.zoom = 0.56;
  renderImage(activeRow());
});

els.acceptButton.addEventListener("click", acceptCurrent);
els.rejectButton.addEventListener("click", () => rejectCurrent(els.rejectReason.value));
els.unresolvedButton.addEventListener("click", () => rejectCurrent("intentionally-unresolved"));
els.exportAccepted.addEventListener("click", () => {
  const text = toCsv(acceptedFields, state.accepted);
  els.csvPreview.value = text;
  downloadCsv("accepted_footnote_links.csv", text);
});
els.exportRejected.addEventListener("click", () => {
  const text = toCsv(rejectedFields, state.rejected);
  els.csvPreview.value = text;
  downloadCsv("rejected_footnote_candidates.csv", text);
});

let dragState = null;
els.stageViewport.addEventListener("mousedown", (event) => {
  if (event.button !== 0) return;
  dragState = {
    x: event.clientX,
    y: event.clientY,
    left: els.stageViewport.scrollLeft,
    top: els.stageViewport.scrollTop,
  };
  els.stageViewport.classList.add("is-dragging");
});

window.addEventListener("mousemove", (event) => {
  if (!dragState) return;
  els.stageViewport.scrollLeft = dragState.left - (event.clientX - dragState.x);
  els.stageViewport.scrollTop = dragState.top - (event.clientY - dragState.y);
});

window.addEventListener("mouseup", () => {
  dragState = null;
  els.stageViewport.classList.remove("is-dragging");
});

els.stageViewport.addEventListener(
  "wheel",
  (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    state.zoom = Math.max(0.2, Math.min(2.5, state.zoom + (event.deltaY < 0 ? 0.08 : -0.08)));
    renderImage(activeRow());
  },
  { passive: false },
);

boot().catch((error) => {
  els.status.textContent = `Could not load review queue: ${error.message}`;
});
