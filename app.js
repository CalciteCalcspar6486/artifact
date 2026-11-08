"use strict";

const $ = (selector) => document.querySelector(selector);
const kinds = { all: "全部", game: "游戏美术", pixel: "像素艺术", other: "异想艺术", music: "音乐" };
const pages = {
  today: ["ARTIFACT", "异想艺术档案馆", "本期作品"],
  archive: ["往期", "按日期重访过去的选集", "往期作品"],
  saved: ["收藏", "留在这台设备上的作品", "收藏作品"],
};
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const storageKey = "artifact.favorites.v1:" + new URL(".", document.baseURI).pathname;
let saved = readSaved();
let page = "today";
let filter = "all";
let dates;
let datesFromCache = false;
let lastChecked = 0;
let issue;
let archiveDate;
let busy = false;
let error = "";
let revision = 0;
let toastTimer;

function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value) node.textContent = value;
  return node;
}

function icon(name) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS(node.namespaceURI, "use");
  node.setAttribute("aria-hidden", "true");
  use.setAttribute("href", `#${name}`);
  node.append(use);
  return node;
}

function https(value) {
  if (typeof value !== "string" || value.length > 3000) return "";
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : "";
  } catch {
    return "";
  }
}

function cleanItem(item) {
  if (!item || typeof item !== "object") return null;
  const url = https(item.url);
  const image = https(item.image);
  if (!url || !image || typeof item.id !== "string" || !/^[\w:-]{1,100}$/.test(item.id)
      || !Object.hasOwn(kinds, item.kind) || item.kind === "all") return null;
  const label = (value) => typeof value === "string" && value.trim() ? value.trim().slice(0, 300) : "未知";
  const dimension = (value) => Number.isInteger(value) && value > 0 && value <= 100000 ? value : 0;
  return {
    id: item.id, kind: item.kind, title: label(item.title), author: label(item.author),
    source: label(item.source), license: typeof item.license === "string" ? label(item.license) : "",
    url, image, full: https(item.full) || image, width: dimension(item.width), height: dimension(item.height),
  };
}

function readSaved() {
  try {
    const stored = JSON.parse(localStorage.getItem(storageKey) || "[]");
    return new Map(stored.map(cleanItem).filter(Boolean).map((item) => [item.id, item]));
  } catch {
    return new Map();
  }
}

function persist() {
  try {
    localStorage.setItem(storageKey, JSON.stringify([...saved.values()]));
    return true;
  } catch {
    return false;
  }
}

function toast(value) {
  $("#toast").textContent = value;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("#toast").textContent = ""; }, 3300);
}

function updateHeart(button) {
  const pressed = saved.has(button.dataset.favorite);
  button.setAttribute("aria-pressed", String(pressed));
  button.setAttribute("aria-label", `${pressed ? "取消收藏" : "收藏"} ${button.dataset.title}`);
}

function heart(item) {
  const button = element("button", "icon-button");
  button.type = "button";
  button.dataset.favorite = item.id;
  button.dataset.title = item.title;
  updateHeart(button);
  button.append(icon("heart"));
  button.addEventListener("click", () => {
    const adding = !saved.has(item.id);
    if (adding) saved.set(item.id, item);
    else saved.delete(item.id);
    toast(persist() ? (adding ? "已收藏" : "已取消收藏") : "浏览器无法保存，本次更改仅在当前页面有效。");
    if (page === "saved") {
      render();
      if (!$("#viewer").open) ($("#gallery button, #music-list button") || $("#page-title")).focus();
    }
    document.querySelectorAll("[data-favorite]").forEach(updateHeart);
  });
  return button;
}

