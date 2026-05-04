(function () {
  "use strict";

  const REPO_ROOT = new URL("../", window.location.href);
  const EDITIONS_PATH = "editions.json";
  const XML_NS = "http://www.w3.org/XML/1998/namespace";
  const FALLBACK_EDITION = {
    id: "berendes1902",
    label: "Berendes 1902",
    tei: "output/berendes1902_epidoc.xml",
    manifest: "manifest.json",
    imageMode: "remote",
    localImageRoot: "images/raw/",
    imageLabelRoot: "images/raw/",
    sourceUrl: "https://digi.ub.uni-heidelberg.de/diglit/berendes1902",
    sourceLabel: "Heidelberg facsimile",
  };

  const els = {
    loadStatus: document.getElementById("loadStatus"),
    pageSelect: document.getElementById("pageSelect"),
    editionSelect: document.getElementById("editionSelect"),
    prevPage: document.getElementById("prevPage"),
    nextPage: document.getElementById("nextPage"),
    sectionList: document.getElementById("sectionList"),
    searchInput: document.getElementById("searchInput"),
    prevResult: document.getElementById("prevResult"),
    nextResult: document.getElementById("nextResult"),
    searchCount: document.getElementById("searchCount"),
    copyCorrection: document.getElementById("copyCorrection"),
    pageTitle: document.getElementById("pageTitle"),
    pageMeta: document.getElementById("pageMeta"),
    teiText: document.getElementById("teiText"),
    imageMeta: document.getElementById("imageMeta"),
    pageImage: document.getElementById("pageImage"),
    imageStage: document.getElementById("imageStage"),
    imageFallback: document.getElementById("imageFallback"),
    zoomOut: document.getElementById("zoomOut"),
    zoomReset: document.getElementById("zoomReset"),
    zoomIn: document.getElementById("zoomIn"),
    fitWidth: document.getElementById("fitWidth"),
    openImage: document.getElementById("openImage"),
    openFacs: document.getElementById("openFacs"),
    toast: document.getElementById("toast"),
  };

  const state = {
    manifest: null,
    pages: [],
    frontSections: [],
    books: [],
    chapters: [],
    currentIndex: 0,
    zoom: 1,
    imageFitMode: false,
    selectedContext: null,
    searchResults: [],
    activeResult: -1,
    toastTimer: null,
    xmlIdPages: new Map(),
    editions: [],
    edition: FALLBACK_EDITION,
  };

  function resolveRepoPath(path) {
    if (!path) return "";
    if (/^(?:https?:|data:|blob:)/i.test(path)) return path;
    return new URL(path.replace(/^\.?\//, ""), REPO_ROOT).href;
  }

  function localName(node) {
    return node.localName || node.nodeName;
  }

  function getXmlId(element) {
    return element.getAttributeNS(XML_NS, "id") || element.getAttribute("xml:id") || "";
  }

  function pageLabel(page) {
    if (!page) return "unknown page";
    const parts = [];
    if (page.n) parts.push(page.n);
    if (page.manifest && page.manifest.book_page && page.manifest.book_page !== page.n) {
      parts.push(`book ${page.manifest.book_page}`);
    }
    return parts.join(" / ") || `TEI page ${page.index + 1}`;
  }

  function sectionLabel(section) {
    if (!section) return "Unsectioned";
    if (section.kind === "book") return `Book ${section.n || section.id || "?"}`;
    return section.navTitle || section.title || section.n || section.id || section.subtype || section.type || "Section";
  }

  function chapterLabel(chapter) {
    if (!chapter) return "";
    return [chapter.n, chapter.navTitle || chapter.title].filter(Boolean).join(" ");
  }

  function pageChapterLabels(page) {
    return page.chapters.map(chapterLabel).filter(Boolean);
  }

  function pageChapterStartLabels(page) {
    return page.chapterStarts.map(chapterLabel).filter(Boolean);
  }

  function normalizeText(text) {
    return text.replace(/\s+/g, " ").trim();
  }

  function prepareRenderedTextClone(clone) {
    for (const lineNumber of clone.querySelectorAll(".line-number")) lineNumber.remove();
    for (const furniture of clone.querySelectorAll(".tei-fw")) {
      furniture.appendChild(document.createTextNode(" "));
    }
    for (const leftColumn of clone.querySelectorAll(".tei-abbr-left")) {
      leftColumn.appendChild(document.createTextNode(" "));
    }
    for (const abbreviationRow of clone.querySelectorAll(".tei-abbreviation-columns .tei-item")) {
      abbreviationRow.appendChild(document.createTextNode(" "));
    }
    return clone;
  }

  function normalizedRenderedText(node) {
    const clone = node.cloneNode(true);
    return normalizeText(prepareRenderedTextClone(clone).textContent || "");
  }

  function selectedText(selection) {
    if (!selection.rangeCount) return "";
    const fragment = selection.getRangeAt(0).cloneContents();
    return normalizeText(prepareRenderedTextClone(fragment).textContent || "");
  }

  function lineFromRenderedPosition(node, fallback = "") {
    function previousSiblingLine(start) {
      let sibling = start ? start.previousSibling : null;
      while (sibling) {
        if (sibling.nodeType === Node.ELEMENT_NODE) {
          if (sibling.classList.contains("tei-line")) return sibling.dataset.line || fallback;
          const nested = sibling.querySelector && sibling.querySelector(".tei-line:last-of-type");
          if (nested) return nested.dataset.line || fallback;
        }
        sibling = sibling.previousSibling;
      }
      return "";
    }

    const directLine = previousSiblingLine(node);
    if (directLine) return directLine;

    let current = node && node.nodeType === Node.ELEMENT_NODE ? node : node ? node.parentElement : null;
    while (current && current !== els.teiText) {
      if (current.classList && current.classList.contains("tei-line")) return current.dataset.line || fallback;
      const childLine = current.querySelector && current.querySelector(".tei-line");
      if (childLine) return childLine.dataset.line || fallback;
      const siblingLine = previousSiblingLine(current);
      if (siblingLine) return siblingLine;
      current = current.parentElement;
    }
    return fallback;
  }

  function classToken(value) {
    return value.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  }

  function romanNumber(value) {
    const roman = String(value || "").trim().toUpperCase();
    if (!/^[IVXLCDM]+$/.test(roman)) return null;
    const values = { I: 1, V: 5, X: 10, L: 50, C: 100, D: 500, M: 1000 };
    let total = 0;
    for (let index = 0; index < roman.length; index += 1) {
      const current = values[roman[index]];
      const next = values[roman[index + 1]] || 0;
      total += current < next ? -current : current;
    }
    return total > 0 ? total : null;
  }

  function printedPageNumber(value) {
    const text = String(value || "").trim();
    const numeric = Number(text);
    if (Number.isInteger(numeric)) return numeric;
    return romanNumber(text);
  }

  function pageNumberValue(page) {
    if (!page) return null;
    return printedPageNumber(page.n) || printedPageNumber(page.manifest && page.manifest.book_page);
  }

  function setTopFurnitureSide(row, number) {
    row.classList.remove("tei-page-even", "tei-page-odd");
    if (!Number.isInteger(number)) return;
    row.classList.add(number % 2 === 0 ? "tei-page-even" : "tei-page-odd");
  }

  function isTopFurniture(element) {
    if (localName(element) !== "fw") return false;
    const place = element.getAttribute("place") || "";
    return place === "top" || place.startsWith("top-");
  }

  function makeManifestLookups(manifest) {
    const byFacs = new Map();
    const byBookPage = new Map();
    const pages = Array.isArray(manifest.pages) ? manifest.pages : [];
    for (const page of pages) {
      if (page.facs) byFacs.set(page.facs, page);
      if (page.tei_facs) byFacs.set(page.tei_facs, page);
      if (page.book_page) byBookPage.set(String(page.book_page), page);
    }
    return { byFacs, byBookPage };
  }

  function nearestManifest(pb, lookups) {
    const facs = pb.getAttribute("facs") || "";
    const n = pb.getAttribute("n") || "";
    return lookups.byFacs.get(facs) || lookups.byBookPage.get(n) || null;
  }

  function directSectionHead(div) {
    const heads = Array.from(div.children).filter((child) => localName(child) === "head");
    return heads.find((head) => head.getAttribute("type") === "section") || heads[0] || null;
  }

  function extractTitle(div) {
    const directHead = directSectionHead(div);
    return directHead ? normalizeText(directHead.textContent || "") : "";
  }

  function extractNavTitle(div, title) {
    const directHead = directSectionHead(div);
    if (directHead) {
      const hi = Array.from(directHead.getElementsByTagNameNS("*", "hi")).find((el) => {
        return (el.getAttribute("rend") || "").toLowerCase().split(/\s+/).includes("bold");
      });
      if (hi) return normalizeText(hi.textContent || "").replace(/[.。]+$/, "");
    }
    return title
      .replace(/^Cap\.\s*[-\d.()]+\.?\s*/i, "")
      .replace(/Περὶ[^.]*\./g, "")
      .replace(/\s+/g, " ")
      .replace(/[.。]+$/, "")
      .trim();
  }

  function buildSection(div, parent, kind, book) {
    const title = extractTitle(div);
    const n = div.getAttribute("n") || "";
    if (kind === "front" && n) {
      const existing = state.frontSections.find((section) => section.n === n);
      if (existing) return existing;
    }
    const section = {
      id: getXmlId(div),
      n,
      type: div.getAttribute("type") || "",
      subtype: div.getAttribute("subtype") || "",
      title,
      navTitle: extractNavTitle(div, title),
      kind,
      parent,
      book: book || null,
      chapters: [],
      currentChapter: null,
      firstPageIndex: null,
    };
    if (kind === "book") state.books.push(section);
    else if (kind === "chapter") {
      state.chapters.push(section);
      if (book) book.chapters.push(section);
    } else if (kind === "front") state.frontSections.push(section);
    return section;
  }

  function addUnique(list, item) {
    if (item && !list.includes(item)) list.push(item);
  }

  function markSectionPage(section, page) {
    if (section && section.firstPageIndex === null) section.firstPageIndex = page.index;
  }

  function registerBookOnPage(book, page) {
    if (!book || !page) return;
    page.book = book;
    markSectionPage(book, page);
  }

  function registerChapterOnPage(chapter, page, startsHere = false) {
    if (!chapter || !page) return;
    const firstSeen = chapter.firstPageIndex === null;
    addUnique(page.chapters, chapter);
    page.activeChapter = chapter;
    markSectionPage(chapter, page);
    if (startsHere || firstSeen) addUnique(page.chapterStarts, chapter);
  }

  function registerFrontOnPage(section, page) {
    if (!section || !page || section.kind !== "front") return;
    page.frontSection = section;
    markSectionPage(section, page);
  }

  function createPage(pb, context, lookups) {
    const manifest = nearestManifest(pb, lookups);
    const page = {
      index: state.pages.length,
      n: pb.getAttribute("n") || "",
      facs: pb.getAttribute("facs") || "",
      manifest,
      section: context.chapter || context.book || context.frontSection || null,
      frontSection: context.frontSection || null,
      book: context.book || null,
      activeChapter: context.chapter || null,
      chapters: [],
      chapterStarts: [],
      fragment: document.createDocumentFragment(),
      plainText: "",
      firstLine: "",
    };

    const boundary = document.createElement("div");
    boundary.className = "tei-page-boundary";
    boundary.textContent = `Page ${pageLabel(page)}`;
    page.fragment.appendChild(boundary);

    state.pages.push(page);
    registerFrontOnPage(context.frontSection, page);
    registerBookOnPage(context.book, page);
    registerChapterOnPage(context.chapter, page, context.chapter && context.chapter.firstPageIndex === page.index);
    return page;
  }

  function contextFromElement(element) {
    const pageIndex = Number(element.dataset.pageIndex);
    const page = state.pages[pageIndex] || state.pages[state.currentIndex];
    return {
      pageIndex: page ? page.index : state.currentIndex,
      line: lineFromRenderedPosition(element, element.dataset.line || ""),
      divId: element.dataset.divId || nearestSectionId(page),
      text: normalizedRenderedText(element),
    };
  }

  function nearestSectionId(page) {
    if (!page) return "";
    return (page.activeChapter && page.activeChapter.id) || (page.book && page.book.id) || (page.frontSection && page.frontSection.id) || "";
  }

  function chapterById(id) {
    return id ? state.chapters.find((chapter) => chapter.id === id) || null : null;
  }

  function decorateContext(element, page, context) {
    element.dataset.pageIndex = String(page.index);
    const section = context.chapter || context.book || context.frontSection || null;
    if (section && section.id) element.dataset.divId = section.id;
  }

  function isInlineContentNode(node) {
    if (!node) return false;
    if (node.nodeType === Node.TEXT_NODE) return Boolean((node.nodeValue || "").trim());
    if (node.nodeType !== Node.ELEMENT_NODE) return false;
    return !isBlockElement(node) && !["pb", "lb"].includes(localName(node));
  }

  function significantSibling(node, direction) {
    let sibling = node ? node[direction] : null;
    while (sibling && sibling.nodeType === Node.TEXT_NODE && !(sibling.nodeValue || "").trim()) {
      sibling = sibling[direction];
    }
    return sibling;
  }

  function shouldPreserveInlineWhitespace(node) {
    const text = node.nodeValue || "";
    if (!text || text.trim()) return false;
    const previous = significantSibling(node, "previousSibling");
    const next = significantSibling(node, "nextSibling");
    return isInlineContentNode(previous) && isInlineContentNode(next);
  }

  function appendText(container, page, text, preserveWhitespace = false) {
    const trimmed = text.replace(/[ \t\r\n]+/g, " ");
    if (trimmed.trim()) {
      container.appendChild(document.createTextNode(trimmed));
      page.plainText += ` ${normalizeText(trimmed)}`;
    } else if (preserveWhitespace && !(container.textContent || "").endsWith(" ")) {
      container.appendChild(document.createTextNode(" "));
      page.plainText += " ";
    }
  }

  function makeRenderedElement(source, page, context) {
    const name = localName(source);
    const isBlock = isBlockElement(source);
    const element = document.createElement(isBlock ? (name === "head" ? "h3" : "div") : name === "ref" ? "a" : "span");
    const type = source.getAttribute("type") || "";
    element.className = `${isBlock ? "tei-block " : ""}tei-${name}`;
    const typeToken = classToken(type);
    if (typeToken) element.classList.add(`tei-${typeToken}`);
    const placeToken = classToken(source.getAttribute("place") || "");
    if (placeToken) element.classList.add(`tei-place-${placeToken}`);
    if (name === "note" && type === "footnote") element.classList.add("tei-footnote");
    decorateContext(element, page, context);
    const sourceId = getXmlId(source);
    if (sourceId) {
      element.id = sourceId;
      state.xmlIdPages.set(sourceId, page.index);
    }

    if (name === "foreign") {
      const lang = source.getAttributeNS(XML_NS, "lang") || source.getAttribute("xml:lang") || source.getAttribute("lang") || "";
      if (lang) element.setAttribute("lang", lang);
    }

    if (name === "hi") {
      const rend = (source.getAttribute("rend") || "").toLowerCase();
      for (const token of rend.split(/\s+/).map(classToken).filter(Boolean)) {
        element.classList.add(`tei-hi-${token}`);
      }
    }

    if (name === "ref") element.setAttribute("href", source.getAttribute("target") || "#");
    if (name === "note" && type === "footnote") {
      const label = source.getAttribute("n") || "";
      if (label) {
        const labelElement = document.createElement("span");
        labelElement.className = "footnote-label";
        labelElement.textContent = label;
        element.appendChild(labelElement);
      }
      const correspPages = Array.from(new Set((source.getAttribute("corresp") || "")
        .split(/\s+/)
        .map((token) => token.replace(/^#/, ""))
        .map((id) => state.xmlIdPages.get(id))
        .filter((index) => Number.isInteger(index))));
      const otherPages = correspPages.filter((index) => index !== page.index);
      if (otherPages.length) {
        element.classList.add("tei-cross-page-footnote");
        element.title = `Footnote anchor on page ${otherPages.map((index) => pageLabel(state.pages[index])).join(", ")}`;
      }
    }
    if (context.lineTracker.current) element.dataset.line = context.lineTracker.current;
    return element;
  }

  function isBlockElement(element) {
    return ["ab", "p", "head", "note", "fw", "lg", "list", "item", "quote"].includes(localName(element));
  }

  function appendLineBreak(context) {
    const page = context.currentPage;
    const parent = context.container;
    if (!page || !parent) return;
    if (parent.childNodes.length) parent.appendChild(document.createElement("br"));
    const line = context.pendingLineElement.getAttribute("n") || "";
    if (line && !page.firstLine) page.firstLine = line;
    context.lineTracker.current = line;
    const anchor = document.createElement("span");
    anchor.className = "tei-line";
    anchor.dataset.pageIndex = String(page.index);
    anchor.dataset.line = line;
    decorateContext(anchor, page, context);
    if (line) {
      const num = document.createElement("span");
      num.className = "line-number";
      num.textContent = line;
      anchor.appendChild(num);
    }
    parent.appendChild(anchor);
  }

  function restoreRenderedFrames(context) {
    let parent = context.currentPage.fragment;
    for (const frame of context.frames) {
      const element = makeRenderedElement(frame.source, context.currentPage, frame.context);
      parent.appendChild(element);
      frame.element = element;
      parent = element;
    }
    context.container = parent;
  }

  function switchPage(pb, context, lookups) {
    const facs = pb.getAttribute("facs") || "";
    const n = pb.getAttribute("n") || "";
    if (context.currentPage && facs && facs === context.currentPage.facs) {
      if (context.chapter) registerChapterOnPage(context.chapter, context.currentPage, true);
      else if (context.book) registerBookOnPage(context.book, context.currentPage);
      else if (context.frontSection) registerFrontOnPage(context.frontSection, context.currentPage);
      context.currentPage.section = context.chapter || context.book || context.frontSection || context.currentPage.section;
      if (n && !context.currentPage.n) context.currentPage.n = n;
      context.topFurnitureRow = null;
      return;
    }
    context.currentPage = createPage(pb, context, lookups);
    context.topFurnitureRow = null;
    restoreRenderedFrames(context);
  }

  function startsWithPageBreak(div) {
    for (const child of div.childNodes) {
      if (child.nodeType === Node.TEXT_NODE && !(child.nodeValue || "").trim()) continue;
      return child.nodeType === Node.ELEMENT_NODE && localName(child) === "pb";
    }
    return false;
  }

  function enterSection(div, context) {
    const subtype = div.getAttribute("subtype") || "";
    const startsNewPage = startsWithPageBreak(div);
    const next = { ...context };
    if (subtype === "book") {
      const book = buildSection(div, null, "book", null);
      next.book = book;
      next.chapter = null;
      next.frontSection = null;
      if (next.currentPage && !startsNewPage) registerBookOnPage(book, next.currentPage);
    } else if (subtype === "chapter") {
      const chapter = buildSection(div, context.book, "chapter", context.book);
      next.chapter = chapter;
      if (context.book) context.book.currentChapter = chapter;
      if (next.currentPage && !startsNewPage) registerChapterOnPage(chapter, next.currentPage, true);
    } else if (subtype === "continuation" && context.book && context.book.currentChapter) {
      next.chapter = context.book.currentChapter;
      if (next.currentPage && !startsNewPage) registerChapterOnPage(next.chapter, next.currentPage, false);
    } else if (!context.book) {
      const front = buildSection(div, context.frontSection, "front", null);
      next.frontSection = front;
      if (next.currentPage && !startsNewPage) registerFrontOnPage(front, next.currentPage);
    }
    if (next.currentPage && !startsNewPage) next.currentPage.section = next.chapter || next.book || next.frontSection || next.currentPage.section;
    return next;
  }

  function appendTopFurniture(source, context, lookups) {
    const page = context.currentPage;
    if (!page || !context.container) return;

    if (!context.topFurnitureRow || context.topFurnitureRow.parentNode !== context.container) {
      const row = document.createElement("div");
      row.className = "tei-top-furniture";
      decorateContext(row, page, context);
      setTopFurnitureSide(row, pageNumberValue(page));
      context.container.appendChild(row);
      context.topFurnitureRow = row;
    }

    const frameContext = {
      book: context.book,
      chapter: context.chapter,
      frontSection: context.frontSection,
      lineTracker: { current: "" },
    };
    const rendered = makeRenderedElement(source, page, frameContext);
    rendered.classList.remove("tei-block");
    context.topFurnitureRow.appendChild(rendered);

    if ((source.getAttribute("type") || "") === "pageNum") {
      setTopFurnitureSide(context.topFurnitureRow, printedPageNumber(source.textContent));
    }

    const childContext = {
      ...context,
      container: rendered,
      topFurnitureRow: null,
      lineTracker: frameContext.lineTracker,
    };
    for (const child of source.childNodes) {
      if (child.nodeType === Node.ELEMENT_NODE && localName(child) === "lb") continue;
      processNode(child, childContext, lookups);
    }
  }

  function processNode(node, context, lookups) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (context.currentPage && context.container) {
        if ((node.nodeValue || "").trim()) context.topFurnitureRow = null;
        appendText(context.container, context.currentPage, node.nodeValue || "", shouldPreserveInlineWhitespace(node));
      }
      return context;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return context;

    const name = localName(node);
    if (name === "pb") {
      switchPage(node, context, lookups);
      return context;
    }
    if (name === "div") {
      const sectionContext = enterSection(node, context);
      for (const child of node.childNodes) processNode(child, sectionContext, lookups);
      context.currentPage = sectionContext.currentPage;
      context.container = sectionContext.container;
      context.topFurnitureRow = sectionContext.topFurnitureRow;
      return context;
    }
    if (name === "lb") {
      context.topFurnitureRow = null;
      context.pendingLineElement = node;
      appendLineBreak(context);
      context.pendingLineElement = null;
      return context;
    }
    if (isTopFurniture(node)) {
      appendTopFurniture(node, context, lookups);
      return context;
    }
    context.topFurnitureRow = null;

    const shouldRender = context.currentPage && (isBlockElement(node) || context.frames.length > 0);
    if (!shouldRender) {
      for (const child of node.childNodes) processNode(child, context, lookups);
      return context;
    }

    const frameContext = {
      book: context.book,
      chapter: context.chapter,
      frontSection: context.frontSection,
      lineTracker: context.lineTracker,
    };
    const rendered = makeRenderedElement(node, context.currentPage, frameContext);
    context.container.appendChild(rendered);
    const previousContainer = context.container;
    const frame = { source: node, context: frameContext, element: rendered };
    context.frames.push(frame);
    context.container = rendered;

    for (const child of node.childNodes) processNode(child, context, lookups);

    context.frames.pop();
    const parentFrame = context.frames[context.frames.length - 1];
    context.container = parentFrame ? parentFrame.element : context.currentPage ? context.currentPage.fragment : previousContainer;
    return context;
  }

  function extractPages(teiDoc, manifest) {
    const lookups = makeManifestLookups(manifest);
    const text = teiDoc.getElementsByTagNameNS("*", "text")[0] || teiDoc.documentElement;
    state.pages = [];
    state.frontSections = [];
    state.books = [];
    state.chapters = [];
    state.xmlIdPages = new Map();

    const context = {
      currentPage: null,
      container: null,
      frames: [],
      book: null,
      chapter: null,
      frontSection: null,
      lineTracker: { current: "" },
      pendingLineElement: null,
      topFurnitureRow: null,
    };

    for (const child of text.childNodes) processNode(child, context, lookups);
    state.frontSections = state.frontSections.filter((section) => section.firstPageIndex !== null);
    state.books = state.books.filter((section) => section.firstPageIndex !== null);
    state.chapters = state.chapters.filter((section) => section.firstPageIndex !== null);
  }

  async function loadText(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`Could not load ${path}: HTTP ${response.status}`);
    return response.text();
  }

  async function loadJson(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`Could not load ${path}: HTTP ${response.status}`);
    return response.json();
  }

  async function loadEditionRegistry() {
    try {
      const registry = await loadJson(resolveRepoPath(EDITIONS_PATH));
      const editions = Array.isArray(registry.editions) ? registry.editions : [];
      state.editions = editions.length ? editions : [FALLBACK_EDITION];
      const requested = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("edition");
      const defaultId = requested || registry.defaultEdition || FALLBACK_EDITION.id;
      state.edition = state.editions.find((edition) => edition.id === defaultId) || state.editions[0];
    } catch (error) {
      console.warn("Edition registry unavailable; using fallback edition", error);
      state.editions = [FALLBACK_EDITION];
      state.edition = FALLBACK_EDITION;
    }
  }

  function populateEditionSelect() {
    els.editionSelect.innerHTML = "";
    for (const edition of state.editions) {
      const option = document.createElement("option");
      option.value = edition.id;
      option.textContent = edition.label || edition.id;
      els.editionSelect.appendChild(option);
    }
    els.editionSelect.value = state.edition.id;
    els.editionSelect.disabled = state.editions.length <= 1;
  }

  async function loadEdition(edition, options = {}) {
    state.edition = edition || state.edition || FALLBACK_EDITION;
    state.selectedContext = null;
    state.searchResults = [];
    state.activeResult = -1;
    state.currentIndex = 0;
    els.copyCorrection.disabled = true;
    els.searchInput.disabled = true;
    els.searchCount.textContent = "0/0";
    els.loadStatus.classList.remove("error");
    els.loadStatus.textContent = `Loading ${state.edition.label || state.edition.id}...`;

    const [teiText, manifest] = await Promise.all([
      loadText(resolveRepoPath(state.edition.tei)),
      loadJson(resolveRepoPath(state.edition.manifest)),
    ]);
    const teiDoc = new DOMParser().parseFromString(teiText, "application/xml");
    const parseError = parserErrorText(teiDoc);
    if (parseError) throw new Error(parseError);

    state.manifest = manifest;
    extractPages(teiDoc, manifest);
    if (!state.pages.length) throw new Error("No TEI page breaks found.");
    populateEditionSelect();
    populatePageSelect();
    populateSections();
    els.searchInput.disabled = false;
    document.title = `${state.edition.label || state.edition.id} · Dioscorides Viewer`;
    els.loadStatus.textContent = `${state.pages.length} TEI pages loaded from ${state.edition.label || state.edition.id}`;
    const initialPage = options.pageIndex ?? pageFromHash();
    showPage(initialPage >= 0 ? initialPage : 0, { skipHash: options.skipHash || initialPage >= 0 });
  }

  function parserErrorText(doc) {
    const error = doc.getElementsByTagName("parsererror")[0];
    return error ? normalizeText(error.textContent || "XML parser error") : "";
  }

  function populatePageSelect() {
    els.pageSelect.innerHTML = "";
    for (const page of state.pages) {
      const option = document.createElement("option");
      option.value = String(page.index);
      const pdf = page.manifest && page.manifest.pdf_page ? `PDF ${page.manifest.pdf_page}` : "PDF ?";
      const section = page.activeChapter
        ? chapterLabel(page.activeChapter)
        : page.book
          ? sectionLabel(page.book)
          : page.frontSection
            ? sectionLabel(page.frontSection)
            : page.manifest && page.manifest.section
              ? page.manifest.section
              : sectionLabel(page.section);
      option.textContent = `${pageLabel(page)} · ${pdf} · ${section}`;
      els.pageSelect.appendChild(option);
    }
    els.pageSelect.disabled = state.pages.length === 0;
  }

  function makeSectionButton(section, className, label, meta) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `section-button ${className || ""}`.trim();
    button.dataset.pageIndex = String(section.firstPageIndex);
    button.dataset.sectionId = section.id || "";
    button.dataset.kind = section.kind || "";
    if (section.book && section.book.id) button.dataset.bookId = section.book.id;
    button.innerHTML = `<span class="label"></span><span class="meta"></span>`;
    button.querySelector(".label").textContent = label || sectionLabel(section);
    button.querySelector(".meta").textContent = meta || "";
    button.addEventListener("click", () => showPage(section.firstPageIndex));
    return button;
  }

  function populateSections() {
    els.sectionList.innerHTML = "";
    for (const section of state.frontSections) {
      const meta = [section.subtype || section.type, `page ${pageLabel(state.pages[section.firstPageIndex])}`].filter(Boolean).join(" · ");
      els.sectionList.appendChild(makeSectionButton(section, "front-button", sectionLabel(section), meta));
    }

    for (const book of state.books) {
      const details = document.createElement("details");
      details.className = "book-group";
      details.open = true;

      const summary = document.createElement("summary");
      summary.className = "book-summary";
      const bookButton = makeSectionButton(book, "book-button", sectionLabel(book), `${book.chapters.length} chapters`);
      bookButton.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        showPage(book.firstPageIndex);
      });
      summary.appendChild(bookButton);
      details.appendChild(summary);

      const chapterList = document.createElement("div");
      chapterList.className = "chapter-list";
      for (const chapter of book.chapters) {
        const meta = `page ${pageLabel(state.pages[chapter.firstPageIndex])}`;
        chapterList.appendChild(makeSectionButton(chapter, "chapter-button", chapterLabel(chapter), meta));
      }
      details.appendChild(chapterList);
      els.sectionList.appendChild(details);
    }
  }

  function pageFromHash() {
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const hashIndex = params.get("pageIndex");
    if (hashIndex !== null) {
      const numeric = Number(hashIndex);
      if (Number.isInteger(numeric) && numeric >= 0 && numeric < state.pages.length) return numeric;
    }
    const hashPage = params.get("page");
    if (!hashPage) return -1;
    const byN = state.pages.findIndex((page) => page.n === hashPage || (page.manifest && String(page.manifest.book_page) === hashPage));
    if (byN >= 0) return byN;
    const numeric = Number(hashPage);
    return Number.isInteger(numeric) && numeric >= 0 && numeric < state.pages.length ? numeric : -1;
  }

  function updateHash(page) {
    const params = new URLSearchParams();
    if (state.edition && state.edition.id) params.set("edition", state.edition.id);
    params.set("pageIndex", String(page.index));
    params.set("page", page.n || String(page.index));
    history.replaceState(null, "", `#${params.toString()}`);
  }

  function setZoom(value) {
    if (!els.pageImage.naturalWidth) return;
    state.zoom = Math.max(0.35, Math.min(3.5, value));
    els.pageImage.style.width = `${Math.round(els.pageImage.naturalWidth * state.zoom)}px`;
    els.pageImage.style.height = "auto";
    els.zoomReset.textContent = `${Math.round(state.zoom * 100)}%`;
  }

  function fitImageWidth() {
    if (!els.pageImage.naturalWidth) return;
    const available = Math.max(220, els.imageStage.clientWidth - 32);
    state.imageFitMode = true;
    setZoom(available / els.pageImage.naturalWidth);
  }

  function renderImage(page) {
    const manifest = page.manifest || {};
    const image = manifest.image || "";
    const localRoot = state.edition.localImageRoot || "";
    const labelRoot = state.edition.imageLabelRoot || localRoot;
    const localHref = image && localRoot ? resolveRepoPath(`${localRoot.replace(/\/?$/, "/")}${image}`) : "";
    const labelHref = image && labelRoot ? `${labelRoot.replace(/\/?$/, "/")}${image}` : "";
    const sourceFacs = manifest.facs || page.facs || "";
    const remoteHref = manifest.remoteImage || (/^https?:/i.test(sourceFacs) ? sourceFacs : "");
    const imageHref = state.edition.imageMode === "local" ? localHref || remoteHref : remoteHref || localHref;
    const sourceLabel = state.edition.sourceLabel || "facsimile";

    els.imageMeta.textContent = [
      manifest.pdf_page ? `PDF ${manifest.pdf_page}` : "",
      manifest.book_page ? `book page ${manifest.book_page}` : page.n ? `TEI page ${page.n}` : "",
      page.book ? sectionLabel(page.book) : manifest.section || "",
    ].filter(Boolean).join(" · ");

    els.openImage.href = imageHref || "#";
    els.openImage.setAttribute("aria-disabled", imageHref ? "false" : "true");
    els.openFacs.href = sourceFacs ? resolveRepoPath(sourceFacs) : "#";
    els.openFacs.setAttribute("aria-disabled", sourceFacs ? "false" : "true");
    els.pageImage.hidden = true;
    els.imageFallback.hidden = true;
    els.pageImage.removeAttribute("src");

    if (!imageHref) {
      els.imageFallback.hidden = false;
      els.imageFallback.textContent = "No image is listed for this TEI page.";
      return;
    }

    els.pageImage.onload = () => {
      els.pageImage.hidden = false;
      els.imageFallback.hidden = true;
      if (state.imageFitMode) fitImageWidth();
      else setZoom(1);
    };
    els.pageImage.onerror = () => {
      els.pageImage.hidden = true;
      els.imageFallback.hidden = false;
      els.imageFallback.innerHTML = "";
      const message = document.createElement("div");
      message.textContent = imageHref === localHref
        ? `Local image missing or unavailable: ${labelHref}`
        : `${sourceLabel} image unavailable.`;
      els.imageFallback.appendChild(message);
      if (sourceFacs) {
        const link = document.createElement("a");
        link.href = resolveRepoPath(sourceFacs);
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = `Open ${sourceLabel}`;
        els.imageFallback.appendChild(link);
      }
    };
    els.pageImage.alt = `Scanned page ${pageLabel(page)}`;
    els.pageImage.src = imageHref;
  }

  function updateActiveSection(page) {
    for (const button of els.sectionList.querySelectorAll(".section-button")) {
      const kind = button.dataset.kind;
      const sectionId = button.dataset.sectionId;
      const chapterIds = new Set(page.chapters.map((chapter) => chapter.id));
      const active =
        (kind === "front" && page.frontSection && page.frontSection.id === sectionId) ||
        (kind === "book" && page.book && page.book.id === sectionId) ||
        (kind === "chapter" && chapterIds.has(sectionId));
      button.classList.toggle("active", active);
      button.classList.toggle("current", kind === "chapter" && page.activeChapter && page.activeChapter.id === sectionId);
    }
    for (const details of els.sectionList.querySelectorAll(".book-group")) {
      const bookButton = details.querySelector(".book-button");
      if (bookButton && page.book && bookButton.dataset.sectionId === page.book.id) details.open = true;
    }
  }

  function clearSelectionUi() {
    for (const selected of els.teiText.querySelectorAll(".selected")) selected.classList.remove("selected");
  }

  function showPage(index, options = {}) {
    if (!state.pages.length) return;
    const nextIndex = Math.max(0, Math.min(state.pages.length - 1, index));
    const page = state.pages[nextIndex];
    const imageLabelRoot = state.edition.imageLabelRoot || state.edition.localImageRoot || "";
    state.currentIndex = nextIndex;
    state.selectedContext = null;
    els.copyCorrection.disabled = true;
    els.pageSelect.value = String(nextIndex);
    els.prevPage.disabled = nextIndex === 0;
    els.nextPage.disabled = nextIndex === state.pages.length - 1;
    els.pageTitle.textContent = `Page ${pageLabel(page)}`;
    const chapterStarts = pageChapterStartLabels(page);
    const chapters = pageChapterLabels(page);
    els.pageMeta.textContent = [
      page.book ? sectionLabel(page.book) : page.frontSection ? sectionLabel(page.frontSection) : "",
      chapters.length ? `chapters ${chapters.join(", ")}` : "",
      chapterStarts.length ? `starts ${chapterStarts.join(", ")}` : "",
      page.manifest && page.manifest.pdf_page ? `PDF page ${page.manifest.pdf_page}` : "",
      page.manifest && page.manifest.image && imageLabelRoot ? `${imageLabelRoot.replace(/\/?$/, "/")}${page.manifest.image}` : "",
    ].filter(Boolean).join(" · ");

    els.teiText.replaceChildren(page.fragment.cloneNode(true));
    els.teiText.scrollTop = 0;
    renderImage(page);
    updateActiveSection(page);
    updateSearchMarkers();
    if (!options.skipHash) updateHash(page);
  }

  function allTextNodes(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        return node.nodeValue && node.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    const nodes = [];
    let node = walker.nextNode();
    while (node) {
      nodes.push(node);
      node = walker.nextNode();
    }
    return nodes;
  }

  function markTextNode(node, query) {
    const text = node.nodeValue;
    const lower = text.toLowerCase();
    const needle = query.toLowerCase();
    const parent = node.parentNode;
    let cursor = 0;
    let found = false;
    const fragment = document.createDocumentFragment();

    while (cursor < text.length) {
      const index = lower.indexOf(needle, cursor);
      if (index === -1) {
        fragment.appendChild(document.createTextNode(text.slice(cursor)));
        break;
      }
      found = true;
      if (index > cursor) fragment.appendChild(document.createTextNode(text.slice(cursor, index)));
      const mark = document.createElement("mark");
      mark.className = "mark";
      mark.textContent = text.slice(index, index + query.length);
      mark.dataset.pageIndex = String(state.currentIndex);
      fragment.appendChild(mark);
      cursor = index + query.length;
    }

    if (found) parent.replaceChild(fragment, node);
  }

  function searchAllPages(query) {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return [];
    return state.pages.flatMap((page) => {
      const text = page.plainText.toLowerCase();
      const hits = [];
      let index = text.indexOf(normalized);
      while (index !== -1) {
        hits.push({ pageIndex: page.index, index });
        index = text.indexOf(normalized, index + normalized.length);
      }
      return hits;
    });
  }

  function updateSearchCount() {
    if (!state.searchResults.length) {
      els.searchCount.textContent = "0/0";
      return;
    }
    els.searchCount.textContent = `${state.activeResult + 1}/${state.searchResults.length}`;
  }

  function updateSearchMarkers() {
    const query = els.searchInput.value.trim();
    if (!query) {
      updateSearchCount();
      return;
    }
    for (const node of allTextNodes(els.teiText)) markTextNode(node, query);
    const active = state.searchResults[state.activeResult];
    if (active && active.pageIndex === state.currentIndex) {
      const marks = Array.from(els.teiText.querySelectorAll(".mark"));
      const samePageBefore = state.searchResults.slice(0, state.activeResult).filter((hit) => hit.pageIndex === state.currentIndex).length;
      const mark = marks[samePageBefore] || marks[0];
      if (mark) {
        mark.classList.add("active");
        mark.scrollIntoView({ block: "center" });
      }
    }
    updateSearchCount();
  }

  function runSearch() {
    state.searchResults = searchAllPages(els.searchInput.value);
    state.activeResult = state.searchResults.length ? 0 : -1;
    updateSearchCount();
    if (state.activeResult >= 0) {
      showPage(state.searchResults[state.activeResult].pageIndex);
    } else {
      showPage(state.currentIndex, { skipHash: true });
    }
  }

  function moveSearch(delta) {
    if (!state.searchResults.length) return;
    state.activeResult = (state.activeResult + delta + state.searchResults.length) % state.searchResults.length;
    showPage(state.searchResults[state.activeResult].pageIndex);
  }

  function selectContext(context, element) {
    clearSelectionUi();
    if (element) element.classList.add("selected");
    state.selectedContext = context;
    els.copyCorrection.disabled = false;
  }

  function contextFromSelection() {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !els.teiText.contains(selection.anchorNode)) return null;
    const text = selectedText(selection);
    if (!text) return null;
    const element = selection.anchorNode.nodeType === Node.ELEMENT_NODE ? selection.anchorNode : selection.anchorNode.parentElement;
    const contextual = element ? element.closest("[data-page-index]") : null;
    const base = contextual ? contextFromElement(contextual) : { pageIndex: state.currentIndex, line: "", divId: "", text: "" };
    base.line = lineFromRenderedPosition(selection.anchorNode, base.line);
    base.text = text;
    return base;
  }

  function correctionPayload() {
    const selectionContext = contextFromSelection();
    const context = selectionContext || state.selectedContext || { pageIndex: state.currentIndex, line: "", divId: "", text: "" };
    const page = state.pages[context.pageIndex] || state.pages[state.currentIndex];
    const manifest = page.manifest || {};
    const nearestChapter = chapterById(context.divId) || page.activeChapter || page.chapters[page.chapters.length - 1] || null;
    const image = manifest.image || "";
    const imageLabelRoot = state.edition.imageLabelRoot || state.edition.localImageRoot || "";
    const facs = manifest.facs || page.facs || "";
    return {
      teiFile: state.edition.tei || "",
      editionId: state.edition.id || "",
      pageN: page.n || "",
      pdfPage: manifest.pdf_page || null,
      bookPage: manifest.book_page || page.n || "",
      localImagePath: image && imageLabelRoot ? `${imageLabelRoot.replace(/\/?$/, "/")}${image}` : "",
      facsUrl: facs ? resolveRepoPath(facs) : "",
      nearestDivId: context.divId || nearestSectionId(page),
      nearestBookId: page.book ? page.book.id : "",
      nearestBook: page.book ? sectionLabel(page.book) : "",
      nearestChapterId: nearestChapter ? nearestChapter.id : "",
      nearestChapter: nearestChapter ? chapterLabel(nearestChapter) : "",
      nearestLine: context.line || page.firstLine || "",
      selectedText: context.text || "",
      note: "",
    };
  }

  async function copyCorrectionNote() {
    const payload = JSON.stringify(correctionPayload(), null, 2);
    try {
      await navigator.clipboard.writeText(payload);
      showToast("Correction note copied");
    } catch (error) {
      window.prompt("Copy correction note JSON", payload);
    }
  }

  function showToast(message) {
    els.toast.textContent = message;
    els.toast.hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => {
      els.toast.hidden = true;
    }, 1800);
  }

  function bindEvents() {
    els.editionSelect.addEventListener("change", async () => {
      const edition = state.editions.find((item) => item.id === els.editionSelect.value);
      if (!edition) return;
      try {
        await loadEdition(edition, { pageIndex: 0 });
      } catch (error) {
        const message = error && error.message ? error.message : String(error);
        console.error("Edition load failed", error);
        els.loadStatus.textContent = message;
        els.loadStatus.classList.add("error");
      }
    });
    els.pageSelect.addEventListener("change", () => showPage(Number(els.pageSelect.value)));
    els.prevPage.addEventListener("click", () => showPage(state.currentIndex - 1));
    els.nextPage.addEventListener("click", () => showPage(state.currentIndex + 1));
    els.searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") runSearch();
    });
    els.searchInput.addEventListener("input", () => {
      if (!els.searchInput.value.trim()) {
        state.searchResults = [];
        state.activeResult = -1;
        showPage(state.currentIndex, { skipHash: true });
      }
    });
    els.prevResult.addEventListener("click", () => moveSearch(-1));
    els.nextResult.addEventListener("click", () => {
      if (!state.searchResults.length) runSearch();
      else moveSearch(1);
    });
    els.copyCorrection.addEventListener("click", copyCorrectionNote);
    els.teiText.addEventListener("click", (event) => {
      const block = event.target.closest(".tei-block");
      if (block && els.teiText.contains(block)) selectContext(contextFromElement(block), block);
    });
    els.teiText.addEventListener("mouseup", () => {
      const context = contextFromSelection();
      if (context) selectContext(context, null);
    });
    els.zoomOut.addEventListener("click", () => {
      state.imageFitMode = false;
      setZoom(state.zoom - 0.15);
    });
    els.zoomIn.addEventListener("click", () => {
      state.imageFitMode = false;
      setZoom(state.zoom + 0.15);
    });
    els.zoomReset.addEventListener("click", () => {
      state.imageFitMode = false;
      setZoom(1);
    });
    els.fitWidth.addEventListener("click", fitImageWidth);
    window.addEventListener("resize", () => {
      if (state.imageFitMode) fitImageWidth();
    });
    window.addEventListener("hashchange", () => {
      const index = pageFromHash();
      if (index >= 0 && index !== state.currentIndex) showPage(index, { skipHash: true });
    });
  }

  async function init() {
    bindEvents();
    try {
      await loadEditionRegistry();
      populateEditionSelect();
      await loadEdition(state.edition);
    } catch (error) {
      const message = error && error.message ? error.message : String(error);
      console.error("Viewer load failed", error);
      els.loadStatus.textContent = message;
      els.loadStatus.classList.add("error");
      els.teiText.innerHTML = `<div class="tei-empty">Unable to load viewer data: <code></code><br>Serve from the repo root with <code>python3 -m http.server 8000</code> and open <code>http://localhost:8000/viewer/</code>.</div>`;
      els.teiText.querySelector("code").textContent = message;
    }
  }

  init();
})();
