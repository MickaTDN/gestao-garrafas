import {
  MAX_FILE,
  validateTrust,
  summary,
  matches,
  low,
  integer,
} from "./domain.js";
import {
  state,
  enroll,
  importSnapshot,
  setAlert,
  markOrdered,
  finishOrder,
  backupPreferences,
  decodePreferences,
  restorePreferences,
} from "./store.js";

const content = document.querySelector("#content"),
  notice = document.querySelector("#notice");
let current,
  section = "stock",
  filter = "all",
  query = "",
  shown = 50,
  busy = false;
const labels = {
  all: "Todas as referências",
  positive: "Com stock",
  zero: "Stock zero",
  low: "Stock baixo",
  todo: "Por encomendar",
  ordered: "Já encomendadas",
};
function node(tag, text, className) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (className) e.className = className;
  return e;
}
function append(parent, ...children) {
  for (const child of children) if (child) parent.append(child);
  return parent;
}
function message(text, error = false) {
  notice.textContent = text;
  notice.className = error ? "error" : "";
  notice.hidden = false;
}
async function action(work, success) {
  if (busy) return;
  busy = true;
  document.querySelectorAll("button").forEach((b) => {
    b.disabled = true;
  });
  try {
    await work();
    if (success) message(success);
    await refresh();
  } catch (error) {
    message(error.message || "Não foi possível concluir a operação.", true);
  } finally {
    busy = false;
    document.querySelectorAll("button").forEach((b) => {
      b.disabled = false;
    });
  }
}
function button(label, callback, secondary = false) {
  const b = node("button", label, secondary ? "secondary" : "");
  b.type = "button";
  b.addEventListener("click", callback);
  return b;
}
function confirm(title, text) {
  const dialog = document.querySelector("#confirmation");
  document.querySelector("#confirm-title").textContent = title;
  document.querySelector("#confirm-text").textContent = text;
  dialog.returnValue = "cancel";
  dialog.showModal();
  return new Promise((resolve) =>
    dialog.addEventListener(
      "close",
      () => resolve(dialog.returnValue === "yes"),
      { once: true },
    ),
  );
}
function date(value) {
  return new Intl.DateTimeFormat("pt-PT", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}
async function fileJSON(input, max = MAX_FILE) {
  const file = input.files[0];
  if (!file) throw new Error("Selecione um ficheiro.");
  if (file.size > max)
    throw new Error("O ficheiro excede o tamanho permitido.");
  try {
    return JSON.parse(await file.text());
  } catch (_) {
    throw new Error("O ficheiro não contém JSON válido.");
  }
}
function download(data, filename) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data)], { type: "application/json" }),
  );
  const link = node("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
function field(label, type, id, options = {}) {
  const wrap = node("div"),
    l = node("label", label),
    input = node("input");
  input.type = type;
  input.id = id;
  l.htmlFor = id;
  Object.assign(input, options);
  append(wrap, l, input);
  return { wrap, input };
}
function connection() {
  document.querySelector("#connection").textContent = navigator.onLine
    ? "Ligação disponível · o stock continua a ser a última cópia importada."
    : "Sem ligação · consulta e acompanhamento locais disponíveis.";
}
function stamp() {
  const card = node("section", undefined, "stamp");
  if (!current.copy)
    return append(
      card,
      node("h2", "Ainda não existe uma cópia válida"),
      node(
        "p",
        "Configure a origem autorizada e importe uma atualização assinada em Atualizações e cópias.",
      ),
    );
  const data = current.copy.data;
  append(
    card,
    node("h2", "A sua fotografia de stock"),
    node("p", "Stock exportado em " + date(data.exported_at)),
    node("p", "Última importação: " + date(current.copy.imported_at), "muted"),
    node(
      "p",
      "Não é stock em tempo real. As encomendas locais não alteram estas quantidades.",
      "muted",
    ),
  );
  if (Date.now() - Date.parse(data.exported_at) > 86400000)
    append(
      card,
      node(
        "p",
        "Cópia desatualizada: tem mais de 24 horas. Confirme uma atualização com o escritório.",
        "warning",
      ),
    );
  if (Date.parse(data.exported_at) > Date.now() + 300000)
    append(
      card,
      node(
        "p",
        "Verifique o relógio do dispositivo: a cópia indica uma data futura.",
        "warning",
      ),
    );
  if (current.recovered)
    append(
      card,
      node(
        "p",
        "Foi recuperada a última cópia válida disponível. Uma cópia mais recente ficou ilegível; peça uma nova exportação.",
        "warning",
      ),
    );
  return card;
}
function ordersFor(id) {
  return current.orders.filter(
    (o) => o.reference_id === id && o.state === "open",
  );
}
function referenceCard(ref, absent = false) {
  const card = node("article", undefined, "card reference-card");
  card.dataset.id = ref.id;
  const alerts = new Map(current.alerts.map((a) => [a.id, a]));
  append(
    card,
    node("p", ref.code + " · ID " + ref.id, "code"),
    node("h3", ref.name),
  );
  if (absent)
    append(
      card,
      node(
        "p",
        "Ausente ou desativada na origem — sem stock ativo disponível nesta cópia.",
        "badge absent",
      ),
    );
  else {
    append(
      card,
      append(
        node("p", undefined, "quantity"),
        node("span", String(ref.bottles)),
        node("small", " garrafas"),
      ),
    );
    append(
      card,
      node(
        "p",
        ref.box_capacity === null
          ? "Capacidade por caixa desconhecida."
          : Math.floor(ref.bottles / ref.box_capacity) +
              " caixas completas + " +
              (ref.bottles % ref.box_capacity) +
              " garrafas soltas.",
        "muted",
      ),
    );
    append(
      card,
      node(
        "span",
        ref.bottles === 0
          ? "Sem stock"
          : low(ref, alerts)
            ? "Stock baixo"
            : "Disponível",
        "badge " + (ref.bottles === 0 ? "zero" : low(ref, alerts) ? "low" : ""),
      ),
    );
    if (ref.bottles === 0 && low(ref, alerts))
      append(card, node("span", "Stock baixo", "badge low"));
  }
  const open = ordersFor(ref.id);
  for (const order of open) {
    append(
      card,
      node("p", "Já encomendada · " + date(order.created_at), "badge low"),
    );
    const actions = node("div", undefined, "actions");
    append(
      actions,
      button("Encerrar acompanhamento", async () => {
        if (
          await confirm(
            "Encerrar acompanhamento",
            "Confirma que pretende encerrar este acompanhamento? Não altera o stock.",
          )
        )
          action(
            () => finishOrder(order.id, "closed"),
            "Acompanhamento encerrado.",
          );
      }),
      button(
        "Anular marcação",
        async () => {
          if (
            await confirm(
              "Anular marcação",
              "Desfazer a marcação por engano? O registo fica no histórico local.",
            )
          )
            action(
              () => finishOrder(order.id, "cancelled"),
              "Marcação anulada.",
            );
        },
        true,
      ),
    );
    append(card, actions);
  }
  if (!absent && low(ref, alerts) && !open.length)
    append(
      card,
      button("Já encomendada", async () => {
        if (
          await confirm(
            "Já encomendada",
            "Registar o acompanhamento de " +
              ref.code +
              "? Não cria uma compra nem altera stock.",
          )
        )
          action(
            () => markOrdered(ref),
            "Encomenda registada apenas neste dispositivo.",
          );
      }),
    );
  const details = node("details"),
    title = node(
      "summary",
      alerts.has(ref.id)
        ? "Alerta mínimo: " + alerts.get(ref.id).limit + " garrafas"
        : "Configurar alerta mínimo",
    );
  details.append(title);
  if (absent && !alerts.has(ref.id)) {
    append(
      details,
      node(
        "p",
        "O histórico de acompanhamento é preservado. Não se cria um alerta novo para stock ausente.",
        "muted",
      ),
    );
  } else {
    const form = node("form", undefined, "alert-form"),
      limit = field("Limite de garrafas", "number", "minimum-" + ref.id, {
        min: "0",
        max: "2147483647",
        step: "1",
        inputMode: "numeric",
        required: true,
        value: alerts.has(ref.id) ? String(alerts.get(ref.id).limit) : "",
      });
    const save = node("button", "Guardar alerta");
    save.type = "submit";
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const raw = limit.input.value;
      if (!/^\d+$/.test(raw) || !integer(Number(raw))) {
        message("Indique um limite inteiro de garrafas.", true);
        return;
      }
      action(
        () => setAlert(ref, Number(raw)),
        "Alerta guardado neste dispositivo.",
      );
    });
    append(form, limit.wrap, save);
    if (alerts.has(ref.id))
      append(
        form,
        button(
          "Desativar alerta",
          () =>
            action(
              () => setAlert(ref, null),
              "Alerta desativado. A encomenda mantém o seu estado.",
            ),
          true,
        ),
      );
    append(details, form);
  }
  append(card, details);
  return card;
}
function list(target) {
  const alerts = new Map(current.alerts.map((a) => [a.id, a])),
    refs = current.copy?.data.references || [];
  const found = refs.filter((r) =>
    matches(r, filter, query, alerts, current.orders),
  );
  if (filter === "ordered")
    for (const old of current.tracked)
      if (
        !refs.some((r) => r.id === old.id) &&
        ordersFor(old.id).length &&
        (old.name + " " + old.code)
          .normalize("NFD")
          .replace(/\p{Diacritic}/gu, "")
          .toLowerCase()
          .includes(
            query
              .normalize("NFD")
              .replace(/\p{Diacritic}/gu, "")
              .toLowerCase(),
          )
      )
        found.push({ ...old, absent: true });
  found.sort((a, b) =>
    a.name.localeCompare(b.name, "pt", { sensitivity: "base" }),
  );
  target.replaceChildren(
    node("p", found.length + " referências nesta lista.", "result-count"),
  );
  const cards = node("div", undefined, "cards");
  for (const ref of found.slice(0, shown))
    cards.append(referenceCard(ref, Boolean(ref.absent)));
  append(target, cards);
  if (!found.length)
    append(
      target,
      node(
        "p",
        "Não foram encontradas referências para estes critérios.",
        "empty",
      ),
    );
  if (found.length > shown)
    append(
      target,
      button(
        "Mostrar mais referências",
        () => {
          shown += 50;
          list(target);
        },
        true,
      ),
    );
}
function stock() {
  content.append(stamp());
  const counts = summary(
      current.copy?.data.references || [],
      new Map(current.alerts.map((a) => [a.id, a])),
      current.orders,
    ),
    metrics = node("section", undefined, "metrics");
  metrics.setAttribute("aria-label", "Indicadores");
  for (const key of ["all", "zero", "low", "todo", "ordered"]) {
    const b = button("", () => {
      filter = key;
      shown = 50;
      render();
      document.querySelector("#filter").focus();
    });
    b.className = "metric";
    b.dataset.filter = key;
    append(b, node("strong", String(counts[key])), node("span", labels[key]));
    if (key === "ordered" && counts.missingOrdered)
      append(b, node("small", counts.missingOrdered + " fora da cópia ativa"));
    metrics.append(b);
  }
  content.append(metrics);
  const toolbar = node("div", undefined, "toolbar"),
    search = field("Pesquisar designação ou código", "search", "search", {
      value: query,
      placeholder: "Pesquisar referências",
      autocomplete: "off",
    }),
    filterWrap = node("div"),
    label = node("label", "Filtrar referências"),
    select = node("select");
  select.id = "filter";
  label.htmlFor = "filter";
  for (const [value, name] of Object.entries(labels)) {
    const option = node("option", name);
    option.value = value;
    select.append(option);
  }
  select.value = filter;
  const results = node("section");
  results.id = "results";
  search.input.addEventListener("input", () => {
    query = search.input.value;
    shown = 50;
    list(results);
  });
  select.addEventListener("change", () => {
    filter = select.value;
    shown = 50;
    list(results);
  });
  append(filterWrap, label, select);
  append(toolbar, search.wrap, filterWrap);
  append(content, toolbar, results);
  list(results);
}
function orders() {
  append(
    content,
    stamp(),
    node("h2", "Acompanhamento de encomendas"),
    node(
      "p",
      "Marcações pessoais. Receber uma atualização não encerra automaticamente encomendas.",
      "muted",
    ),
  );
  const cards = node("section", undefined, "cards");
  const refs = current.copy?.data.references || [];
  for (const order of current.orders.filter((o) => o.state === "open")) {
    const ref =
      refs.find((r) => r.id === order.reference_id) ||
      current.tracked.find((r) => r.id === order.reference_id);
    if (ref)
      cards.append(referenceCard(ref, !refs.some((r) => r.id === ref.id)));
  }
  if (!cards.childElementCount)
    cards.append(node("p", "Não existem acompanhamentos abertos.", "empty"));
  append(content, cards);
  const past = node("details");
  append(
    past,
    node("summary", "Histórico de acompanhamentos encerrados ou anulados"),
  );
  for (const order of current.orders
    .filter((o) => o.state !== "open")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))) {
    const ref = current.tracked.find((r) => r.id === order.reference_id);
    append(
      past,
      node(
        "p",
        (ref?.code || order.reference_id) +
          " · " +
          (ref?.name || "Referência histórica") +
          " · " +
          (order.state === "closed" ? "Encerrado" : "Anulado") +
          " em " +
          date(order.ended_at),
        "card",
      ),
    );
  }
  append(content, past);
}
function settings() {
  append(
    content,
    node("h2", "Atualizações e cópias"),
    node(
      "p",
      "O stock oficial permanece no escritório. Esta aplicação nunca envia movimentos ou alterações de stock.",
      "muted",
    ),
  );
  const stack = node("section", undefined, "stack");
  const update = node("article", undefined, "card");
  append(
    update,
    node("h3", "Importar atualização de stock"),
    node(
      "p",
      "Selecione uma fotografia completa e assinada. A cópia anterior só é substituída depois de todas as verificações.",
    ),
  );
  const file = field("Ficheiro de atualização de stock", "file", "stock-file", {
    accept: ".json,application/json",
  });
  append(
    update,
    file.wrap,
    button("Importar atualização de stock", () =>
      action(async () => {
        const json = await fileJSON(file.input);
        await importSnapshot(json);
      }, "Atualização verificada e importada. Alertas e encomendas preservados."),
    ),
  );
  const trust = node("article", undefined, "card");
  append(
    trust,
    node("h3", "Origem e chave autorizadas"),
    node(
      "p",
      "Obtenha o ficheiro de origem junto da informática e confirme o fingerprint por um canal independente. Não confie apenas no ficheiro recebido.",
    ),
  );
  if (current.trust) {
    append(
      trust,
      node("p", "Origem fixada: " + current.trust.source_id, "fingerprint"),
    );
    if (current.watermark)
      append(
        trust,
        node(
          "p",
          "Última atualização aceite: sequência " +
            current.watermark.sequence +
            " · " +
            current.watermark.update_id,
          "fingerprint",
        ),
      );
    for (const k of current.trust.keys.filter((k) => !k.revoked))
      append(trust, node("p", "SHA-256: " + k.key_id, "fingerprint"));
  }
  const trustFile = field(
      "Ficheiro de origem autorizada",
      "file",
      "trust-file",
      { accept: ".json,application/json" },
    ),
    fp = field(
      "Fingerprint SHA-256 confirmado com a informática",
      "text",
      "trust-fingerprint",
      {
        autocomplete: "off",
        maxLength: 64,
        placeholder: "64 caracteres hexadecimais",
      },
    );
  append(
    trust,
    trustFile.wrap,
    fp.wrap,
    button("Instalar ou atualizar chave pública", async () => {
      try {
        const bundle = await validateTrust(
          await fileJSON(trustFile.input, 65536),
        );
        if (
          await confirm(
            "Confirmar origem e chave",
            "Origem: " +
              bundle.source_id +
              "\nFingerprints:\n" +
              bundle.keys.map((k) => k.key_id).join("\n") +
              "\nConfirme com a informática por um canal independente. As chaves anteriores deixam de autorizar novas atualizações.",
          )
        )
          action(
            () => enroll(bundle, fp.input.value),
            "Origem e chaves públicas confirmadas.",
          );
      } catch (e) {
        message(e.message, true);
      }
    }),
  );
  const backup = node("article", undefined, "card");
  append(
    backup,
    node("h3", "Proteger preferências"),
    node(
      "p",
      "Backup cifrado dos alertas e acompanhamentos. Não inclui stock, credenciais nem chave privada. Limpar dados do browser, desinstalar ou trocar de telemóvel pode apagar os dados locais.",
    ),
  );
  const password = field(
      "Frase-passe para proteger o backup",
      "password",
      "backup-password",
      { minLength: 12, autocomplete: "new-password" },
    ),
    repeat = field("Repetir frase-passe", "password", "backup-repeat", {
      minLength: 12,
      autocomplete: "new-password",
    });
  append(
    backup,
    password.wrap,
    repeat.wrap,
    button("Exportar preferências cifradas", () =>
      action(async () => {
        try {
          if (password.input.value !== repeat.input.value)
            throw new Error("As frases-passe não coincidem.");
          download(
            await backupPreferences(password.input.value),
            "vertente-preferencias.vaprefs.json",
          );
        } finally {
          password.input.value = "";
          repeat.input.value = "";
        }
      }, "Backup cifrado preparado. Guarde o ficheiro e a frase-passe separadamente."),
    ),
  );
  const restore = node("article", undefined, "card");
  append(
    restore,
    node("h3", "Restaurar preferências"),
    node(
      "p",
      "Configure primeiro a mesma origem. O restauro substitui apenas alertas e acompanhamentos; não altera a cópia de stock.",
    ),
  );
  const restoreFile = field(
      "Backup de preferências cifradas",
      "file",
      "restore-file",
      { accept: ".json,application/json" },
    ),
    restorePass = field(
      "Frase-passe do backup",
      "password",
      "restore-password",
      { autocomplete: "off" },
    );
  append(
    restore,
    restoreFile.wrap,
    restorePass.wrap,
    button("Restaurar preferências", async () => {
      try {
        const data = await decodePreferences(
          await fileJSON(restoreFile.input),
          restorePass.input.value,
        );
        restorePass.input.value = "";
        if (
          await confirm(
            "Substituir preferências locais",
            data.alerts.length +
              " alertas e " +
              data.orders.length +
              " acompanhamentos. A fotografia de stock permanece igual.",
          )
        )
          action(() => restorePreferences(data), "Preferências restauradas.");
      } catch (e) {
        restorePass.input.value = "";
        message(e.message, true);
      }
    }),
  );
  append(stack, update, trust, backup, restore);
  append(content, stack);
  if (navigator.storage?.persist)
    append(
      content,
      button(
        "Pedir conservação dos dados neste dispositivo",
        () =>
          action(async () => {
            const granted = await navigator.storage.persist();
            message(
              granted
                ? "O browser autorizou armazenamento persistente. Mantenha backups."
                : "O browser não garantiu persistência. Faça backups das preferências.",
            );
          }),
        true,
      ),
    );
}
function render() {
  content.replaceChildren();
  connection();
  for (const key of ["stock", "orders", "settings"]) {
    const b = document.querySelector("#nav-" + key);
    if (key === section) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  }
  if (section === "stock") stock();
  else if (section === "orders") orders();
  else settings();
}
async function refresh() {
  current = await state();
  render();
}
for (const key of ["stock", "orders", "settings"])
  document.querySelector("#nav-" + key).addEventListener("click", () => {
    section = key;
    render();
  });
window.addEventListener("online", connection);
window.addEventListener("offline", connection);
window.addEventListener("pageshow", () => {
  if (current) refresh().catch((e) => message(e.message, true));
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && current && section !== "settings" && !busy)
    refresh().catch((e) => message(e.message, true));
});
let installEvent;
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installEvent = event;
  document.querySelector("#install").hidden = false;
});
document.querySelector("#install").addEventListener("click", async () => {
  if (installEvent) {
    await installEvent.prompt();
    installEvent = null;
    document.querySelector("#install").hidden = true;
  }
});
if (!window.isSecureContext || !crypto.subtle || !window.indexedDB)
  message(
    "Esta aplicação exige um browser atualizado, HTTPS confiável e armazenamento local disponível.",
    true,
  );
else {
  if ("serviceWorker" in navigator)
    navigator.serviceWorker
      .register("/service-worker.js")
      .catch(() =>
        message(
          "Não foi possível preparar o funcionamento offline. Verifique HTTPS e o armazenamento antes de sair da rede.",
          true,
        ),
      );
  refresh().catch((e) => message(e.message, true));
}
