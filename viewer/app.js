(function () {
  "use strict";

  const REPO_ROOT = new URL("../", window.location.href);
  const EDITIONS_PATH = "editions.json";
  const LOCAL_PRIVATE_REGISTRY_PATHS = [
    "editions/beck2020/private_registry.json",
    "editions/beck2020_fresh/private_registry.json",
  ];
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
    textViewToggle: document.getElementById("textViewToggle"),
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
    imageFitMode: true,
    selectedContext: null,
    searchResults: [],
    activeResult: -1,
    toastTimer: null,
    xmlIdPages: new Map(),
    editions: [],
    edition: FALLBACK_EDITION,
    textViewMode: "diplomatic",
    generatedSectionIds: new WeakMap(),
    generatedSectionIdCounts: new Map(),
  };

  function resolveRepoPath(path) {
    if (!path) return "";
    if (/^(?:https?:|data:|blob:)/i.test(path)) return path;
    return new URL(path.replace(/^\.?\//, ""), REPO_ROOT).href;
  }

  function registryPath() {
    const requested = new URLSearchParams(window.location.search).get("registry");
    if (!requested) return EDITIONS_PATH;
    if (/^(?:https?:|data:|blob:)/i.test(requested) || requested.startsWith("/") || requested.includes("..")) {
      console.warn("Ignoring unsupported edition registry path", requested);
      return EDITIONS_PATH;
    }
    return requested;
  }

  function hasExplicitRegistryPath() {
    return new URLSearchParams(window.location.search).has("registry");
  }

  function isLocalViewerHost() {
    const host = window.location.hostname;
    return host === "localhost" || host === "0.0.0.0" || host === "::1" || /^127(?:\.\d{1,3}){3}$/.test(host);
  }

  function mergeEditionRegistries(primary, overlay) {
    if (!overlay || !Array.isArray(overlay.editions) || !overlay.editions.length) return primary;
    const merged = [];
    const seen = new Set();
    for (const registry of [primary, overlay]) {
      for (const edition of Array.isArray(registry.editions) ? registry.editions : []) {
        if (!edition || !edition.id || seen.has(edition.id)) continue;
        seen.add(edition.id);
        merged.push(edition);
      }
    }
    return { ...primary, editions: merged };
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
    if (section.kind === "book") return section.navTitle || section.title || `Book ${section.n || section.id || "?"}`;
    return section.navTitle || section.title || section.n || section.id || section.subtype || section.type || "Section";
  }

  function compactSectionLabel(section) {
    if (!section) return "";
    if (section.kind === "book") return `Book ${section.n || "?"}`;
    return sectionLabel(section);
  }

  function chapterLabel(chapter) {
    if (!chapter) return "";
    if (chapter.subtype === "proem") return chapter.navTitle || chapter.title || chapter.n || "Proem";
    return [chapter.n, chapter.navTitle || chapter.title].filter(Boolean).join(" ");
  }

  function pageChapterLabels(page) {
    return page.chapters.map(chapterLabel).filter(Boolean);
  }

  function pageChapterSummary(page) {
    return pageChapterLabels(page).join(", ");
  }

  function pageChapterStartLabels(page) {
    return page.chapterStarts.map(chapterLabel).filter(Boolean);
  }

  function pageSelectContext(page) {
    const chapterSummary = pageChapterSummary(page);
    return chapterSummary
      ? chapterSummary
      : page.book
        ? sectionLabel(page.book)
        : page.frontSection
          ? frontSectionLabels(page.frontSection).join(" · ")
          : page.manifest && page.manifest.section
            ? page.manifest.section
            : sectionLabel(page.section);
  }

  function pageSelectCompactLabel(page) {
    const pdf = page.manifest && page.manifest.pdf_page ? `PDF ${page.manifest.pdf_page}` : "PDF ?";
    return `${pageLabel(page)} · ${pdf}`;
  }

  function activeChapterForNavigation(page, direction) {
    if (!page) return null;
    if (page.activeChapter) return page.activeChapter;
    return direction < 0 ? page.chapters[0] || null : page.chapters[page.chapters.length - 1] || null;
  }

  function chapterIndexForNavigation(page, direction) {
    const chapter = activeChapterForNavigation(page, direction);
    if (!chapter) return -1;
    return state.chapters.findIndex((candidate) => candidate === chapter || candidate.id === chapter.id);
  }

  function chapterPageIndex(chapter) {
    return chapter && Number.isInteger(chapter.firstPageIndex) ? chapter.firstPageIndex : -1;
  }

  function rootFrontSection(section) {
    let current = section || null;
    while (current && current.parent && current.parent.kind === "front") current = current.parent;
    return current;
  }

  function frontSectionLabels(section) {
    const labels = [];
    const root = rootFrontSection(section);
    if (root) labels.push(sectionLabel(root));
    if (section && section !== root) labels.push(sectionLabel(section));
    return labels;
  }

  function frontNavigationSections() {
    const sections = [];
    for (const section of state.frontSections) {
      if (section.children.length) {
        for (const child of section.children) {
          if (Number.isInteger(child.firstPageIndex)) sections.push(child);
        }
      } else if (Number.isInteger(section.firstPageIndex)) {
        sections.push(section);
      }
    }
    return sections;
  }

  function frontSectionInPath(page, sectionId) {
    let section = page.frontSection;
    while (section) {
      if (section.id === sectionId) return true;
      section = section.parent && section.parent.kind === "front" ? section.parent : null;
    }
    return false;
  }

  function navigateFrontSection(delta) {
    const page = state.pages[state.currentIndex];
    if (!page || !page.frontSection) return false;
    const sections = frontNavigationSections();
    const currentIndex = sections.findIndex((section) => section === page.frontSection || section.id === page.frontSection.id);
    if (currentIndex < 0) return false;
    const nextIndex = currentIndex + delta;
    if (nextIndex < 0 || nextIndex >= sections.length) return false;
    const nextPageIndex = sections[nextIndex].firstPageIndex;
    if (!Number.isInteger(nextPageIndex) || nextPageIndex === state.currentIndex) return false;
    showPage(nextPageIndex);
    return true;
  }

  function navigatePage(delta) {
    if (!state.pages.length) return false;
    const nextIndex = state.currentIndex + delta;
    if (nextIndex < 0 || nextIndex >= state.pages.length) return false;
    showPage(nextIndex);
    return true;
  }

  function navigateChapter(delta) {
    const page = state.pages[state.currentIndex];
    if (page && page.frontSection && !page.book) return navigateFrontSection(delta);
    if (!state.chapters.length) return false;
    const currentChapterIndex = chapterIndexForNavigation(page, delta);
    if (currentChapterIndex < 0) return false;
    const nextChapterIndex = currentChapterIndex + delta;
    if (nextChapterIndex < 0 || nextChapterIndex >= state.chapters.length) return false;
    const nextPageIndex = chapterPageIndex(state.chapters[nextChapterIndex]);
    if (nextPageIndex < 0 || nextPageIndex === state.currentIndex) return false;
    showPage(nextPageIndex);
    return true;
  }

  function isNavigationShortcutTarget(target) {
    if (!target || target === document || target === window) return true;
    if (!(target instanceof Element)) return true;
    if (target.isContentEditable || target.closest("[contenteditable]")) return false;
    return !target.closest("input, select, textarea");
  }

  function handleKeyboardNavigation(event) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (!isNavigationShortcutTarget(event.target)) return;
    const handled =
      (event.key === "ArrowLeft" && navigatePage(-1)) ||
      (event.key === "ArrowRight" && navigatePage(1)) ||
      (event.key === "ArrowUp" && navigateChapter(-1)) ||
      (event.key === "ArrowDown" && navigateChapter(1));
    if (handled) event.preventDefault();
  }

  function normalizeText(text) {
    return text.replace(/\s+/g, " ").trim();
  }

  function prepareRenderedTextClone(clone) {
    for (const footnote of clone.querySelectorAll(".tei-footnote")) footnote.remove();
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

  function isInsideRenderedFootnote(node) {
    const element = node && node.nodeType === Node.ELEMENT_NODE ? node : node ? node.parentElement : null;
    return Boolean(element && element.closest(".tei-footnote"));
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

  function textWithoutRefs(element) {
    const parts = [];
    for (const node of element.childNodes) {
      if (node.nodeType === Node.TEXT_NODE) {
        parts.push(node.nodeValue || "");
      } else if (node.nodeType === Node.ELEMENT_NODE && localName(node) !== "ref") {
        parts.push(node.textContent || "");
      }
    }
    return normalizeText(parts.join(" "));
  }

  function stripPrintedCapPrefix(text) {
    return normalizeText(text)
      .replace(/^\s*\(?\s*Cap\.\s*\d+\.?(?:\s*[A-Za-z])?(?:\s*\([^)]+\))?\s*\)?\.?\s*/i, "")
      .replace(/^\s*\)?\s*/, "")
      .replace(/\s+/g, " ")
      .replace(/[.。]+$/, "")
      .trim();
  }

  function cleanBracketedTitle(text) {
    const bracketed = text.match(/\[([^\]]+)/);
    if (bracketed) {
      return bracketed[1]
        .replace(/\[\d+\]?$/, "")
        .replace(/\s+/g, " ")
        .replace(/[.。]+$/, "")
        .trim();
    }
    return text
      .replace(/^Κεφ\.\s*\S+\.?\s*/i, "")
      .replace(/\s+/g, " ")
      .replace(/[.。]+$/, "")
      .trim();
  }

  function elementLang(element) {
    return element.getAttributeNS(XML_NS, "lang") || element.getAttribute("xml:lang") || element.getAttribute("lang") || "";
  }

  function isInsideFootnoteRef(node) {
    for (let parent = node.parentElement; parent; parent = parent.parentElement) {
      if (localName(parent) === "ref" && parent.getAttribute("type") === "footnote-ref") return true;
    }
    return false;
  }

  function textAfterElement(root, marker) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const parts = [];
    let node = walker.nextNode();
    while (node) {
      if (!isInsideFootnoteRef(node) && !marker.contains(node) && (marker.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING)) {
        parts.push(node.nodeValue || "");
      }
      node = walker.nextNode();
    }
    return normalizeText(parts.join(" "));
  }

  function shortTitleFromHeadText(text) {
    let normalized = normalizeText(text).replace(/^[\s.:-]+/, "");
    if (!normalized) return "";
    const split = normalized.match(/^(.{1,90}?\.)\s+(?=\[?Einige\b|Auch\b|Der\b|Die\b|Das\b|Den\b|Dem\b|Ein\b|Eine\b|Es\b|Man\b|Wir\b|Nimm\b|Jede\b|Von\b|Wird\b|Fast\b|Als\b)/);
    if (split) normalized = split[1];
    return normalized.replace(/[.。]+$/, "").trim();
  }

  function hasRendToken(element, token) {
    return (element.getAttribute("rend") || "").toLowerCase().split(/\s+/).includes(token);
  }

  function leadingTranslationTitleContinuation(div, directHead) {
    if (!div || !directHead) return "";
    const children = Array.from(div.childNodes);
    const headIndex = children.indexOf(directHead);
    if (headIndex === -1) return "";
    for (const child of children.slice(headIndex + 1)) {
      if (child.nodeType === Node.TEXT_NODE && !(child.nodeValue || "").trim()) continue;
      if (child.nodeType !== Node.ELEMENT_NODE) return "";
      const name = localName(child);
      if (name === "pb" || name === "fw") continue;
      if (name !== "ab" || child.getAttribute("type") !== "translation") return "";
      const parts = [];
      for (const node of child.childNodes) {
        if (node.nodeType === Node.TEXT_NODE && !(node.nodeValue || "").trim()) continue;
        if (node.nodeType !== Node.ELEMENT_NODE) break;
        const nodeName = localName(node);
        if (nodeName === "lb" || nodeName === "ref") continue;
        if (nodeName === "hi" && hasRendToken(node, "bold")) {
          parts.push(normalizeText(node.textContent || ""));
          if (/[.。]$/.test(normalizeText(node.textContent || ""))) break;
          continue;
        }
        break;
      }
      const continuation = normalizeText(parts.join(" "));
      return /[.。]$/.test(continuation) ? continuation.replace(/[.。]+$/, "").trim() : "";
    }
    return "";
  }

  function extractBerendesHeadTitle(directHead) {
    const foreignHeads = Array.from(directHead.getElementsByTagNameNS("*", "foreign"))
      .filter((el) => elementLang(el) === "grc");
    const lastForeign = foreignHeads[foreignHeads.length - 1];
    if (!lastForeign) return "";
    return shortTitleFromHeadText(textAfterElement(directHead, lastForeign));
  }

  function appendLeadingTranslationTitleContinuation(div, directHead, title) {
    if (!title) return "";
    const foreignHeads = Array.from(directHead.getElementsByTagNameNS("*", "foreign"))
      .filter((el) => elementLang(el) === "grc");
    const lastForeign = foreignHeads[foreignHeads.length - 1];
    if (!lastForeign) return title;
    const titleText = textAfterElement(directHead, lastForeign);
    if (/[.。]\s*$/.test(normalizeText(titleText))) return title;
    const continuation = leadingTranslationTitleContinuation(div, directHead);
    return [title, continuation].filter(Boolean).join(" ");
  }

  function extractNavTitle(div, title) {
    const directHead = directSectionHead(div);
    if (directHead) {
      const berendesTitle = appendLeadingTranslationTitleContinuation(div, directHead, extractBerendesHeadTitle(directHead));
      if (berendesTitle) return berendesTitle;
      const hi = Array.from(directHead.getElementsByTagNameNS("*", "hi")).find((el) => hasRendToken(el, "bold"));
      if (hi) return normalizeText(hi.textContent || "").replace(/[.。]+$/, "");
    }
    if (/^Κεφ\./.test(title)) return cleanBracketedTitle(title);
    return stripPrintedCapPrefix(directHead ? textWithoutRefs(directHead) : title)
      .replace(/Περὶ[^.]*\./g, "")
      .replace(/\s+/g, " ")
      .replace(/[.。]+$/, "")
      .trim();
  }

  function generatedSectionId(div, kind, n, type, subtype, book) {
    const sourceId = getXmlId(div);
    if (sourceId) return sourceId;
    if (state.generatedSectionIds.has(div)) return state.generatedSectionIds.get(div);
    const bookPart = book && book.n ? `book-${classToken(book.n)}` : "";
    const base = [state.edition.id, kind, bookPart, subtype || type || "section", n || ""]
      .map(classToken)
      .filter(Boolean)
      .join("-");
    const key = base || `${state.edition.id || "edition"}-${kind}-section`;
    const count = (state.generatedSectionIdCounts.get(key) || 0) + 1;
    state.generatedSectionIdCounts.set(key, count);
    const id = count === 1 ? key : `${key}-${count}`;
    state.generatedSectionIds.set(div, id);
    return id;
  }

  function buildSection(div, parent, kind, book) {
    const title = extractTitle(div);
    const n = div.getAttribute("n") || "";
    const type = div.getAttribute("type") || "";
    const subtype = div.getAttribute("subtype") || "";
    if (kind === "front" && n) {
      const existing = state.frontSections.find((section) => section.n === n);
      if (existing) return existing;
    }
    const section = {
      id: generatedSectionId(div, kind, n, type, subtype, book),
      n,
      type,
      subtype,
      title,
      navTitle: extractNavTitle(div, title),
      kind,
      parent,
      book: book || null,
      chapters: [],
      children: [],
      currentChapter: null,
      firstPageIndex: null,
    };
    if (kind === "book") state.books.push(section);
    else if (kind === "chapter") {
      state.chapters.push(section);
      if (book) book.chapters.push(section);
    } else if (kind === "front") {
      if (parent && parent.kind === "front") addUnique(parent.children, section);
      else state.frontSections.push(section);
    }
    return section;
  }

  function addUnique(list, item) {
    if (item && !list.includes(item)) list.push(item);
  }

  function markSectionPage(section, page) {
    if (section && section.firstPageIndex === null) section.firstPageIndex = page.index;
  }

  function markSectionPageWithAncestors(section, page) {
    let current = section;
    while (current) {
      markSectionPage(current, page);
      current = current.parent && current.parent.kind === "front" ? current.parent : null;
    }
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
    markSectionPageWithAncestors(section, page);
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

  function chapterByBookAndN(book, n) {
    if (!book || !n) return null;
    return state.chapters.find((chapter) => chapter.book === book && chapter.n === n) || null;
  }

  function looksGreek(text) {
    return /[\u0370-\u03ff\u1f00-\u1fff]/.test(text || "");
  }

  function combinedChapterTitle(primary, paired) {
    const labels = [primary, paired].filter(Boolean);
    if (labels.length === 2 && !looksGreek(labels[0]) && looksGreek(labels[1])) {
      return [labels[1], labels[0]].join(" / ");
    }
    return labels.join(" / ");
  }

  function registerChapterMilestone(milestone, context) {
    const page = context.currentPage;
    if (!page || !context.book) return;
    const n = milestone.getAttribute("n") || "";
    const label = milestone.getAttribute("label") || "";
    const pairedLabel = milestone.getAttribute("pairedLabel") || "";
    const title = combinedChapterTitle(label, pairedLabel) || milestone.getAttribute("sourceLabel") || n;
    let chapter = chapterByBookAndN(context.book, n);
    if (!chapter) {
      chapter = {
        id: getXmlId(milestone) || generatedSectionId(milestone, "chapter", n, "textpart", "chapter", context.book),
        n,
        type: "textpart",
        subtype: "chapter",
        title,
        navTitle: title,
        kind: "chapter",
        parent: context.book,
        book: context.book,
        chapters: [],
        currentChapter: null,
        firstPageIndex: null,
      };
      state.chapters.push(chapter);
      context.book.chapters.push(chapter);
    } else if (title && (!chapter.navTitle || chapter.navTitle === chapter.n)) {
      chapter.title = title;
      chapter.navTitle = title;
    }
    context.chapter = chapter;
    context.book.currentChapter = chapter;
    registerChapterOnPage(chapter, page, true);
    page.section = chapter;
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

  function isInCommentaryZone(container) {
    return container instanceof Element && Boolean(container.closest(".tei-place-commentary"));
  }

  function contributesToPageText(container) {
    return !(container instanceof Element && container.closest(".tei-footnote"));
  }

  function appendCommentaryText(container, page, text) {
    const lines = text
      .replace(/\r\n?/g, "\n")
      .split("\n")
      .map((line) => line.replace(/[ \t]+/g, " ").trim())
      .filter(Boolean);
    for (const line of lines) {
      if (container.childNodes.length) container.appendChild(document.createElement("br"));
      container.appendChild(document.createTextNode(line));
      if (contributesToPageText(container)) page.plainText += ` ${normalizeText(line)}`;
    }
  }

  function appendText(container, page, text, preserveWhitespace = false) {
    if (isInCommentaryZone(container) && /\r|\n/.test(text)) {
      appendCommentaryText(container, page, text);
      return;
    }
    const trimmed = text.replace(/[ \t\r\n]+/g, " ");
    if (trimmed.trim()) {
      container.appendChild(document.createTextNode(trimmed));
      if (contributesToPageText(container)) page.plainText += ` ${normalizeText(trimmed)}`;
    } else if (preserveWhitespace && !(container.textContent || "").endsWith(" ")) {
      container.appendChild(document.createTextNode(" "));
      if (contributesToPageText(container)) page.plainText += " ";
    }
  }

  function makeRenderedElement(source, page, context) {
    const name = localName(source);
    const isBlock = isBlockElement(source);
    const element = document.createElement(isBlock ? (name === "head" ? "h3" : "div") : name === "ref" ? "a" : "span");
    const type = source.getAttribute("type") || "";
    const labeledNote = name === "note" && ["apparatus", "footnote"].includes(type);
    element.className = `${isBlock ? "tei-block " : ""}tei-${name}`;
    const typeToken = classToken(type);
    if (typeToken) element.classList.add(`tei-${typeToken}`);
    const placeToken = classToken(source.getAttribute("place") || "");
    if (placeToken) element.classList.add(`tei-place-${placeToken}`);
    if (labeledNote) element.classList.add("tei-footnote");
    decorateContext(element, page, context);
    const sourceId = getXmlId(source);
    if (sourceId) {
      element.id = sourceId;
      state.xmlIdPages.set(sourceId, page.index);
    }

    const lang = source.getAttributeNS(XML_NS, "lang") || source.getAttribute("xml:lang") || source.getAttribute("lang") || "";
    if (lang) {
      element.setAttribute("lang", lang);
      if (type === "pageZone") {
        const place = source.getAttribute("place") || "";
        element.dataset.zoneLabel = place === "commentary" ? "Commentary" : lang === "grc" ? "Greek" : lang === "la" ? "Latin" : lang;
      }
    }

    if (name === "hi") {
      const rend = (source.getAttribute("rend") || "").toLowerCase();
      for (const token of rend.split(/\s+/).map(classToken).filter(Boolean)) {
        element.classList.add(`tei-hi-${token}`);
      }
    }

    if (name === "ref") element.setAttribute("href", source.getAttribute("target") || "#");
    if (labeledNote) {
      const label = source.getAttribute("n") || "";
      if (label) {
        const labelElement = document.createElement("span");
        labelElement.className = "footnote-label";
        labelElement.textContent = `${label} `;
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

  function hasPageBreakBefore(element) {
    for (let sibling = element.previousSibling; sibling; sibling = sibling.previousSibling) {
      if (sibling.nodeType === Node.ELEMENT_NODE && localName(sibling) === "pb") return true;
    }
    return false;
  }

  function hasLineBreak(element) {
    return Array.from(element.getElementsByTagNameNS("*", "lb")).length > 0;
  }

  function isRenderableHead(element, context) {
    if (localName(element) !== "head") return true;
    const parent = element.parentElement;
    if (!parent) return true;
    const parentName = localName(parent);
    if (parentName === "ab") return true;
    if (parentName === "div" && parent.getAttribute("subtype") === "diplomatic-page") return true;
    if (parentName === "div" && context.currentPage && (hasPageBreakBefore(element) || hasLineBreak(element))) return true;
    return context.frames.some((frame) => frame.source === parent);
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
      if (child.nodeType !== Node.ELEMENT_NODE) return false;
      const name = localName(child);
      if (name === "head") continue;
      if (name === "pb") return true;
      if (name === "div") return startsWithPageBreak(child);
      return false;
    }
    return false;
  }

  function enterSection(div, context) {
    const type = div.getAttribute("type") || "";
    const subtype = div.getAttribute("subtype") || "";
    const startsNewPage = startsWithPageBreak(div);
    const next = { ...context };
    if (startsNewPage) {
      next.currentPage = null;
      next.container = null;
      next.topFurnitureRow = null;
    }
    if (subtype === "diplomatic-page" || (type === "edition" && subtype === "diplomatic")) {
      return next;
    }
    if (subtype === "book") {
      const book = buildSection(div, null, "book", null);
      next.book = book;
      next.chapter = null;
      next.frontSection = null;
      if (next.currentPage && !startsNewPage) registerBookOnPage(book, next.currentPage);
    } else if (subtype === "chapter" || subtype === "proem") {
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
    if (name === "milestone" && (node.getAttribute("unit") || "") === "chapter") {
      registerChapterMilestone(node, context);
      return context;
    }
    if (isTopFurniture(node)) {
      appendTopFurniture(node, context, lookups);
      return context;
    }
    if (name === "head" && !isRenderableHead(node, context)) {
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

  async function loadOptionalJson(path) {
    try {
      return await loadJson(path);
    } catch (error) {
      console.warn("Optional edition registry unavailable", path, error);
      return null;
    }
  }

  async function loadEditionRegistry() {
    try {
      let registry = await loadJson(resolveRepoPath(registryPath()));
      if (!hasExplicitRegistryPath() && isLocalViewerHost()) {
        for (const registryPath of LOCAL_PRIVATE_REGISTRY_PATHS) {
          const privateRegistry = await loadOptionalJson(resolveRepoPath(registryPath));
          registry = mergeEditionRegistries(registry, privateRegistry);
        }
      }
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
    state.generatedSectionIds = new WeakMap();
    state.generatedSectionIdCounts = new Map();
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
      const compactLabel = pageSelectCompactLabel(page);
      option.textContent = compactLabel;
      option.title = `${compactLabel} · ${pageSelectContext(page)}`;
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
    button.title = [sectionLabel(section), meta].filter(Boolean).join(" · ");
    button.addEventListener("click", () => showPage(section.firstPageIndex));
    return button;
  }

  function populateSections() {
    els.sectionList.innerHTML = "";
    for (const section of state.frontSections) {
      const meta = [section.subtype || section.type, `page ${pageLabel(state.pages[section.firstPageIndex])}`].filter(Boolean).join(" · ");
      if (section.children.length) {
        const details = document.createElement("details");
        details.className = "book-group front-group";
        details.open = true;
        const summary = document.createElement("summary");
        summary.className = "book-summary";
        const sectionButton = makeSectionButton(section, "front-button", sectionLabel(section), meta);
        sectionButton.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          showPage(section.firstPageIndex);
        });
        summary.appendChild(sectionButton);
        details.appendChild(summary);
        const subsectionList = document.createElement("div");
        subsectionList.className = "chapter-list front-subsection-list";
        for (const child of section.children) {
          const childMeta = `page ${pageLabel(state.pages[child.firstPageIndex])}`;
          subsectionList.appendChild(makeSectionButton(child, "front-button", sectionLabel(child), childMeta));
        }
        details.appendChild(subsectionList);
        els.sectionList.appendChild(details);
      } else {
        els.sectionList.appendChild(makeSectionButton(section, "front-button", sectionLabel(section), meta));
      }
    }

    for (const book of state.books) {
      const details = document.createElement("details");
      details.className = "book-group";
      details.open = true;

      const summary = document.createElement("summary");
      summary.className = "book-summary";
      const bookButton = makeSectionButton(book, "book-button", compactSectionLabel(book), `${book.chapters.length} chapters`);
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
        (kind === "front" && frontSectionInPath(page, sectionId)) ||
        (kind === "book" && page.book && page.book.id === sectionId) ||
        (kind === "chapter" && chapterIds.has(sectionId));
      button.classList.toggle("active", active);
      button.classList.toggle("current", kind === "chapter" && chapterIds.has(sectionId));
    }
    for (const details of els.sectionList.querySelectorAll(".front-group")) {
      const frontButton = details.querySelector(".front-button");
      if (frontButton && frontSectionInPath(page, frontButton.dataset.sectionId)) details.open = true;
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
    const frontLabels = frontSectionLabels(page.frontSection);
    const pageMetaParts = [
      page.book ? compactSectionLabel(page.book) : frontLabels.join(" · "),
      chapters.length ? `chapters ${chapters.join(", ")}` : "",
      chapterStarts.length ? `starts ${chapterStarts.join(", ")}` : "",
      page.manifest && page.manifest.pdf_page ? `PDF page ${page.manifest.pdf_page}` : "",
      page.manifest && page.manifest.image && imageLabelRoot ? `${imageLabelRoot.replace(/\/?$/, "/")}${page.manifest.image}` : "",
    ].filter(Boolean);
    els.pageMeta.textContent = pageMetaParts.join(" · ");
    els.pageMeta.title = [
      page.book ? sectionLabel(page.book) : frontLabels.join(" · "),
      ...pageMetaParts.slice(1),
    ].filter(Boolean).join(" · ");

    els.teiText.replaceChildren(page.fragment.cloneNode(true));
    updateTextViewMode(page);
    els.teiText.scrollTop = 0;
    renderImage(page);
    updateActiveSection(page);
    updateSearchMarkers();
    if (!options.skipHash) updateHash(page);
  }

  function pageHasParallelZones(page) {
    if (!page) return false;
    return Boolean(page.fragment.querySelector('.tei-pagezone[lang="grc"]')) && Boolean(page.fragment.querySelector('.tei-pagezone[lang="la"]'));
  }

  function updateTextViewMode(page) {
    const canParallel = pageHasParallelZones(page);
    els.textViewToggle.hidden = !canParallel;
    els.textViewToggle.disabled = !canParallel;
    if (!canParallel) state.textViewMode = "diplomatic";
    const parallel = canParallel && state.textViewMode === "parallel";
    els.teiText.classList.toggle("tei-parallel", parallel);
    els.textViewToggle.textContent = parallel ? "Diplomatic" : "Parallel";
    els.textViewToggle.setAttribute("aria-pressed", parallel ? "true" : "false");
  }

  function allTextNodes(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (isInsideRenderedFootnote(node)) return NodeFilter.FILTER_REJECT;
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
    const nearestFrontSubsection = page.frontSection && page.frontSection.parent && page.frontSection.parent.kind === "front" ? page.frontSection : null;
    const nearestFrontSection = rootFrontSection(page.frontSection);
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
      nearestFrontSectionId: nearestFrontSection ? nearestFrontSection.id : "",
      nearestFrontSection: nearestFrontSection ? sectionLabel(nearestFrontSection) : "",
      nearestFrontSubsectionId: nearestFrontSubsection ? nearestFrontSubsection.id : "",
      nearestFrontSubsection: nearestFrontSubsection ? sectionLabel(nearestFrontSubsection) : "",
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
    els.textViewToggle.addEventListener("click", () => {
      state.textViewMode = state.textViewMode === "parallel" ? "diplomatic" : "parallel";
      showPage(state.currentIndex, { skipHash: true });
    });
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
    window.addEventListener("keydown", handleKeyboardNavigation);
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