function external(item, className) {
  const link = element("a", className);
  link.href = item.url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function sourceLink(item) {
  const link = external(item, "source-link");
  link.append("原始链接", icon("arrow"));
  link.setAttribute("aria-label", `打开 ${item.title} 的原始链接`);
  return link;
}

function actions(item) {
  const group = element("div", "actions");
  group.append(sourceLink(item), heart(item));
  return group;
}

function media(container, item, { eager = false, full = false } = {}) {
  const image = element("img", item.kind === "pixel" ? "pixel" : "");
  image.alt = item.title;
  image.loading = eager ? "eager" : "lazy";
  image.decoding = "async";
  if (item.width && item.height) {
    image.width = item.width;
    image.height = item.height;
  }
  const label = element("span", "missing-label", "预览暂不可用");
  label.hidden = true;
  container.classList.remove("is-missing");
  image.addEventListener("error", () => {
    if (full && image.src !== item.image) {
      image.src = item.image;
      return;
    }
    container.classList.add("is-missing");
    label.hidden = false;
  });
  image.src = full ? item.full : item.image;
  container.replaceChildren(image, label);
}

function zoomButton(item, cover = false) {
  const button = element("button", "artwork");
  button.type = "button";
  button.setAttribute("aria-label", `放大 ${item.title}`);
  media(button, item, { eager: cover });
  const badge = element("span", "zoom-badge");
  badge.append(icon("zoom"));
  button.append(badge);
  button.addEventListener("click", () => openViewer(item, button));
  return button;
}

function credit(item) {
  const author = item.source === "itch.io" ? `项目署名 ${item.author}` : item.author;
  return `${author}  /  ${item.source}`;
}

function showHero(item, date) {
  const hero = $("#hero");
  hero.hidden = !item;
  hero.replaceChildren();
  if (!item) return;
  const visual = element("div", "hero-visual");
  const edition = dates.length - dates.indexOf(date);
  visual.append(zoomButton(item, true), element("span", "hero-label", `第 ${String(edition).padStart(3, "0")} 期 · 封面`));
  const caption = element("div", "hero-caption");
  const copy = element("div");
  copy.append(element("h2", "", item.title), element("p", "credit", credit(item)));
  caption.append(copy, actions(item));
  hero.append(visual, caption);
}

function artCard(item) {
  const card = element("article", "card");
  const caption = element("div", "card-caption");
  caption.append(element("span", "category", kinds[item.kind]), element("h3", "", item.title), element("p", "credit", credit(item)));
  card.append(zoomButton(item), caption, actions(item));
  return card;
}

function musicCard(item) {
  const card = element("article", "music");
  const link = external(item, "music-link");
  link.setAttribute("aria-label", `前往 ${item.source} 播放 ${item.title}`);
  const cover = element("div", "music-cover");
  media(cover, item);
  const copy = element("div", "music-copy");
  copy.append(element("h3", "", item.title), element("p", "credit", credit(item)));
  link.append(cover, copy, icon("play"));
  card.append(link, heart(item));
  return card;
}

function openViewer(item, opener) {
  const dialog = $("#viewer");
  media($("#viewer-image"), item, { eager: true, full: true });
  $("#viewer-type").textContent = [kinds[item.kind], item.license].filter(Boolean).join(" / ");
  $("#viewer-title").textContent = item.title;
  $("#viewer-credit").textContent = credit(item);
  $(".viewer-actions").replaceChildren(sourceLink(item), heart(item));
  dialog.showModal();
  dialog.addEventListener("close", () => {
    $("#viewer-image").replaceChildren();
    (opener.isConnected ? opener : $("#page-title")).focus();
  }, { once: true });
}

function chinaDate() {
  return new Date(Date.now() + 8 * 3600000).toISOString().slice(0, 10);
}

function setNotice() {
  const notice = $("#notice");
  const parts = [];
  if (!navigator.onLine) parts.push("当前离线，可查看已缓存的档案。部分预览和原站暂不可用。");
  else if (page !== "saved" && issue && (datesFromCache || issue.cached)) {
    parts.push("暂时无法连接档案，正在展示已缓存的内容。");
  }
  if (page === "today" && issue && issue.date !== chinaDate()) {
    parts.push(`今日档案尚未更新，正在展示最近一期（${issue.date}）。`);
  }
  if (page !== "saved" && issue?.demo) parts.push("Demo · 当前内容仅用于界面演示。");
  notice.textContent = parts.join(" ");
  notice.hidden = !parts.length;
}

function render() {
  const [title, subtitle, heading] = pages[page];
  $("#page-title").textContent = title;
  $("#page-subtitle").textContent = subtitle;
  $("#collection-title").textContent = heading;
  $("#date-block").hidden = page !== "today";
  const date = $("#today-date");
  date.dateTime = chinaDate();
  date.textContent = date.dateTime.replaceAll("-", ".");
  document.querySelectorAll(".top nav a").forEach((link) => {
    if (link.hash === `#${page}`) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  setNotice();
  const items = page === "saved" ? [...saved.values()].reverse() : issue?.items || [];
  const selected = items.filter((item) => filter === "all" || filter === item.kind);
  const cover = page === "today" && filter === "all" && issue
    ? items.find((item) => item.kind !== "music" && item.id === issue.cover)
      || items.find((item) => item.kind !== "music")
    : null;
  const art = selected.filter((item) => item.kind !== "music" && item !== cover);
  const music = selected.filter((item) => item.kind === "music");
  showHero(cover, issue?.date);
  $("#controls").hidden = busy && !dates?.length;
  $("#archive-tools").hidden = page !== "archive" || !dates?.length;
  $("#saved-tools").hidden = page !== "saved";
  $("#export-saved").disabled = !saved.size;
  $("#collection-meta").textContent = page === "saved" ? `${items.length} 件作品`
    : issue ? `${issue.date}  /  ${items.length} 件作品` : "";
  const filters = $("#filters");
  filters.hidden = !items.length;
  filters.querySelectorAll("button").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.filter === filter)));
  $("#gallery").replaceChildren(...art.map(artCard));
  $("#music-list").replaceChildren(...music.map(musicCard));
  $("#listening").hidden = !music.length;
  const empty = $("#empty");
  empty.textContent = busy ? "正在打开档案…" : error || (filter !== "all" ? "这一类暂无作品，可切换其他分类。"
    : page === "saved" ? "在作品旁点一下爱心，它就会出现在这里。" : "还没有已发布的档案。");
  empty.hidden = !!selected.length;
}

