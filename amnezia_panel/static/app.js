const makeElement = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
};

const renderVariant = (variant) => {
  const card = makeElement("section", "config-card");
  card.append(makeElement("h3", "", variant.label));
  if (!variant.available) {
    card.append(makeElement("div", "config-message", "Файл этого варианта не найден"));
    return card;
  }
  if (variant.qr_available) {
    const image = makeElement("img");
    image.src = variant.qr_url;
    image.alt = `QR: ${variant.label}`;
    card.append(image);
  } else {
    card.append(makeElement("div", "config-message", "QR-код не найден"));
  }
  card.append(makeElement("pre", "config-text", variant.text));
  const links = makeElement("div", "config-links");
  const configLink = makeElement("a", "icon", `↓ ${variant.config_kind}`);
  configLink.href = variant.config_url;
  const copyButton = makeElement("button", "icon", "Копировать текст");
  copyButton.type = "button";
  copyButton.addEventListener("click", async () => {
    await navigator.clipboard.writeText(variant.text);
    copyButton.textContent = "Скопировано";
  });
  links.append(configLink, copyButton);
  if (variant.qr_available) {
    const qrLink = makeElement("a", "icon", "↓ QR");
    qrLink.href = variant.qr_download_url;
    links.append(qrLink);
  }
  card.append(links);
  return card;
};

