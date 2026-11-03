// Drafts are not stock movements. JOSE implements the PR #29 wire protocol.
import { CompactEncrypt, importJWK, calculateJwkThumbprint } from "./jose.js";
import { insist, exact, integer, HEX, UUID, ID, calendarDate, timestamp,
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
  exact(v, ["version", "source_id", "device_id", "sheets", ...("deliveries" in v ? ["deliveries"] : [])]);
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
      exact(l, ["reference_id", "name", "boxes", "units", "box_capacity", ...("proposal" in l ? ["proposal"] : [])]);
      if ("proposal" in l) {
        exact(l.proposal, ["name"]);
        insist(s.kind === "entry" && l.reference_id.startsWith("proposal:") && UUID.test(l.reference_id.slice(9)));
        safeText(l.proposal.name, 250, false); insist(l.name === l.proposal.name);
      } else insist(ID.test(l.reference_id));
      insist(!refs.has(l.reference_id)); refs.add(l.reference_id);
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
      insist(s.file.format === "vertente-pending-sheet" && s.file.version === (s.lines.some(l => l.proposal) ? 2 : 1) &&
        typeof s.file.jwe === "string" && encoder.encode(JSON.stringify(s.file)).length <= MAX_WIRE);
    } else insist(s.state !== "exported");
  }
  if (v.deliveries !== undefined) {
    insist(Array.isArray(v.deliveries) && v.deliveries.length <= 1000);
    const ids = new Set();
    for (const d of v.deliveries) {
      exact(d, ["sheet_id", "file_sha256", "attempt_id", "attempted_at", "last_error", "ack", "ack_request_id"]);
      insist(UUID.test(d.sheet_id) && !ids.has(d.sheet_id) && HEX.test(d.file_sha256) &&
        UUID.test(d.attempt_id) && timestamp(d.attempted_at) &&
        v.sheets.some(s => s.id === d.sheet_id && s.state === "exported"));
      ids.add(d.sheet_id); safeText(d.last_error, 200);
      insist(d.ack === null ? d.ack_request_id === null : UUID.test(d.ack_request_id));
    }
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
    let transport = null;
    try { transport = await transportPolicy(saved); } catch (_) { /* Wi-Fi remains opt-in. */ }
    const deliveries = {};
    if (v) for (const d of v.deliveries || []) {
      const s = v.sheets.find(s => s.id === d.sheet_id);
      try {
        const proof = d.ack ? await receiptProof(d.ack, saved, g, s, d.ack_request_id, {stored: true}) : null;
        deliveries[s.id] = {state: proof ? ({pending: "received", duplicate: "duplicate", conflict: "conflict"})[proof.outcome] : "failure",
          receipt_id: proof?.receipt_id, received_at: proof?.received_at, message: d.last_error};
      } catch (_) { deliveries[s.id] = {state: "failure", message: "Comprovativo inválido; não existe prova de receção verificada."}; }
    }
    return { allowed: true, unlocked: !!v, exists: !!saved.sheetVault, sheets: v?.sheets || [], deliveries,
      transportEnabled: !!transport && saved.meta.sheet_transport_enabled === true,
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
      exact(l, ["reference_id", "boxes", "units", ...("proposal" in l ? ["proposal"] : [])]);
      const prior = s.lines.find(p => p.reference_id === l.reference_id);
      if (l.proposal) {
        exact(l.proposal, ["name", "box_capacity"]);
        insist(s.kind === "entry" && l.reference_id.startsWith("proposal:") && UUID.test(l.reference_id.slice(9)), "Só entradas permitem propor referências.");
        safeText(l.proposal.name, 250, false);
        return {reference_id: l.reference_id, name: l.proposal.name, box_capacity: l.proposal.box_capacity,
          boxes: l.boxes, units: l.units, proposal: {name: l.proposal.name}};
      }
      insist(!prior?.proposal, "Uma proposta não pode transformar-se silenciosamente numa referência oficial.");
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
  const lines = s.lines.map(({reference_id, boxes, units, box_capacity, proposal}) => {
    quantity(boxes, units, box_capacity); return {reference_id, boxes, units, box_capacity, ...(proposal ? {proposal} : {})};
  });
  const version = lines.some(l => l.proposal) ? 2 : 1;
  const r = await recipient(saved);
  const payload = { source_id: g.source_id, device_id: g.device_id, authorization_revision: g.revision,
    sheet_id: s.id, revision: s.revision, kind: s.kind, physical_date: s.physical_date,
    person: s.person, notes: s.notes, lines };
  const data = encoder.encode(JSON.stringify(payload));
  const prefix = encoder.encode(`vertente-sheet-v${version}\0`), message = new Uint8Array(prefix.length + data.length);
  message.set(prefix); message.set(data, prefix.length);
  const signature = await crypto.subtle.sign({name: "ECDSA", hash: "SHA-256"}, saved.meta.device.privateKey, message);
  const envelope = {format: "vertente-sheet", version, algorithm: "ES256", key_id: g.device_key_id,
    payload: encode(data), signature: encode(new Uint8Array(signature))};
  const key = await importJWK(r.jwk, "RSA-OAEP-256");
  const jwe = await new CompactEncrypt(encoder.encode(JSON.stringify(envelope)))
    .setProtectedHeader({alg: "RSA-OAEP-256", enc: "A256GCM", kid: r.key_id}).encrypt(key);
  s.file = {format: "vertente-pending-sheet", version, jwe};
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
  for (const delivery of v.deliveries || []) {
    const s = prior.sheets.find(s => s.id === delivery.sheet_id);
    if (delivery.ack) await receiptProof(delivery.ack, saved, g, s, delivery.ack_request_id, {stored: true});
    prior.deliveries ||= [];
    if (!prior.deliveries.some(d => d.sheet_id === delivery.sheet_id)) prior.deliveries.push(delivery);
  }
  await save(saved, g, prior);
}

async function transportPolicy(saved) {
  insist(saved.meta.sheet_transport, "Importe a política Wi-Fi assinada pela informática.");
  const policy = await verifyEnvelope(saved.meta.sheet_transport, saved.meta.trust, "vertente-sheet-transport", 1);
  exact(policy, ["source_id", "receiver_origin", "stock_origin"]);
  const url = new URL(policy.receiver_origin);
  insist(url.protocol === "https:" && url.origin === policy.receiver_origin && url.pathname === "/" &&
    !url.username && !url.password && policy.stock_origin === location.origin && url.origin !== location.origin,
    "Política de outra origem ou transporte não autorizado.");
  return policy;
}
export async function configureTransport(envelope, enabled) {
  const saved = await raw(), g = await authorization(saved);
  await permission(saved, g);
  const candidate = {...saved, meta: {...saved.meta, sheet_transport: envelope}};
  await transportPolicy(candidate);
  insist(typeof enabled === "boolean");
  await commit(saved, tx => {
    tx.objectStore("meta").put({id: "sheet_transport", value: envelope});
    tx.objectStore("meta").put({id: "sheet_transport_enabled", value: enabled});
  });
}
export async function disableTransport() {
  const saved = await raw(); await authorization(saved);
  await commit(saved, tx => tx.objectStore("meta").put({id: "sheet_transport_enabled", value: false}));
}
async function wireHash(file) {
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(JSON.stringify(file))))]
    .map(b => b.toString(16).padStart(2, "0")).join("");
}
async function receiptProof(envelope, saved, grant, sheet, requestId, opts = {}) {
  const data = await verifyEnvelope(envelope, saved.meta.trust, "vertente-sheet-receipt", 1, opts);
  exact(data, ["source_id", "device_id", "sheet_id", "revision", "file_sha256", "receipt_id", "outcome", "received_at", "request_id"]);
  insist(data.device_id === grant.device_id && data.sheet_id === sheet.id && data.revision === sheet.revision &&
    data.request_id === requestId && UUID.test(data.receipt_id) && timestamp(data.received_at) &&
    ["pending", "duplicate", "conflict"].includes(data.outcome) && data.file_sha256 === await wireHash(sheet.file),
    "Comprovativo não corresponde à folha, dispositivo ou tentativa.");
  return data;
}
export async function sendSheet(id, revision) {
  let saved = await raw(), g = await authorization(saved), v = await open(saved, g);
  const policy = await transportPolicy(saved);
  insist(saved.meta.sheet_transport_enabled === true, "Ative explicitamente o envio Wi-Fi neste dispositivo.");
  const sheet = v.sheets.find(s => s.id === id);
  insist(sheet?.state === "exported" && sheet.revision === revision, "Prepare e confira a folha antes de enviar.");
  const requestId = crypto.randomUUID(), hash = await wireHash(sheet.file);
  v.deliveries ||= [];
  let delivery = v.deliveries.find(d => d.sheet_id === id);
  if (!delivery) {delivery = {sheet_id: id, ack: null, ack_request_id: null}; v.deliveries.push(delivery);}
  Object.assign(delivery, {file_sha256: hash, attempt_id: requestId, attempted_at: new Date().toISOString(), last_error: "Tentativa sem comprovativo novo; em caso de interrupção, tente novamente."});
  await save(saved, g, v); // No request if persistence fails.
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
  try {
    insist(navigator.onLine, "Sem ligação.");
    const response = await fetch(policy.receiver_origin + "/v1/pending-sheets", {
      method: "POST", mode: "cors", credentials: "include", redirect: "error", cache: "no-store", referrerPolicy: "no-referrer",
      headers: {"Content-Type": "application/json", "X-GVA-Request": requestId},
      body: JSON.stringify(sheet.file), signal: controller.signal,
    });
    insist(response.ok && response.headers.get("content-type")?.startsWith("application/json"));
    const reader = response.body.getReader(); let size = 0, chunks = [];
    while (true) {const {done, value} = await reader.read(); if (done) break; size += value.length;
      if (size > 32768) {await reader.cancel(); throw new Error("Comprovativo demasiado grande.");} chunks.push(value);}
    const body = new Uint8Array(size); let offset = 0; for (const chunk of chunks) {body.set(chunk, offset); offset += chunk.length;}
    const ack = JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(body));
    await receiptProof(ack, saved, g, sheet, requestId);
    saved = await raw(); g = await authorization(saved); v = await open(saved, g);
    delivery = v.deliveries.find(d => d.sheet_id === id);
    insist(delivery?.attempt_id === requestId, "Existe outra tentativa; reabra a folha para consultar o resultado.");
    delivery.ack = ack; delivery.ack_request_id = requestId; delivery.last_error = "";
    await save(saved, g, v);
  } catch (_) {
    try {
      saved = await raw(); g = await authorization(saved); v = await open(saved, g);
      delivery = v.deliveries.find(d => d.sheet_id === id);
      if (delivery?.attempt_id === requestId) {
        delivery.last_error = "Falha nesta tentativa. Conserve a folha e tente novamente; um comprovativo anterior válido mantém-se.";
        await save(saved, g, v);
      }
    } catch (_) { /* Last committed vault remains intact, including unknown-delivery state. */ }
    throw new Error("Envio não comprovado nesta tentativa. A folha foi preservada; tente novamente com a mesma identidade.");
  } finally {clearTimeout(timer);}
}