async function json(path) {
  const response = await fetch(path, { cache: "no-cache", signal: AbortSignal.timeout(12000) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return { data: await response.json(), cached: response.headers.has("X-Artifact-Cached") };
}

async function showRoute() {
  const requested = location.hash.slice(1);
  const [route, date] = requested.split("/");
  page = Object.hasOwn(pages, route) ? route : "today";
  const token = ++revision;
  archiveDate = page === "archive" && datePattern.test(date || "") ? date : null;
  issue = null;
  filter = "all";
  error = "";
  busy = page !== "saved";
  render();
  if (!busy) return;
  try {
    if (!dates) {
      const { data: index, cached } = await json("./data/index.json");
      if (!Array.isArray(index.dates)) throw new Error("Invalid archive index");
      dates = [...new Set(index.dates.filter((entry) => typeof entry === "string" && datePattern.test(entry)))].sort().reverse();
      datesFromCache = cached;
      lastChecked = Date.now();
    }
    if (token !== revision) return;
    const selected = archiveDate || dates[0];
    $("#issue-select").replaceChildren(...dates.map((entry) => {
      const option = element("option", "", entry);
      option.value = entry;
      return option;
    }));
    if (selected && dates.includes(selected)) {
      $("#issue-select").value = selected;
      const { data, cached } = await json(`./data/archive/${selected}.json`);
      if (token !== revision) return;
      if (data.date !== selected || !Array.isArray(data.items)) throw new Error("Invalid issue");
      issue = { ...data, cached, items: data.items.map(cleanItem).filter(Boolean) };
    } else if (selected) {
      error = "找不到这期档案，请选择其他日期。";
    }
  } catch {
    if (token !== revision) return;
    error = navigator.onLine ? "暂时无法读取档案，请刷新页面重试。" : "这期档案还未缓存，联网后再试。";
  }
  busy = false;
  render();
}

for (const [key, name] of Object.entries(kinds)) {
  const button = element("button", "", name);
  button.type = "button";
  button.dataset.filter = key;
  button.addEventListener("click", () => { filter = key; render(); });
  $("#filters").append(button);
}
$("#page-title").tabIndex = -1;
$("#viewer-close").addEventListener("click", () => $("#viewer").close());
$("#viewer").addEventListener("click", (event) => {
  const box = event.currentTarget.getBoundingClientRect();
  if (event.target === event.currentTarget && (event.clientX < box.left || event.clientX > box.right
      || event.clientY < box.top || event.clientY > box.bottom)) event.currentTarget.close();
});
$(".skip").addEventListener("click", (event) => {
  event.preventDefault();
  $("#main").focus();
});
$("#issue-select").addEventListener("change", (event) => { location.hash = `archive/${event.target.value}`; });
$("#export-saved").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify([...saved.values()], null, 2)], { type: "application/json" }));
  const link = element("a");
  link.href = url;
  link.download = "ARTIFACT-收藏.json";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
});
$("#import-saved").addEventListener("click", () => $("#import-file").click());
$("#import-file").addEventListener("change", async (event) => {
  const [file] = event.target.files;
  event.target.value = "";
  if (!file) return;
  try {
    if (file.size > 5000000) throw new Error("Import too large");
    const parsed = JSON.parse(await file.text());
    if (!Array.isArray(parsed)) throw new Error("Invalid export");
    const items = parsed.map(cleanItem);
    if (items.some((item) => !item)) throw new Error("Invalid favorite");
    const existing = saved.size;
    for (const item of items) if (!saved.has(item.id)) saved.set(item.id, item);
    toast(persist() ? `已导入 ${saved.size - existing} 件新收藏` : "浏览器无法保存，导入内容仅在当前页面有效。");
    render();
  } catch {
    toast("无法读取这个文件，请选择 ARTIFACT 导出的收藏 JSON。");
  }
});
window.addEventListener("hashchange", showRoute);
window.addEventListener("offline", setNotice);
window.addEventListener("online", () => {
  if (page !== "saved" && (error || !issue || datesFromCache || issue.cached)) {
    dates = undefined;
    showRoute();
  }
  else setNotice();
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && page === "today" && !busy && navigator.onLine && Date.now() - lastChecked > 600000) {
    dates = undefined;
    showRoute();
  }
});
if ("serviceWorker" in navigator) navigator.serviceWorker.register("./sw.js").catch(console.warn);
showRoute();