const openConfigPreview = async (button) => {
  const dialog = document.getElementById("config-dialog");
  const variants = document.getElementById("config-variants");
  const loading = document.getElementById("config-loading");
  const error = document.getElementById("config-error");
  document.getElementById("config-title").textContent = button.dataset.name;
  variants.replaceChildren();
  loading.hidden = false;
  error.hidden = true;
  dialog.showModal();
  try {
    const response = await fetch(button.dataset.previewUrl, {headers: {Accept: "application/json"}, credentials: "same-origin"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    payload.variants.forEach((variant) => variants.append(renderVariant(variant)));
    loading.hidden = true;
  } catch (requestError) {
    loading.hidden = true;
    error.textContent = "Не удалось загрузить конфигурации. Обновите страницу и повторите.";
    error.hidden = false;
  }
};

document.addEventListener("click", (event) => {
  const opener = event.target.closest("[data-dialog]");
  if (opener) document.getElementById(opener.dataset.dialog)?.showModal();
  if (event.target.matches("[data-close]")) event.target.closest("dialog")?.close();

  const preview = event.target.closest("[data-config-preview]");
  if (preview) openConfigPreview(preview);

  const action = event.target.closest("[data-client-actions]");
  if (action) {
    const dialog = document.getElementById("actions-dialog");
    dialog.querySelectorAll(".action-key").forEach((input) => { input.value = action.dataset.key; });
    dialog.querySelector("#action-title").textContent = action.dataset.name;
    dialog.querySelector("#rename-input").value = action.dataset.name;
    dialog.querySelector("#notes-input").value = action.dataset.notes;
    dialog.querySelector("#tags-input").value = action.dataset.tags;
    const enabled = action.dataset.enabled === "1";
    const form = dialog.querySelector("#toggle-form");
    form.action = enabled ? "/clients/disable" : "/clients/enable";
    dialog.querySelector("#toggle-label").textContent = enabled ? "Отключить доступ" : "Включить доступ";
    dialog.showModal();
  }
});

document.addEventListener("submit", (event) => {
  const message = event.target.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
    return;
  }
  const button = event.submitter || event.target.querySelector("button[type='submit'], button:not([type])");
  if (button) {
    button.disabled = true;
    button.textContent = "Выполняется…";
  }
  event.target.setAttribute("aria-busy", "true");
});

const peerTable = document.getElementById("peer-table");
if (peerTable) {
  const stateKey = "amnezia-peer-table-state";
  const rows = [...peerTable.tBodies[0].querySelectorAll("tr[data-search]")];
  const search = document.getElementById("peer-search");
  const status = document.getElementById("peer-status");
  const summary = document.getElementById("peer-summary");
  let saved = {};
  try {
    saved = JSON.parse(window.sessionStorage.getItem(stateKey) || "{}");
  } catch (storageError) {
    saved = {};
  }
  search.value = typeof saved.search === "string" ? saved.search : "";
  if ([...status.options].some((option) => option.value === saved.status)) status.value = saved.status;
  let sortKey = typeof saved.sortKey === "string" ? saved.sortKey : "";
  let sortDirection = saved.sortDirection === "desc" ? "desc" : "asc";

  const saveState = () => {
    try {
      window.sessionStorage.setItem(stateKey, JSON.stringify({
        search: search.value,
        status: status.value,
        sortKey,
        sortDirection,
      }));
    } catch (storageError) {
      // The table remains usable when browser storage is unavailable.
    }
  };
  const applyFilters = (persist = true) => {
    const needle = search.value.trim().toLowerCase();
    let visible = 0;
    rows.forEach((row) => {
      row.hidden = !row.dataset.search.includes(needle) || (status.value && row.dataset.status !== status.value);
      if (!row.hidden) visible += 1;
    });
    summary.textContent = `Показано ${visible} из ${rows.length}`;
    if (persist) saveState();
  };

  const statusOrder = {active: 0, offline: 1, never: 2, disabled: 3};
  const compare = (left, right, type) => {
    if (type === "number") return Number(left || 0) - Number(right || 0);
    if (type === "ip") {
      const asNumber = (value) => value.split(".").reduce((result, part) => result * 256 + Number(part), 0);
      return asNumber(left) - asNumber(right);
    }
    if (type === "status") return statusOrder[left] - statusOrder[right];
    return (left || "").localeCompare(right || "", "ru");
  };
  const sortRows = (header, direction, persist = true) => {
    const key = header.dataset.sort;
    const type = header.dataset.sortType || "text";
    const multiplier = direction === "asc" ? 1 : -1;
    rows.sort((left, right) => multiplier * compare(left.dataset[key], right.dataset[key], type));
    rows.forEach((row) => peerTable.tBodies[0].appendChild(row));
    peerTable.querySelectorAll("th[data-sort]").forEach((item) => {
      item.dataset.direction = "";
      item.setAttribute("aria-sort", "none");
    });
    sortKey = key;
    sortDirection = direction;
    header.dataset.direction = direction;
    header.setAttribute("aria-sort", direction === "asc" ? "ascending" : "descending");
    if (persist) saveState();
  };

  search.addEventListener("input", () => applyFilters());
  status.addEventListener("change", () => applyFilters());
  peerTable.querySelectorAll("th[data-sort]").forEach((header) => header.addEventListener("click", () => {
    const direction = sortKey === header.dataset.sort && sortDirection === "asc" ? "desc" : "asc";
    sortRows(header, direction);
  }));
  const savedHeader = [...peerTable.querySelectorAll("th[data-sort]")].find((header) => header.dataset.sort === sortKey);
  if (savedHeader) sortRows(savedHeader, sortDirection, false);
  applyFilters(false);
}

const relativeTime = new Intl.RelativeTimeFormat("ru", {numeric: "auto"});
const updateRelativeTimes = () => {
  const now = Math.floor(Date.now() / 1000);
  document.querySelectorAll("[data-relative-time]").forEach((element) => {
    const difference = Number(element.dataset.timestamp) - now;
    const absolute = Math.abs(difference);
    if (absolute < 60) element.textContent = "только что";
    else if (absolute < 3600) element.textContent = relativeTime.format(Math.round(difference / 60), "minute");
    else if (absolute < 86400) element.textContent = relativeTime.format(Math.round(difference / 3600), "hour");
    else if (absolute < 2592000) element.textContent = relativeTime.format(Math.round(difference / 86400), "day");
    else element.textContent = relativeTime.format(Math.round(difference / 2592000), "month");
  });
};
updateRelativeTimes();
window.setInterval(updateRelativeTimes, 30000);

const auditTable = document.getElementById("audit-table");
if (auditTable) {
  const rows = [...auditTable.tBodies[0].querySelectorAll("tr[data-search]")];
  const search = document.getElementById("audit-search");
  const action = document.getElementById("audit-action");
  const date = document.getElementById("audit-date");
  const summary = document.getElementById("audit-summary");
  const applyFilters = () => {
    const needle = search.value.trim().toLowerCase();
    let visible = 0;
    rows.forEach((row) => {
      row.hidden = !row.dataset.search.includes(needle) || (action.value && row.dataset.action !== action.value) || (date.value && row.dataset.date !== date.value);
      if (!row.hidden) visible += 1;
    });
    summary.textContent = `Показано ${visible} из ${rows.length}`;
  };
  search.addEventListener("input", applyFilters);
  action.addEventListener("change", applyFilters);
  date.addEventListener("change", applyFilters);
  applyFilters();
}

const refreshButton = document.querySelector("[data-refresh]");
if (refreshButton) refreshButton.addEventListener("click", () => {
  refreshButton.disabled = true;
  refreshButton.textContent = "Обновление…";
  window.location.reload();
});

const autoRefresh = document.querySelector("[data-auto-refresh]");
if (autoRefresh) {
  const interval = Number(autoRefresh.dataset.autoRefresh);
  const status = document.querySelector("[data-refresh-status]");
  const updated = new Intl.DateTimeFormat("ru-RU", {timeZone: "Europe/Moscow", hour: "2-digit", minute: "2-digit", second: "2-digit"}).format(new Date());
  let remaining = Math.ceil(interval / 1000);
  const dialogIsOpen = () => document.querySelector("dialog[open]") !== null;
  const renderStatus = () => {
    status.textContent = dialogIsOpen()
      ? `Обновлено ${updated} МСК · автообновление приостановлено`
      : `Обновлено ${updated} МСК · следующее обновление через ${remaining} с`;
  };
  renderStatus();
  window.setInterval(() => {
    if (dialogIsOpen()) {
      renderStatus();
      return;
    }
    remaining = Math.max(0, remaining - 1);
    if (remaining === 0) {
      window.location.reload();
      return;
    }
    renderStatus();
  }, 1000);
}
