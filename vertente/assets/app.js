import {
  MAX_FILE,
  summary,
  matches,
  low,
  pending,
  orderReceived,
} from "./domain.js";
import {
  state,
  enroll,
  activate,
  deviceRequest,
  unlock,
  lock,
  touch,
  importSnapshot,
  createOrder,
  editOrder,
  backupPreferences,
  decodePreferences,
  restorePreferences,
  quantity,
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
    const outcome = await work();
    if (success && outcome !== false) message(success);
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
const isOwner = () => current?.authorized && current.grant.role === "owner";
function equivalent(bottles, capacity) {
  return capacity
    ? `${Math.floor(bottles / capacity)} caixas + ${bottles % capacity} garrafas soltas`
    : `${bottles} garrafas · capacidade da caixa não definida`;
}
function optionalNumber(input) {
  if (input.value.trim() === "") return null;
  if (!/^\d+$/.test(input.value))
    throw new Error("Indique um número inteiro não negativo.");
  return Number(input.value);
}
function inputQuantities(ref, values = { boxes: null, units: null }) {
  const boxes = field("Caixas", "number", "boxes", {
    min: "0",
    step: "1",
    value: values.boxes ?? "",
    disabled: !ref.box_capacity,
  });
  const units = field("Garrafas soltas", "number", "units", {
    min: "0",
    step: "1",
    value: values.units ?? "",
  });
  const preview = node("p", "Quantidade não definida", "muted");
  const update = () => {
    try {
      const q = quantity(
        optionalNumber(boxes.input),
        optionalNumber(units.input),
        ref.box_capacity,
        { optional: true },
      );
      preview.textContent =
        q === null ? "Quantidade não definida" : `${q} garrafas no total`;
    } catch (e) {
      preview.textContent = e.message;
    }
  };
  boxes.input.addEventListener("input", update);
  units.input.addEventListener("input", update);
  update();
  return { boxes, units, preview };
}
function connection() {
  document.querySelector("#connection").textContent = navigator.onLine
    ? "Consulta da última cópia importada · não é stock em tempo real."
    : "Sem ligação · a consulta e os dados guardados neste dispositivo continuam disponíveis.";
}
function stamp() {
  const card = node("section", undefined, "stamp");
  if (!current.copy)
    return append(
      card,
      node("h2", "Importe a primeira cópia de stock"),
      node("p", "Use Importar Stock em Atualizações e cópias."),
    );
  append(
    card,
    node("h2", "Última atualização de stock"),
    node("p", date(current.copy.data.exported_at)),
    node(
      "p",
      "Importado neste dispositivo: " + date(current.copy.imported_at),
      "muted",
    ),
  );
  if (Date.now() - Date.parse(current.copy.data.exported_at) > 86400000)
    append(
      card,
      node(
        "p",
        "Cópia desatualizada: tem mais de 24 horas. Peça uma atualização ao escritório.",
        "warning",
      ),
    );
  if (current.recovered)
    append(
      card,
      node(
        "p",
        "Foi recuperada a última cópia válida. Peça nova exportação; o marcador de atualização e as encomendas não foram revertidos.",
        "warning",
      ),
    );
  return card;
}
function unlockForm() {
  const card = node("section", undefined, "card"),
    pass = field("Frase-passe do cofre", "password", "vault-password", {
      required: true,
      minLength: 16,
      autocomplete: "off",
    }),
    form = node("form");
  append(
    card,
    node(
      "h2",
      current.vaultExists
        ? "Desbloquear Proprietário"
        : "Proteger as encomendas",
    ),
  );
  append(
    card,
    node(
      "p",
      current.vaultExists
        ? "A consulta de stock está disponível. Desbloqueie para gerir encomendas, alertas e importações."
        : "Escolha uma frase-passe de pelo menos 16 caracteres. Não fica guardada e não pode ser recuperada. Proteja também o dispositivo.",
      "muted",
    ),
  );
  let repeated = null;
  if (!current.vaultExists)
    repeated = field(
      "Repetir frase-passe do cofre",
      "password",
      "vault-repeat",
      { required: true, minLength: 16, autocomplete: "off" },
    );
  const submit = node(
    "button",
    current.vaultExists ? "Desbloquear" : "Criar cofre",
  );
  submit.type = "submit";
  append(form, pass.wrap, repeated?.wrap, submit);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    action(async () => {
      if (repeated && pass.input.value !== repeated.input.value)
        throw new Error("As frases-passe não coincidem.");
      await unlock(pass.input.value);
      pass.input.value = "";
      if (repeated) repeated.input.value = "";
    }, "Cofre desbloqueado.");
  });
  return append(card, form);
}
function setup() {
  const wrap = node("section", undefined, "stack");
  append(
    wrap,
    node("h2", "Ativação do dispositivo"),
    node(
      "p",
      current.authError ||
        "A informática autoriza individualmente este dispositivo. Não existe seleção livre de perfil.",
    ),
  );
  const trust = node("form", undefined, "card stack"),
    file = field("Origem autorizada (.vatrust.json)", "file", "trust-file", {
      accept: ".json",
    }),
    fp = field(
      "Fingerprint da origem confirmado pela informática",
      "text",
      "trust-fingerprint",
      { required: true },
    );
  const submit = node("button", "Instalar origem autorizada");
  submit.type = "submit";
  append(
    trust,
    node("h3", "1. Origem de stock"),
    node(
      "p",
      "Confirme o fingerprint completo por um canal independente. Uma rotação exige prova assinada pela chave anterior.",
      "muted",
    ),
    file.wrap,
    fp.wrap,
    submit,
  );
  trust.addEventListener("submit", (e) => {
    e.preventDefault();
    action(async () => {
      const data = await fileJSON(file.input);
      await enroll(data, fp.input.value);
    }, "Origem autorizada guardada.");
  });
  const device = node("section", undefined, "card stack");
  append(
    device,
    node("h3", "2. Pedido de autorização"),
    node(
      "p",
      "Transfira o pedido e confirme presencialmente o fingerprint no ecrã com a informática. A chave privada deste dispositivo não é exportada.",
    ),
  );
  if (current.device)
    append(
      device,
      node(
        "p",
        "Fingerprint do dispositivo: " + current.device.key_id,
        "fingerprint",
      ),
    );
  append(
    device,
    button("Criar / exportar pedido do dispositivo", () =>
      action(async () =>
        download(await deviceRequest(), "stock-dispositivo.varequest.json"),
      ),
    ),
  );
  const grant = node("form", undefined, "card stack"),
    gf = field("Autorização assinada do dispositivo", "file", "grant-file", {
      accept: ".json",
    }),
    go = node("button", "Ativar dispositivo");
  go.type = "submit";
  append(grant, node("h3", "3. Ativar acesso"), gf.wrap, go);
  grant.addEventListener("submit", (e) => {
    e.preventDefault();
    action(
      async () => activate(await fileJSON(gf.input)),
      "Dispositivo autorizado.",
    );
  });
  append(wrap, trust, device, grant);
  return wrap;
}
function referenceDetail(ref) {
  content.replaceChildren(stamp());
  const card = node("section", undefined, "card stack");
  append(
    card,
    button("Voltar à lista", () => render(), true),
    node("h2", ref.name),
    node("p", equivalent(ref.bottles, ref.box_capacity), "quantity"),
    node("p", `${ref.bottles} garrafas no total`),
    node("p", "Localização: " + ref.location),
    node("p", "Setor: " + (ref.sector || "Sem setor definido")),
    node(
      "p",
      ref.bottles === 0 ? "Sem stock disponível" : "Com stock disponível",
    ),
  );
  if (isOwner() && current.unlocked) {
    append(
      card,
      node(
        "p",
        ref.minimum === null
          ? "Sem alerta de stock mínimo configurado"
          : `Mínimo configurado na Gestão: ${ref.minimum} garrafas · ${low(ref) ? "Stock baixo" : "Acima do limite"}`,
      ),
    );
    append(
      card,
      button("Criar encomenda", () => orderForm(ref)),
    );
  }
  content.append(card);
}
function orderForm(ref, existing = null) {
  if (!isOwner() || !current.unlocked) {
    message("Desbloqueie o Proprietário.", true);
    return;
  }
  content.replaceChildren(stamp());
  const form = node("form", undefined, "card stack"),
    q = inputQuantities(ref, existing || undefined),
    note = field("Observação (opcional)", "text", "order-note", {
      maxLength: 1000,
      value: existing?.note || "",
    }),
    day = field("Data da encomenda", "date", "order-date", {
      required: true,
      value: existing?.ordered_on || new Date().toISOString().slice(0, 10),
      disabled: !!existing,
    });
  append(
    form,
    node("h2", (existing ? "Editar encomenda · " : "Encomendar · ") + ref.name),
    node(
      "p",
      "A quantidade é opcional. Qualquer Entrada confirmada posterior ao registo pode receber esta encomenda; a atribuição é automática por ordem cronológica.",
      "muted",
    ),
    day.wrap,
    q.boxes.wrap,
    q.units.wrap,
    q.preview,
    note.wrap,
  );
  if (!ref.box_capacity)
    append(
      form,
      node(
        "p",
        "Capacidade desconhecida: indique apenas garrafas, se desejar definir uma quantidade.",
        "muted",
      ),
    );
  const save = node("button", "Guardar encomenda");
  save.type = "submit";
  append(
    form,
    save,
    button("Cancelar", () => render(), true),
  );
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    action(async () => {
      const data = {
        boxes: optionalNumber(q.boxes.input),
        units: optionalNumber(q.units.input),
        note: note.input.value,
        ordered_on: day.input.value,
      };
      if (existing) await editOrder(existing.id, data);
      else await createOrder(ref.id, data);
      section = "orders";
    }, "Encomenda guardada neste dispositivo. O stock oficial não foi alterado.");
  });
  content.append(form);
}
function stockView() {
  append(content, stamp());
  if (isOwner() && !current.unlocked) content.append(unlockForm());
  const refs = current.copy?.data.references || [],
    owner = isOwner() && current.unlocked;
  if (!owner && !["all", "positive", "zero"].includes(filter)) filter = "all";
  const counts = summary(refs, current.orders),
    panel = node("section", undefined, "stats");
  for (const name of owner
    ? ["all", "zero", "low", "todo", "ordered"]
    : ["all", "zero"]) {
    const b = button(`${counts[name]} · ${labels[name]}`, () => {
      filter = name;
      shown = 50;
      render();
    });
    b.dataset.filter = name;
    panel.append(b);
  }
  content.append(panel);
  const controls = node("section", undefined, "card stack"),
    search = field("Pesquisar pelo nome", "search", "search", {
      value: query,
      placeholder: "Nome da referência",
      autocomplete: "off",
    }),
    select = node("select");
  select.id = "filter";
  select.setAttribute("aria-label", "Filtrar referências");
  for (const name of owner
    ? Object.keys(labels)
    : ["all", "positive", "zero"]) {
    const option = node("option", labels[name]);
    option.value = name;
    select.append(option);
  }
  select.value = filter;
  const list = node("section", undefined, "stack");
  list.id = "reference-list";
  function results() {
    list.replaceChildren();
    const found = refs.filter((r) => matches(r, filter, query, current.orders));
    list.append(node("p", `${found.length} referências`, "muted"));
    for (const ref of found.slice(0, shown)) {
      const card = node("article", undefined, "card reference");
      const name = button(ref.name, () => referenceDetail(ref), true);
      name.classList.add("reference-name");
      append(card, name, node("p", equivalent(ref.bottles, ref.box_capacity)));
      if (owner && low(ref))
        append(card, node("span", "Stock baixo", "badge warning"));
      list.append(card);
    }
    if (found.length > shown)
      list.append(
        button(
          "Mostrar mais referências",
          () => {
            shown += 50;
            results();
          },
          true,
        ),
      );
  }
  search.input.addEventListener("input", () => {
    query = search.input.value;
    shown = 50;
    results();
  });
  select.addEventListener("change", () => {
    filter = select.value;
    shown = 50;
    results();
  });
  append(controls, search.wrap, select);
  append(content, controls, list);
  results();
}
const orderLabels = {
  waiting: "A aguardar entrada",
  partial: "Parcialmente recebida",
  received: "Recebida",
  cancelled: "Cancelada",
};
let orderTab = "pending";
function ordersView() {
  if (!isOwner()) {
    section = "stock";
    stockView();
    return;
  }
  append(content, stamp());
  if (!current.unlocked) {
    content.append(unlockForm());
    return;
  }
  const refs = current.copy?.data.references || [];
  append(
    content,
    node("h2", "Encomendas"),
    node(
      "p",
      "Receções associadas automaticamente por referência e instante de confirmação. Esta associação não comprova a ligação a uma compra.",
      "muted",
    ),
  );
  const tabs = node("div", undefined, "actions");
  append(
    tabs,
    button(
      "Pendentes",
      () => {
        orderTab = "pending";
        render();
      },
      orderTab !== "pending",
    ),
    button(
      "Concluídas",
      () => {
        orderTab = "done";
        render();
      },
      orderTab !== "done",
    ),
  );
  content.append(tabs);
  const orders = current.orders
    .filter((o) => pending(o) === (orderTab === "pending"))
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  if (!orders.length)
    content.append(
      node(
        "p",
        "Não existem encomendas nesta lista. Abra uma referência de stock para criar uma encomenda.",
        "card",
      ),
    );
  for (const o of orders) {
    const card = node("article", undefined, "card stack"),
      received = current.allocations
        .filter((a) => a.order_id === o.id)
        .reduce((n, a) => n + a.bottles, 0),
      ref = refs.find((r) => r.id === o.reference_id);
    append(
      card,
      node("h3", ref?.name || o.name),
      node("p", orderLabels[o.state], "badge"),
      node("p", "Data da encomenda: " + o.ordered_on),
      node("p", "Registada em " + date(o.created_at), "muted"),
      node(
        "p",
        o.quantity === null
          ? "Quantidade encomendada não definida"
          : "Encomendado: " + equivalent(o.quantity, o.box_capacity),
      ),
      node("p", "Recebido: " + equivalent(received, o.box_capacity)),
    );
    if (o.quantity !== null)
      append(
        card,
        node(
          "p",
          "Falta receber: " +
            equivalent(Math.max(0, o.quantity - received), o.box_capacity),
        ),
      );
    if (!ref)
      append(
        card,
        node(
          "p",
          "Referência ausente ou desativada na última atualização. O acompanhamento foi preservado.",
          "warning",
        ),
      );
    if (o.gap)
      append(
        card,
        node(
          "p",
          "Histórico de receções incompleto. Peça à informática ficheiros de recuperação desde " +
            date(o.created_at) +
            ". Não se presumiram receções.",
          "warning",
        ),
      );
    if (o.note) append(card, node("p", o.note));
    for (const a of current.allocations.filter((a) => a.order_id === o.id)) {
      const r = current.receipts.find((r) => r.id === a.receipt_id);
      append(
        card,
        node(
          "p",
          "Entrada de " +
            date(r.confirmed_at) +
            " · " +
            equivalent(a.bottles, r.box_capacity),
          "muted",
        ),
      );
    }
    if (pending(o)) {
      if (!received)
        append(
          card,
          button(
            "Editar encomenda",
            () =>
              orderForm(
                {
                  id: o.reference_id,
                  name: ref?.name || o.name,
                  box_capacity: o.box_capacity,
                },
                o,
              ),
            true,
          ),
        );
      append(
        card,
        button(
          "Cancelar encomenda",
          () =>
            action(async () => {
              if (
                !(await confirm(
                  "Cancelar encomenda",
                  "As receções já associadas ficam preservadas e não serão usadas para outra encomenda.",
                ))
              )
                return false;
              await editOrder(o.id, { note: o.note, cancel: true });
            }, "Encomenda cancelada."),
          true,
        ),
      );
    }
    content.append(card);
  }
}
function settingsView() {
  append(content, stamp());
  if (isOwner()) {
    if (!current.unlocked) content.append(unlockForm());
    else
      content.append(
        button(
          "Bloquear Proprietário",
          () => {
            lock();
            refresh();
          },
          true,
        ),
      );
  }
  append(
    content,
    node(
      "p",
      `Perfil: ${isOwner() ? "Proprietário" : "Empregado"} · autorização válida até ${date(current.grant.expires_at)}`,
      "card",
    ),
  );
  if (current.grant.can_import) {
    const form = node("form", undefined, "card stack"),
      f = field(
        "Ficheiro de atualização de stock ou recuperação",
        "file",
        "stock-file",
        { accept: ".json" },
      ),
      submit = node("button", "Importar Stock");
    submit.type = "submit";
    append(
      form,
      node("h2", "Importar Stock"),
      node(
        "p",
        "A assinatura, origem, versão e sequência serão verificadas. A importação substitui a fotografia e não soma stock. Pode apagar manualmente o ficheiro recebido depois do sucesso.",
        "muted",
      ),
      f.wrap,
      submit,
    );
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      action(async () => {
        const result = await importSnapshot(await fileJSON(f.input));
        message(
          (result.recovery
            ? "Receções recuperadas."
            : `${result.references} referências importadas.`) +
            ` ${result.receipts} linhas de Entrada verificadas.` +
            (result.gaps
              ? " Existem encomendas com lacunas históricas; consulte Encomendas."
              : ""),
        );
      });
    });
    content.append(form);
  } else
    content.append(
      node(
        "p",
        "A informática não autorizou importações neste dispositivo.",
        "card",
      ),
    );
  if (isOwner() && current.unlocked) {
    const backup = node("form", undefined, "card stack"),
      p = field("Frase-passe do backup", "password", "backup-password", {
        minLength: 16,
        required: true,
        autocomplete: "off",
      }),
      repeat = field(
        "Repetir frase-passe do backup",
        "password",
        "backup-repeat",
        { minLength: 16, required: true, autocomplete: "off" },
      ),
      go = node("button", "Exportar cópia cifrada");
    go.type = "submit";
    append(
      backup,
      node("h2", "Proteger encomendas"),
      node(
        "p",
        "Android ou Chrome podem remover dados locais. Guarde uma cópia cifrada em suporte autorizado e a frase-passe separadamente. Não contém credenciais nem chaves privadas de assinatura.",
        "muted",
      ),
      p.wrap,
      repeat.wrap,
      go,
    );
    backup.addEventListener("submit", (e) => {
      e.preventDefault();
      action(async () => {
        if (p.input.value !== repeat.input.value)
          throw new Error("As frases-passe não coincidem.");
        download(
          await backupPreferences(p.input.value),
          "stock-encomendas.vaprefs.json",
        );
      }, "Cópia cifrada preparada. Guarde-a num suporte autorizado.");
    });
    const restore = node("form", undefined, "card stack"),
      f = field("Cópia cifrada das encomendas", "file", "restore-file", {
        accept: ".json",
      }),
      pass = field("Frase-passe da cópia", "password", "restore-password", {
        minLength: 16,
        required: true,
        autocomplete: "off",
      }),
      ok = node("button", "Restaurar encomendas");
    ok.type = "submit";
    append(restore, node("h2", "Recuperar encomendas"), f.wrap, pass.wrap, ok);
    restore.addEventListener("submit", (e) => {
      e.preventDefault();
      action(async () => {
        const data = await decodePreferences(
          await fileJSON(f.input, MAX_FILE * 2),
          pass.input.value,
        );
        if (
          !(await confirm(
            "Substituir encomendas locais",
            `Foram verificadas ${data.orders.length} encomendas e ${data.receipts.length} Entradas. Substituir o acompanhamento local? O stock mantém-se.`,
          ))
        )
          return false;
        await restorePreferences(data);
      }, "Encomendas recuperadas.");
    });
    append(content, backup, restore);
  }
  const activation = node("details", undefined, "card");
  append(
    activation,
    node("summary", "Origem, renovação e autorização do dispositivo"),
    setup(),
  );
  content.append(activation);
  append(
    content,
    node(
      "p",
      "Use dispositivos/perfis de navegador separados para Proprietário e Empregados. Revogações offline só são conhecidas após renovação/atualização autorizada; proteja os dispositivos com as políticas da empresa.",
      "muted",
    ),
  );
}
function render() {
  content.replaceChildren();
  connection();
  document.querySelector("#nav-orders").hidden = !isOwner();
  for (const name of ["stock", "orders", "settings"])
    document
      .querySelector("#nav-" + name)
      .setAttribute("aria-current", section === name ? "page" : "false");
  if (!current.authorized) {
    content.append(setup());
    return;
  }
  if (section === "orders") ordersView();
  else if (section === "settings") settingsView();
  else stockView();
}
async function refresh() {
  current = await state();
  render();
}
for (const name of ["stock", "orders", "settings"])
  document.querySelector("#nav-" + name).addEventListener("click", () => {
    if (name === "orders" && !isOwner()) return;
    section = name;
    refresh().catch((e) => message(e.message, true));
  });
window.addEventListener("online", connection);
window.addEventListener("offline", connection);
for (const event of ["pointerdown", "keydown"])
  document.addEventListener(event, () => touch());
async function checkSession() {
  const updated = await state();
  if (
    !current ||
    current.authorized !== updated.authorized ||
    current.unlocked !== updated.unlocked
  ) {
    current = updated;
    render();
  }
}
document.addEventListener("visibilitychange", () => {
  content.hidden = document.hidden;
  if (!document.hidden) checkSession().catch((e) => message(e.message, true));
});
setInterval(() => {
  if (!document.hidden && !busy)
    checkSession().catch((e) => message(e.message, true));
}, 30000);
let installation;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installation = e;
  document.querySelector("#install").hidden = false;
});
document.querySelector("#install").addEventListener("click", async () => {
  if (installation) {
    await installation.prompt();
    installation = null;
    document.querySelector("#install").hidden = true;
  }
});
if ("serviceWorker" in navigator)
  navigator.serviceWorker
    .register("/service-worker.js")
    .catch(() =>
      message(
        "Não foi possível preparar a consulta offline. Verifique HTTPS e volte a abrir antes de sair do Wi-Fi.",
        true,
      ),
    );
refresh().catch((e) => message(e.message, true));
