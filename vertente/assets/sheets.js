// Drafts are not stock movements. JOSE implements the PR #29 wire protocol.
import { CompactEncrypt, importJWK, calculateJwkThumbprint } from "./jose.js";
import { insist, exact, integer, text, UUID, ID, calendarDate, timestamp,
  bytes, encode, verifyEnvelope, today } from "./domain.js";
import { raw, commit, authorization, copyOf, derive, seal, unseal, quantity } from "./store.js";

let session = null;
const encoder = new TextEncoder();
const MAX_WIRE = 1024 * 1024;
const options = (source, device) => ({
  format: "vertente-sheets-encrypted",
  context: `stock-sheets-v1\0${source}\0${device}`,
  validate: v => validate(v, source, device),
});
export function lockSheets() { session = null; }
window.addEventListener("vertente-lock", lockSheets);
export function touchSheets() {
  if (session && Date.now() - session.last < 300000) session.last = Date.now();
}
function safeText(value, max, empty = true) {
  insist(typeof value === "string" && value.length <= max && !value.includes("\0"));
  // TextEncoder replaces unpaired surrogates; refuse rather than change evidence.
  insist(new TextDecoder().decode(encoder.encode(value)) === value);
  insist(empty || value.trim().length > 0);
}
function validate(v, source, device) {
  exact(v, ["version", "source_id", "device_id", "sheets"]);
  insist(v.version === 1 && v.source_id === source && v.device_id === device);
  insist(Array.isArray(v.sheets) && v.sheets.length <= 1000);
  const ids = new Set();
  for (const s of v.sheets) {
    exact(s, ["id", "revision", "kind", "person", "physical_date", "notes", "lines",
      "created_at", "updated_at", "state", "file"]);
    insist(UUID.test(s.id) && !ids.has(s.id) && integer(s.revision, 1)); ids.add(s.id);
    insist(["entry", "exit"].includes(s.kind) && ["draft", "exported", "cancelled"].includes(s.state));
    safeText(s.person, 200); safeText(s.notes, 4000);
    insist(s.physical_date === "" || calendarDate(s.physical_date));
    insist(timestamp(s.created_at) && timestamp(s.updated_at));
    insist(Array.isArray(s.lines) && s.lines.length <= 500);
    const refs = new Set();
    for (const l of s.lines) {
      exact(l, ["reference_id", "name", "boxes", "units", "box_capacity"]);
      insist(ID.test(l.reference_id) && !refs.has(l.reference_id)); refs.add(l.reference_id);
      safeText(l.name, 250, false);
      insist(l.box_capacity === null || integer(l.box_capacity, 1));
      insist([l.boxes, l.units].every(n => n === null || integer(n)));
      insist(!l.boxes || l.box_capacity !== null, "Capacidade desconhecida: introduza garrafas.");
      const total = (l.boxes || 0) * (l.box_capacity || 0) + (l.units || 0);
      insist(integer(total), "Quantidade fora do limite permitido.");
    }
    if (s.file !== null) {
      insist(s.state === "exported");
      exact(s.file, ["format", "version", "jwe"]);
      insist(s.file.format === "vertente-pending-sheet" && s.file.version === 1 &&
        typeof s.file.jwe === "string" && encoder.encode(JSON.stringify(s.file)).length <= MAX_WIRE);
    } else insist(s.state !== "exported");
  }
  return v;
}
async function permission(saved, grant) {
  insist(saved.meta.sheet_permission, "Importe a permissão individual de preparação de folhas.");
  const p = await verifyEnvelope(saved.meta.sheet_permission, saved.meta.trust, "vertente-sheet-authorization", 1);
  exact(p, ["source_id", "device_id", "device_key_id", "authorization_revision", "expires_at", "sheets_allowed"]);
  insist(p.device_id === grant.device_id && p.device_key_id === grant.device_key_id &&
    p.authorization_revision === grant.revision && p.sheets_allowed === true &&
    timestamp(p.expires_at) && Date.parse(p.expires_at) > Date.now() &&
    Date.parse(p.expires_at) <= Date.parse(grant.expires_at),
    "Permissão de folhas inválida, expirada ou de outro dispositivo/revisão.");
  return p;
}
async function recipient(saved) {
  insist(saved.meta.sheet_recipient, "Importe a chave pública de receção autenticada pelo escritório.");
  const r = await verifyEnvelope(saved.meta.sheet_recipient, saved.meta.trust, "vertente-sheet-recipient", 1);
  exact(r, ["source_id", "jwk", "key_id"]);
  exact(r.jwk, ["kty", "n", "e"]);
  insist(r.jwk.kty === "RSA" && r.jwk.e === "AQAB" && bytes(r.jwk.n).length >= 384);
  insist(await calculateJwkThumbprint(r.jwk) === r.key_id, "Chave de receção inconsistente.");
  return r;
}
export async function configureSheets(kind, envelope) {
  insist(["permission", "recipient"].includes(kind));
  const saved = await raw(), g = await authorization(saved);
  const candidate = { ...saved, meta: { ...saved.meta, ["sheet_" + kind]: envelope } };
  if (kind === "permission") await permission(candidate, g);
  else await recipient(candidate);
  await commit(saved, tx => tx.objectStore("meta").put({ id: "sheet_" + kind, value: envelope }));
  lockSheets();
}
function empty(g) { return {version: 1, source_id: g.source_id, device_id: g.device_id, sheets: []}; }
async function open(saved, g) {
  await permission(saved, g);
  if (!session || Date.now() - session.last >= 300000) {
    lockSheets(); throw new Error("Desbloqueie os rascunhos deste dispositivo.");
  }
  insist(!saved.sheetVault || saved.sheetVault.salt === encode(session.salt), "Os rascunhos mudaram noutra janela. Desbloqueie novamente.");
  return saved.sheetVault ? unseal(saved.sheetVault, session.key, g.source_id, options(g.source_id, g.device_id)) : empty(g);
}
async function save(saved, g, v) {
  validate(v, g.source_id, g.device_id);
  const file = await seal(v, session.key, session.salt, g.source_id, options(g.source_id, g.device_id));
  await commit(saved, tx => tx.objectStore("vault").put({ id: "sheets", value: file }));
  session.last = Date.now();
}
export async function unlockSheets(password) {
  const saved = await raw(), g = await authorization(saved);
  await permission(saved, g);
  const salt = saved.sheetVault ? bytes(saved.sheetVault.salt, 16) : crypto.getRandomValues(new Uint8Array(16));
  const key = await derive(password, salt, ["encrypt", "decrypt"]);
  if (saved.sheetVault) await unseal(saved.sheetVault, key, g.source_id, options(g.source_id, g.device_id));
  else {
    const file = await seal(empty(g), key, salt, g.source_id, options(g.source_id, g.device_id));
    await commit(saved, tx => tx.objectStore("vault").put({ id: "sheets", value: file }));
  }
  session = { key, salt, last: Date.now() };
}
export async function sheetState() {
  try {
    const saved = await raw(), g = await authorization(saved);
    await permission(saved, g);
    let v;
    try { v = await open(saved, g); } catch (_) { /* Locked vault exposes no personal fields. */ }
    return { allowed: true, unlocked: !!v, exists: !!saved.sheetVault, sheets: v?.sheets || [],
      recipient: !!saved.meta.sheet_recipient };
  } catch (e) { return { allowed: false, unlocked: false, sheets: [], error: e.message }; }
}
export async function createSheet(kind) {
  insist(["entry", "exit"].includes(kind));
  const saved = await raw(), g = await authorization(saved), v = await open(saved, g);
  const id = crypto.randomUUID(), now = new Date().toISOString();
  v.sheets.push({id, revision: 1, kind, person: "", physical_date: today(), notes: "", lines: [],
    created_at: now, updated_at: now, state: "draft", file: null});
  await save(saved, g, v); return id;
}
export async function editSheet(id, revision, values, cancel = false) {
  const saved = await raw(), g = await authorization(saved), v = await open(saved, g);
  const s = v.sheets.find(s => s.id === id);
  insist(s?.state === "draft" && s.revision === revision, "Folha exportada, cancelada ou alterada. Reabra a versão atual.");
  if (cancel) s.state = "cancelled";
  else {
    exact(values, ["person", "physical_date", "notes", "lines"]);
    const { copy } = await copyOf(saved);
    s.person = values.person; s.physical_date = values.physical_date; s.notes = values.notes;
    insist(Array.isArray(values.lines) && values.lines.length <= 500);
    s.lines = values.lines.map(l => {
      exact(l, ["reference_id", "boxes", "units"]);
      const prior = s.lines.find(p => p.reference_id === l.reference_id);
      const ref = copy?.data.references.find(r => r.id === l.reference_id);
      insist(prior || ref, "Escolha uma referência da cópia importada.");
      return { ...l, name: prior?.name || ref.name, box_capacity: prior ? prior.box_capacity : ref.box_capacity };
    });
  }
  s.revision++; s.updated_at = new Date().toISOString();
  await save(saved, g, v);
}
export async function exportSheet(id, revision) {
  const saved = await raw(), g = await authorization(saved), v = await open(saved, g);
  const s = v.sheets.find(s => s.id === id);
  insist(s && s.revision === revision && s.state !== "cancelled", "Reabra a versão atual da folha.");
  if (s.state === "exported") return s.file; // Exact bytes, identity and revision, never resign a sent sheet.
  safeText(s.person, 200, false);
  insist(calendarDate(s.physical_date) && s.lines.length > 0, "Complete pessoa, data e referências antes de exportar.");
  const lines = s.lines.map(({reference_id, boxes, units, box_capacity}) => {
    quantity(boxes, units, box_capacity); return {reference_id, boxes, units, box_capacity};
  });
  const r = await recipient(saved);
  const payload = { source_id: g.source_id, device_id: g.device_id, authorization_revision: g.revision,
    sheet_id: s.id, revision: s.revision, kind: s.kind, physical_date: s.physical_date,
    person: s.person, notes: s.notes, lines };
  const data = encoder.encode(JSON.stringify(payload));
  const prefix = encoder.encode("vertente-sheet-v1\0"), message = new Uint8Array(prefix.length + data.length);
  message.set(prefix); message.set(data, prefix.length);
  const signature = await crypto.subtle.sign({name: "ECDSA", hash: "SHA-256"}, saved.meta.device.privateKey, message);
  const envelope = {format: "vertente-sheet", version: 1, algorithm: "ES256", key_id: g.device_key_id,
    payload: encode(data), signature: encode(new Uint8Array(signature))};
  const key = await importJWK(r.jwk, "RSA-OAEP-256");
  const jwe = await new CompactEncrypt(encoder.encode(JSON.stringify(envelope)))
    .setProtectedHeader({alg: "RSA-OAEP-256", enc: "A256GCM", kid: r.key_id}).encrypt(key);
  s.file = {format: "vertente-pending-sheet", version: 1, jwe};
  insist(encoder.encode(JSON.stringify(s.file)).length <= MAX_WIRE, "Folha demasiado grande.");
  s.state = "exported"; s.updated_at = new Date().toISOString();
  await save(saved, g, v); // Commit before download: a failed commit must not produce a new export.
  return s.file;
}
export async function backupSheets(password) {
  const saved = await raw(), g = await authorization(saved), v = await open(saved, g);
  const salt = crypto.getRandomValues(new Uint8Array(16)), key = await derive(password, salt, ["encrypt"]);
  return seal(v, key, salt, g.source_id, options(g.source_id, g.device_id));
}
export async function restoreSheets(file, password) {
  const saved = await raw(), g = await authorization(saved), prior = await open(saved, g);
  const key = await derive(password, bytes(file.salt, 16), ["decrypt"]);
  const v = await unseal(file, key, g.source_id, options(g.source_id, g.device_id));
  // Merge, never roll an exported identity back to editable or silently replace a newer draft.
  for (const s of v.sheets) {
    const old = prior.sheets.find(p => p.id === s.id);
    if (old) insist(JSON.stringify(old) === JSON.stringify(s), "Conflito com uma folha local; nenhuma folha foi substituída.");
    else prior.sheets.push(s);
  }
  await save(saved, g, prior);
}
