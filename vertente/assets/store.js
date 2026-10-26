// Reuses the Stage 7 atomic snapshot/trust design. Owner data now lives only in an
// authenticated encrypted vault. No passwords or decrypted owner data persist.
import {
  insist,
  exact,
  integer,
  timestamp,
  text,
  ID,
  UUID,
  MAX_FILE,
  calendarDate,
  today,
  bytes,
  encode,
  keyRecord,
  validateTrust,
  validateStock,
  validateGrant,
  validateRecovery,
  validateReceipts,
  mergeCoverage,
  verifyEnvelope,
  reconcile,
  orderReceived,
  pending,
} from "./domain.js";
const NAME = "stock-vertente-aveludada-b",
  VERSION = 1;
let connection,
  session = null;
const req = (r) =>
  new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
const completion = (tx) =>
  new Promise((resolve, reject) => {
    tx.oncomplete = resolve;
    tx.onabort = () =>
      reject(
        new Error(
          "Não foi possível guardar. A última cópia válida foi preservada.",
        ),
      );
    tx.onerror = () => {};
  });
export async function database() {
  if (connection) return connection;
  connection = await new Promise((resolve, reject) => {
    const r = indexedDB.open(NAME, VERSION);
    r.onupgradeneeded = () => {
      for (const name of ["meta", "snapshots", "vault"])
        r.result.createObjectStore(name, { keyPath: "id" });
    };
    r.onerror = () =>
      reject(
        new Error(
          "Armazenamento indisponível. Não limpe os dados; verifique espaço e permissões.",
        ),
      );
    r.onblocked = () =>
      reject(
        new Error("Feche outras janelas antes de atualizar o armazenamento."),
      );
    r.onsuccess = () => {
      r.result.onversionchange = () => {
        r.result.close();
        connection = null;
        lock();
      };
      resolve(r.result);
    };
  });
  return connection;
}
async function raw() {
  const db = await database(),
    tx = db.transaction(["meta", "snapshots", "vault"], "readonly"),
    done = completion(tx);
  const [meta, snapshots, vault] = await Promise.all(
    ["meta", "snapshots", "vault"].map((n) => req(tx.objectStore(n).getAll())),
  );
  await done;
  const m = Object.fromEntries(meta.map((x) => [x.id, x.value]));
  return { meta: m, snapshots, vault: vault[0]?.value };
}
async function commit(before, write) {
  const db = await database(),
    tx = db.transaction(["meta", "snapshots", "vault"], "readwrite"),
    done = completion(tx);
  let reason;
  const r = tx.objectStore("meta").getAll();
  r.onsuccess = () => {
    const m = Object.fromEntries(r.result.map((x) => [x.id, x.value]));
    if (
      (m.revision || 0) !== (before.meta.revision || 0) ||
      JSON.stringify(m.trust) !== JSON.stringify(before.meta.trust) ||
      JSON.stringify(m.grant) !== JSON.stringify(before.meta.grant)
    ) {
      reason = "Os dados mudaram noutra janela. Reveja antes de repetir.";
      tx.abort();
      return;
    }
    try {
      write(tx);
      tx.objectStore("meta").put({
        id: "revision",
        value: (m.revision || 0) + 1,
      });
    } catch (e) {
      reason = e.message;
      tx.abort();
    }
  };
  try {
    await done;
  } catch (e) {
    throw new Error(reason || e.message);
  }
}
function publicDevice(d) {
  return d ? { id: d.id, key_id: d.key_id, spki: d.spki } : null;
}
export async function deviceRequest() {
  let saved = await raw();
  if (!saved.meta.device) {
    const pair = await crypto.subtle.generateKey(
      { name: "ECDSA", namedCurve: "P-256" },
      false,
      ["sign", "verify"],
    );
    const der = new Uint8Array(
      await crypto.subtle.exportKey("spki", pair.publicKey),
    );
    const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", der))]
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    const device = {
      id: crypto.randomUUID(),
      key_id: hash,
      spki: encode(der),
      privateKey: pair.privateKey,
    };
    await commit(saved, (tx) =>
      tx.objectStore("meta").put({ id: "device", value: device }),
    );
    saved = await raw();
  }
  const d = saved.meta.device;
  const sig = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    d.privateKey,
    new TextEncoder().encode("vertente-device-request-v1\0" + d.id),
  );
  return {
    format: "vertente-device-request",
    version: 1,
    device_id: d.id,
    spki: d.spki,
    signature: encode(new Uint8Array(sig)),
  };
}
async function authorization(saved) {
  insist(
    saved.meta.trust && saved.meta.device && saved.meta.grant,
    "Dispositivo ainda não autorizado. Peça ativação à informática.",
  );
  const d = saved.meta.device;
  const g = await validateGrant(saved.meta.grant, saved.meta.trust, d);
  const key = await keyRecord({ key_id: d.key_id, spki: d.spki });
  const challenge = crypto.getRandomValues(new Uint8Array(32));
  const proof = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    d.privateKey,
    challenge,
  );
  insist(
    await crypto.subtle.verify(
      { name: "ECDSA", hash: "SHA-256" },
      key,
      proof,
      challenge,
    ),
    "A chave privada deste dispositivo não corresponde à autorização.",
  );
  return g;
}
export async function enroll(bundle, fingerprint) {
  await validateTrust(bundle);
  insist(
    bundle.keys[0].key_id === fingerprint.trim().toLowerCase(),
    "Confirme o fingerprint completo por um canal independente.",
  );
  const saved = await raw(),
    old = saved.meta.trust;
  insist(
    !old || old.source_id === bundle.source_id,
    "A origem está fixada a outra instalação.",
  );
  if (
    old &&
    !old.keys.some((k) => !k.revoked && k.key_id === bundle.keys[0].key_id)
  ) {
    insist(
      bundle.rotation,
      "A rotação exige autorização assinada pela chave anterior. Não é permitido substituir a confiança livremente.",
    );
    const proof = await verifyEnvelope(
      bundle.rotation,
      old,
      "vertente-key-rotation",
      1,
    );
    exact(proof, ["source_id", "key"]);
    insist(
      JSON.stringify(proof.key) === JSON.stringify(bundle.keys[0]),
      "A rotação não autoriza esta chave.",
    );
  }
  const retired = (old?.keys || [])
    .filter((k) => k.key_id !== bundle.keys[0].key_id)
    .map((k) => ({ ...k, revoked: true }));
  insist(
    retired.length < 64,
    "Limite de chaves históricas atingido. Contacte a informática.",
  );
  await commit(saved, (tx) =>
    tx.objectStore("meta").put({
      id: "trust",
      value: {
        source_id: bundle.source_id,
        keys: [{ ...bundle.keys[0], revoked: false }, ...retired],
      },
    }),
  );
  lock();
}
export async function activate(envelope) {
  const saved = await raw();
  insist(saved.meta.device, "Crie primeiro o pedido deste dispositivo.");
  const g = await validateGrant(envelope, saved.meta.trust, saved.meta.device);
  insist(
    !saved.meta.role || saved.meta.role === g.role,
    "Não se misturam perfis no mesmo armazenamento. Use um dispositivo/perfil de navegador distinto.",
  );
  insist(
    g.revision > (saved.meta.grant_revision || 0),
    "Autorização repetida ou anterior.",
  );
  await commit(saved, (tx) => {
    for (const [id, value] of Object.entries({
      grant: envelope,
      grant_revision: g.revision,
      role: g.role,
    }))
      tx.objectStore("meta").put({ id, value });
  });
  lock();
}
export function lock() {
  session = null;
}
export function touch() {
  if (session && Date.now() - session.last < 300000) session.last = Date.now();
}
async function derive(password, salt, uses) {
  insist(
    typeof password === "string" && password.length >= 16,
    "Use uma frase-passe de pelo menos 16 caracteres. Não fica guardada e não pode ser recuperada.",
  );
  const raw = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt, iterations: 600000 },
    raw,
    { name: "AES-GCM", length: 256 },
    false,
    uses,
  );
}
async function seal(data, key, salt, source) {
  const plain = new TextEncoder().encode(JSON.stringify(data));
  insist(
    plain.length < MAX_FILE - 1024,
    "Arquivo local demasiado grande. Exporte uma cópia de segurança e contacte a assistência; nenhum dado foi eliminado.",
  );
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = await crypto.subtle.encrypt(
    {
      name: "AES-GCM",
      iv,
      additionalData: new TextEncoder().encode("stock-owner-v1\0" + source),
    },
    key,
    plain,
  );
  return {
    format: "vertente-owner-encrypted",
    version: 1,
    source_id: source,
    kdf: "PBKDF2-SHA256",
    iterations: 600000,
    salt: encode(salt),
    iv: encode(iv),
    ciphertext: encode(new Uint8Array(ciphertext)),
  };
}
async function unseal(file, key, source) {
  exact(file, [
    "format",
    "version",
    "source_id",
    "kdf",
    "iterations",
    "salt",
    "iv",
    "ciphertext",
  ]);
  insist(
    file.format === "vertente-owner-encrypted" &&
      file.version === 1 &&
      file.source_id === source &&
      file.kdf === "PBKDF2-SHA256" &&
      file.iterations === 600000,
    "Backup de outra origem ou formato.",
  );
  const salt = bytes(file.salt, 16),
    iv = bytes(file.iv, 12);
  insist(salt.length === 16 && iv.length === 12);
  try {
    const raw = await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv,
        additionalData: new TextEncoder().encode("stock-owner-v1\0" + source),
      },
      key,
      bytes(file.ciphertext, MAX_FILE + 32),
    );
    return validateVault(
      JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)),
      source,
    );
  } catch (e) {
    throw new Error(
      "Frase-passe incorreta, arquivo alterado ou dados inválidos. A cópia anterior foi preservada.",
    );
  }
}
function emptyVault(source) {
  return {
    version: 1,
    source_id: source,
    orders: [],
    receipts: [],
    allocations: [],
    coverage: [],
    watermark: null,
  };
}
export function validateVault(v, source) {
  exact(v, [
    "version",
    "source_id",
    "orders",
    "receipts",
    "allocations",
    "coverage",
    "watermark",
  ]);
  insist(v.version === 1 && v.source_id === source && UUID.test(source));
  for (const key of ["orders", "receipts", "allocations"])
    insist(Array.isArray(v[key]) && v[key].length <= 100000);
  insist(Array.isArray(v.coverage) && v.coverage.length <= 1000);
  if (v.watermark) {
    exact(v.watermark, ["sequence", "update_id", "exported_at"]);
    insist(
      integer(v.watermark.sequence, 1, Number.MAX_SAFE_INTEGER) &&
        UUID.test(v.watermark.update_id) &&
        timestamp(v.watermark.exported_at),
    );
  }
  const orders = new Map(),
    receipts = new Map();
  for (const o of v.orders) {
    exact(o, [
      "id",
      "reference_id",
      "name",
      "created_at",
      "ordered_on",
      "quantity",
      "boxes",
      "units",
      "box_capacity",
      "note",
      "state",
      "ended_at",
      "gap",
    ]);
    insist(
      UUID.test(o.id) &&
        ID.test(o.reference_id) &&
        text(o.name, 250) &&
        timestamp(o.created_at) &&
        calendarDate(o.ordered_on),
    );
    insist(o.quantity === null || integer(o.quantity, 1));
    insist(o.box_capacity === null || integer(o.box_capacity, 1));
    insist(
      (o.boxes === null || integer(o.boxes)) &&
        (o.units === null || integer(o.units)) &&
        (!o.boxes || o.box_capacity !== null),
    );
    insist(
      o.quantity === null
        ? o.boxes === null && o.units === null
        : (o.boxes || 0) * (o.box_capacity || 0) + (o.units || 0) ===
            o.quantity,
    );
    insist(
      typeof o.note === "string" &&
        o.note.length <= 1000 &&
        typeof o.gap === "boolean" &&
        ["waiting", "partial", "received", "cancelled"].includes(o.state),
    );
    insist(
      pending(o)
        ? o.ended_at === null
        : timestamp(o.ended_at) && o.ended_at >= o.created_at,
    );
    insist(!orders.has(o.id));
    orders.set(o.id, o);
  }
  insist(
    JSON.stringify(mergeCoverage(v.coverage)) === JSON.stringify(v.coverage),
  );
  for (let i = 0; i < v.receipts.length; i += 10000) {
    const chunk = v.receipts.slice(i, i + 10000);
    const times = chunk.map((r) => r.confirmed_at).sort();
    validateReceipts({
      coverage: { from: times[0], until: times.at(-1) },
      receipts: chunk,
    });
    for (const r of chunk) {
      insist(
        !receipts.has(r.id) &&
          v.coverage.some(
            (c) => c.from <= r.confirmed_at && c.until >= r.confirmed_at,
          ),
      );
      receipts.set(r.id, r);
    }
  }
  const allocations = new Set(),
    used = new Map(),
    totals = new Map();
  for (const a of v.allocations) {
    exact(a, ["receipt_id", "order_id", "bottles"]);
    const o = orders.get(a.order_id),
      r = receipts.get(a.receipt_id);
    insist(
      o &&
        r &&
        integer(a.bottles, 1) &&
        r.reference_id === o.reference_id &&
        r.confirmed_at > o.created_at,
    );
    const id = a.receipt_id + ":" + a.order_id;
    insist(!allocations.has(id));
    allocations.add(id);
    used.set(r.id, (used.get(r.id) || 0) + a.bottles);
    totals.set(o.id, (totals.get(o.id) || 0) + a.bottles);
    insist(used.get(r.id) <= r.bottles);
  }
  for (const o of orders.values()) {
    const received = totals.get(o.id) || 0;
    insist(o.quantity === null || received <= o.quantity);
    if (o.state !== "cancelled")
      insist(
        o.state ===
          (received === 0
            ? "waiting"
            : o.quantity === null || received === o.quantity
              ? "received"
              : "partial"),
      );
  }
  return v;
}
async function owner(saved, g) {
  insist(g.role === "owner", "Esta função é exclusiva do Proprietário.");
  if (!session || Date.now() - session.last >= 300000) {
    lock();
    throw new Error("Desbloqueie o cofre do Proprietário.");
  }
  insist(
    !saved.vault || saved.vault.salt === encode(session.salt),
    "O cofre mudou noutra janela. Bloqueie e volte a desbloquear.",
  );
  return saved.vault
    ? unseal(saved.vault, session.key, g.source_id)
    : emptyVault(g.source_id);
}
export async function unlock(password) {
  const saved = await raw(),
    g = await authorization(saved);
  insist(g.role === "owner", "Esta função é exclusiva do Proprietário.");
  const salt = saved.vault
    ? bytes(saved.vault.salt, 16)
    : crypto.getRandomValues(new Uint8Array(16));
  const key = await derive(password, salt, ["encrypt", "decrypt"]);
  if (saved.vault) await unseal(saved.vault, key, g.source_id);
  else {
    const v = await seal(emptyVault(g.source_id), key, salt, g.source_id);
    await commit(saved, (tx) =>
      tx.objectStore("vault").put({ id: "owner", value: v }),
    );
  }
  session = { key, salt, last: Date.now() };
}
async function copyOf(saved) {
  let recovered = false;
  for (const c of [...saved.snapshots].sort((a, b) => b.id - a.id)) {
    try {
      const data = await validateStock(c.envelope, saved.meta.trust, {
        stored: true,
      });
      insist(data.sequence === c.id);
      return {
        copy: { ...c, data },
        recovered:
          recovered || data.sequence !== saved.meta.watermark?.sequence,
      };
    } catch (e) {
      recovered = true;
    }
  }
  return { copy: null, recovered };
}
export async function state() {
  const saved = await raw(),
    base = {
      trust: saved.meta.trust,
      device: publicDevice(saved.meta.device),
      authorized: false,
      copy: null,
      orders: [],
      vaultExists: !!saved.vault,
      unlocked: false,
    };
  let g;
  try {
    g = await authorization(saved);
  } catch (e) {
    return { ...base, authError: e.message };
  }
  const copies = await copyOf(saved);
  let v = null;
  if (g.role === "owner")
    try {
      v = await owner(saved, g);
    } catch (e) {}
  return {
    ...base,
    ...copies,
    authorized: true,
    grant: g,
    unlocked: !!v,
    orders: v?.orders || [],
    allocations: v?.allocations || [],
    receipts: v?.receipts || [],
    watermark: saved.meta.watermark,
  };
}
async function saveVault(saved, v) {
  validateVault(v, saved.meta.trust.source_id);
  const encrypted = await seal(
    v,
    session.key,
    session.salt,
    saved.meta.trust.source_id,
  );
  await commit(saved, (tx) =>
    tx.objectStore("vault").put({ id: "owner", value: encrypted }),
  );
  session.last = Date.now();
}
export function quantity(boxes, units, capacity, { optional = false } = {}) {
  for (const n of [boxes, units])
    insist(
      n === null || integer(n),
      "Indique quantidades inteiras não negativas.",
    );
  if (boxes === null && units === null) {
    insist(optional, "Indique uma quantidade.");
    return null;
  }
  insist(
    !boxes || capacity !== null,
    "A capacidade da caixa não está definida. Use garrafas.",
  );
  const total = (boxes || 0) * (capacity || 0) + (units || 0);
  insist(integer(total, 1), "A quantidade deve ser superior a zero.");
  return total;
}
export async function createOrder(
  referenceId,
  { boxes = null, units = null, note = "", ordered_on = today() } = {},
) {
  const saved = await raw(),
    g = await authorization(saved),
    v = await owner(saved, g),
    { copy } = await copyOf(saved);
  const ref = copy?.data.references.find((r) => r.id === referenceId);
  insist(ref, "Escolha uma referência ativa da cópia importada.");
  const total = quantity(boxes, units, ref.box_capacity, { optional: true });
  insist(typeof note === "string" && note.length <= 1000);
  insist(
    calendarDate(ordered_on) && ordered_on <= today(),
    "Data de encomenda inválida.",
  );
  v.orders.push({
    id: crypto.randomUUID(),
    reference_id: ref.id,
    name: ref.name,
    created_at: new Date().toISOString(),
    ordered_on,
    quantity: total,
    boxes,
    units,
    box_capacity: ref.box_capacity,
    note,
    state: "waiting",
    ended_at: null,
    gap: false,
  });
  await saveVault(saved, v);
}
export async function editOrder(id, { note, boxes, units, cancel = false }) {
  const saved = await raw(),
    g = await authorization(saved),
    v = await owner(saved, g),
    o = v.orders.find((o) => o.id === id);
  insist(o && pending(o), "Encomenda inexistente ou concluída.");
  insist(typeof note === "string" && note.length <= 1000);
  o.note = note;
  if (cancel) {
    o.state = "cancelled";
    o.ended_at = new Date().toISOString();
    o.gap = false;
  } else {
    insist(
      orderReceived(v, id) === 0,
      "Não se altera a quantidade depois de uma receção. Cancele o remanescente e crie outra encomenda.",
    );
    o.quantity = quantity(boxes, units, o.box_capacity, { optional: true });
    o.boxes = boxes;
    o.units = units;
  }
  await saveVault(saved, v);
}
export async function importSnapshot(envelope) {
  const saved = await raw(),
    g = await authorization(saved);
  insist(
    g.can_import,
    "O Empregado não está autorizado a importar atualizações.",
  );
  const recovery = envelope.format === "vertente-receipts";
  const data = recovery
    ? await validateRecovery(envelope, saved.meta.trust)
    : await validateStock(envelope, saved.meta.trust);
  if (recovery)
    insist(
      g.role === "owner",
      "A recuperação de encomendas é exclusiva do Proprietário.",
    );
  const mark = saved.meta.watermark,
    floor = saved.meta.floor;
  if (!recovery) {
    insist(
      !mark ||
        (data.sequence > mark.sequence &&
          data.update_id !== mark.update_id &&
          data.exported_at >= mark.exported_at),
      "Atualização repetida ou anterior à última importação.",
    );
    insist(
      !floor ||
        data.sequence > floor.sequence ||
        (data.sequence === floor.sequence &&
          data.update_id === floor.update_id &&
          data.exported_at === floor.exported_at),
      "O ficheiro é anterior ou contradiz o backup recuperado.",
    );
  }
  let encrypted = null,
    v = null;
  if (g.role === "owner") {
    v = await owner(saved, g);
    const until = recovery
      ? saved.meta.watermark?.exported_at || data.coverage.until
      : data.exported_at;
    reconcile(v, data, until);
    if (!recovery)
      v.watermark = {
        sequence: data.sequence,
        update_id: data.update_id,
        exported_at: data.exported_at,
      };
    validateVault(v, g.source_id);
    encrypted = await seal(v, session.key, session.salt, g.source_id);
  }
  const previous = await copyOf(saved);
  await commit(saved, (tx) => {
    if (!recovery) {
      const s = tx.objectStore("snapshots");
      for (const c of saved.snapshots)
        if (c.id !== previous.copy?.id) s.delete(c.id);
      s.put({
        id: data.sequence,
        envelope,
        imported_at: new Date().toISOString(),
      });
      tx.objectStore("meta").put({
        id: "watermark",
        value: {
          sequence: data.sequence,
          update_id: data.update_id,
          exported_at: data.exported_at,
        },
      });
    }
    if (encrypted)
      tx.objectStore("vault").put({ id: "owner", value: encrypted });
  });
  return {
    references: recovery ? null : data.references.length,
    receipts: data.receipts.length,
    gaps: v?.orders.filter((o) => o.gap).length || 0,
    recovery,
  };
}
export async function backupPreferences(password) {
  const saved = await raw(),
    g = await authorization(saved),
    v = await owner(saved, g);
  const salt = crypto.getRandomValues(new Uint8Array(16)),
    key = await derive(password, salt, ["encrypt"]);
  return seal(v, key, salt, g.source_id);
}
export async function decodePreferences(file, password) {
  const saved = await raw(),
    g = await authorization(saved);
  await owner(saved, g);
  const salt = bytes(file.salt, 16),
    key = await derive(password, salt, ["decrypt"]);
  return unseal(file, key, g.source_id);
}
export async function restorePreferences(v) {
  const saved = await raw(),
    g = await authorization(saved);
  await owner(saved, g);
  validateVault(v, g.source_id);
  const { copy } = await copyOf(saved);
  if (copy) reconcile(v, copy.data, copy.data.exported_at);
  const encrypted = await seal(v, session.key, session.salt, g.source_id);
  await commit(saved, (tx) => {
    tx.objectStore("vault").put({ id: "owner", value: encrypted });
    const prior = saved.meta.floor;
    if (v.watermark && (!prior || v.watermark.sequence > prior.sequence))
      tx.objectStore("meta").put({ id: "floor", value: v.watermark });
  });
}
