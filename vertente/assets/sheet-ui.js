import { normalize } from "./domain.js";
import { configureSheets, unlockSheets, lockSheets, createSheet, editSheet,
  exportSheet, backupSheets, restoreSheets } from "./sheets.js";

let editing = null;
export function sheetsView(ui) {
  const {content, current, node, append, field, button, action, refresh, confirm,
    fileJSON, download, inputQuantities, optionalNumber, quantity} = ui;
  const state = current.sheetState;
  const name = current.grant.role === "owner" ? "Fábio" : "Daniel";
  append(content, node("h2", "Folhas de entrada e saída"),
    node("p", `Utilizador: ${name}. Preparar ou exportar não altera o stock oficial.`, "card"),
    node("p", "Exportar apenas disponibiliza um ficheiro: não significa que o escritório o recebeu ou confirmou.", "warning"));
  const setup = node("details", undefined, "card stack");
  append(setup, node("summary", "Autorizações e chave de receção"));
  for (const [kind, label] of [["permission", "Permissão individual de folhas"], ["recipient", "Chave pública de receção assinada"]]) {
    const form = node("form"), f = field(label, "file", "sheet-" + kind, {accept: ".json"});
    const go = node("button", "Importar " + label.toLocaleLowerCase("pt-PT")); go.type = "submit";
    append(form, f.wrap, go);
    form.addEventListener("submit", e => {e.preventDefault(); action(async () => {
      await configureSheets(kind, await fileJSON(f.input, 1024 * 1024)); editing = null;
    }, "Configuração assinada verificada. Desbloqueie os rascunhos.");});
    setup.append(form);
  }
  content.append(setup);
  if (!state.allowed) {content.append(node("p", state.error, "card")); return;}
  if (!state.unlocked) {
    const form = node("form", undefined, "card stack");
    const pass = field("Frase-passe dos rascunhos", "password", "sheet-pass", {required: true, minLength: 16, autocomplete: "off"});
    const repeat = !state.exists ? field("Repetir frase-passe dos rascunhos", "password", "sheet-repeat", {required: true, minLength: 16, autocomplete: "off"}) : null;
    const go = node("button", state.exists ? "Desbloquear rascunhos" : "Proteger rascunhos"); go.type = "submit";
    append(form, node("h3", "Rascunhos privados de " + name), node("p", "Use uma frase-passe individual. Não fica guardada nem pode ser recuperada. O cofre de encomendas de Fábio permanece separado."), pass.wrap, repeat?.wrap, go);
    form.addEventListener("submit", e => {e.preventDefault(); action(async () => {
      if (repeat && repeat.input.value !== pass.input.value) throw new Error("As frases-passe não coincidem.");
      await unlockSheets(pass.input.value); pass.input.value = ""; if (repeat) repeat.input.value = "";
    }, "Rascunhos desbloqueados.");});
    content.append(form); return;
  }
  append(content, button("Bloquear rascunhos", () => {lockSheets(); editing = null; refresh();}, true));
  const selected = state.sheets.find(s => s.id === editing);
  if (selected) {
    const s = selected, form = node("form", undefined, "card stack");
    const writable = s.state === "draft";
    append(form, node("h3", (s.kind === "entry" ? "Entrada" : "Saída") + " · revisão " + s.revision),
      node("p", s.id, "code"));
    const person = field(s.kind === "entry" ? "Quem entregou" : "Quem levantou", "text", "sheet-person", {value: s.person, maxLength: 200, disabled: !writable});
    const physical = field("Data física comunicada", "date", "sheet-date", {value: s.physical_date, disabled: !writable});
    const notes = field("Observações", "text", "sheet-notes", {value: s.notes, maxLength: 4000, disabled: !writable});
    append(form, person.wrap, physical.wrap, notes.wrap);
    let dirty = false, sequence = 0;
    const lines = [], list = node("div", undefined, "stack");
    const mark = () => {dirty = true;}; form.addEventListener("input", mark);
    function addLine(l) {
      const card = node("section", undefined, "card stack");
      const q = inputQuantities({box_capacity: l.box_capacity}, l, "sheet-line-" + (++sequence) + "-");
      q.boxes.input.disabled = !writable || !l.box_capacity; q.units.input.disabled = !writable;
      append(card, node("h3", `${l.reference_id} · ${l.name}`),
        node("p", l.box_capacity ? `${l.box_capacity} garrafas por caixa (capacidade preservada).` : "Capacidade desconhecida: introduza apenas garrafas."),
        q.boxes.wrap, q.units.wrap, q.preview);
      const entry = {l, q, card}; lines.push(entry);
      if (writable) card.append(button("Remover " + l.name, () => {lines.splice(lines.indexOf(entry), 1); card.remove(); mark();}, true));
      list.append(card);
    }
    s.lines.forEach(addLine); form.append(list);
    if (writable) {
      const search = field("Pesquisar referência para a folha", "search", "sheet-search");
      const results = node("div", undefined, "stack");
      const find = () => {
        const query = normalize(search.input.value.trim()); results.replaceChildren();
        if (!query) return;
        const refs = (current.copy?.data.references || []).filter(r =>
          normalize(r.name + " " + r.id).includes(query) && !lines.some(l => l.l.reference_id === r.id));
        refs.slice(0, 30).forEach(r => results.append(button(`${r.id} · ${r.name}`, () => {
          addLine({reference_id: r.id, name: r.name, box_capacity: r.box_capacity, boxes: null, units: null});
          mark(); search.input.value = ""; results.replaceChildren();
        }, true)));
        if (!refs.length) results.append(node("p", "Nenhuma referência ativa na cópia importada."));
        else if (refs.length > 30) results.append(node("p", "Refine a pesquisa para encontrar outras referências."));
      };
      search.input.addEventListener("input", find); append(form, search.wrap, results,
        node("p", "Guarde antes de sair. Campos vazios permanecem por preencher; não são zeros confirmados.", "muted"));
      const save = node("button", "Guardar rascunho"); save.type = "submit"; form.append(save);
      form.addEventListener("submit", e => {e.preventDefault(); action(async () => {
        await editSheet(s.id, s.revision, {person: person.input.value, physical_date: physical.input.value,
          notes: notes.input.value, lines: lines.map(({l, q}) => ({reference_id: l.reference_id,
            boxes: optionalNumber(q.boxes.input), units: optionalNumber(q.units.input)}))});
      }, "Rascunho guardado neste dispositivo. Stock inalterado.");});
      form.append(button("Cancelar folha", () => action(async () => {
        if (!(await confirm("Cancelar rascunho", "Cancelar apenas este rascunho local? Não altera stock nem cancela ficheiros já entregues."))) return false;
        await editSheet(s.id, s.revision, {}, true); editing = null;
      }, "Rascunho cancelado."), true));
    }
    if (s.state !== "cancelled") form.append(button(writable ? "Rever e exportar folha" : "Descarregar novamente o mesmo ficheiro", () => action(async () => {
      if (dirty) throw new Error("Guarde as alterações antes de rever e exportar.");
      if (writable) {
        const total = s.lines.map(l => `${l.reference_id} · ${l.name}: ${quantity(l.boxes, l.units, l.box_capacity)} garrafas`).join("\n");
        if (!(await confirm("Exportar folha pendente", `${s.person}\n${s.physical_date}\n${total}\n${s.notes}\nA folha fica imutável. Não é uma confirmação nem um recibo do escritório.`))) return false;
      }
      download(await exportSheet(s.id, s.revision), `folha-${s.id}-r${s.revision}.vasheet`);
    }, "Ficheiro disponibilizado. Receção e confirmação pelo escritório ainda não estão comprovadas.")));
    if (!writable) form.append(node("p", "Esta folha não pode ser reescrita. A reexportação mantém o mesmo UUID, revisão e ficheiro; nenhuma alteração é enviada silenciosamente.", "warning"));
    form.append(button("Voltar às folhas", () => {editing = null; refresh();}, true));
    content.append(form); return;
  }
  const actions = node("div", undefined, "actions");
  for (const [kind, label] of [["entry", "Preparar entrada"], ["exit", "Preparar saída"]])
    actions.append(button(label, () => action(async () => {editing = await createSheet(kind);})));
  content.append(actions);
  const labels = {draft: "Rascunho", cancelled: "Cancelada localmente", exported: "Exportada · sem comprovativo de receção"};
  for (const s of [...state.sheets].reverse()) {
    const card = node("section", undefined, "card");
    append(card, node("h3", `${s.kind === "entry" ? "Entrada" : "Saída"} · ${labels[s.state]}`),
      node("p", `${s.person || "Pessoa por indicar"} · ${s.physical_date || "Data por indicar"} · ${s.lines.length} referências`),
      button("Abrir folha " + s.id, () => {editing = s.id; refresh();}, true)); content.append(card);
  }
  const backup = node("details", undefined, "card stack");
  append(backup, node("summary", "Cópias cifradas dos rascunhos"),
    node("p", "Não incluem a chave privada do dispositivo. Recuperação apenas neste dispositivo/perfil e origem; não substitui folhas já existentes. Guarde a frase-passe separadamente."));
  const pass = field("Frase-passe da cópia de folhas", "password", "sheet-backup-password", {minLength: 16, autocomplete: "off"});
  const file = field("Cópia cifrada de folhas", "file", "sheet-backup-file", {accept: ".json"});
  append(backup, pass.wrap, button("Exportar cópia de folhas", () => action(async () => {
    download(await backupSheets(pass.input.value), "folhas.vadrafts.json"); pass.input.value = "";
  }, "Cópia cifrada preparada.")), file.wrap, button("Recuperar cópia de folhas", () => action(async () => {
    if (!(await confirm("Recuperar folhas locais", "Juntar as folhas da cópia, recusando conflitos com folhas já existentes? Não altera stock."))) return false;
    await restoreSheets(await fileJSON(file.input, 16 * 1024 * 1024), pass.input.value); pass.input.value = "";
  }, "Folhas recuperadas sem alterar stock.")));
  content.append(backup);
}
