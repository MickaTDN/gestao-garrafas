// File protocol v1. Verification uses the exact signed bytes, never a reserialized JSON.
export const MAX_FILE = 8 * 1024 * 1024;
export const MAX_ITEMS = 10000;
export const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const ID = /^[1-9][0-9]{0,18}$/;
export const HEX = /^[0-9a-f]{64}$/;
export function insist(ok, message = "Ficheiro inválido ou incompleto.") {
  if (!ok) throw new Error(message);
}
export function exact(value, keys) {
  insist(value && typeof value === "object" && !Array.isArray(value));
  insist(Object.keys(value).sort().join("|") === [...keys].sort().join("|"));
}
export function integer(n, min = 0, max = 2147483647) {
  return Number.isSafeInteger(n) && n >= min && n <= max;
}
export function timestamp(value) {
  return (
    typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value) &&
    Number.isFinite(Date.parse(value)) &&
    new Date(value).toISOString() === value
  );
}
export function text(value, max) {
  return (
    typeof value === "string" &&
    value.trim().length > 0 &&
    value.length <= max * 2 &&
    [...value].length <= max &&
    !/[\u0000\p{Surrogate}]/u.test(value)
  );
}
export function bytes(value, max = MAX_FILE) {
  insist(
    typeof value === "string" &&
      value.length <= max * 2 &&
      /^[A-Za-z0-9_-]+$/.test(value),
  );
  let decoded;
  try {
    decoded = Uint8Array.from(
      atob(value.replace(/-/g, "+").replace(/_/g, "/")),
      (c) => c.charCodeAt(0),
    );
  } catch (_) {
    throw new Error("Codificação inválida.");
  }
  insist(decoded.length <= max && encode(decoded) === value);
  return decoded;
}
export function encode(value) {
  let output = "";
  for (let i = 0; i < value.length; i += 8192)
    output += String.fromCharCode(...value.subarray(i, i + 8192));
  return btoa(output)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}
export async function keyRecord(record) {
  exact(record, ["key_id", "spki"]);
  insist(HEX.test(record.key_id));
  const der = bytes(record.spki, 512);
  const digest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", der))]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  insist(digest === record.key_id, "O fingerprint da chave não corresponde.");
  const key = await crypto.subtle.importKey(
    "spki",
    der,
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["verify"],
  );
  return key;
}
export async function validateTrust(bundle) {
  exact(
    bundle,
    bundle.rotation
      ? ["format", "version", "source_id", "keys", "rotation"]
      : ["format", "version", "source_id", "keys"],
  );
  insist(
    bundle.format === "vertente-trust" &&
      bundle.version === 1 &&
      UUID.test(bundle.source_id),
  );
  insist(
    Array.isArray(bundle.keys) && bundle.keys.length === 1,
    "O ficheiro de origem deve conter exatamente uma chave, confirmada pelo seu fingerprint.",
  );
  insist(new Set(bundle.keys.map((k) => k.key_id)).size === bundle.keys.length);
  for (const record of bundle.keys) await keyRecord(record);
  return bundle;
}
export async function verifyEnvelope(
  envelope,
  trust,
  kind,
  version,
  { stored = false } = {},
) {
  exact(envelope, [
    "format",
    "version",
    "algorithm",
    "key_id",
    "payload",
    "signature",
  ]);
  insist(
    envelope.format === kind && envelope.version === version,
    "Formato ou versão não suportados. Peça uma exportação compatível com a Etapa B.",
  );
  insist(envelope.algorithm === "ES256" && HEX.test(envelope.key_id));
  insist(trust, "Configure a origem autorizada antes de importar.");
  const record = trust.keys.find(
    (k) => k.key_id === envelope.key_id && (stored || !k.revoked),
  );
  insist(record, "Chave não autorizada ou revogada. Contacte a informática.");
  const key = await keyRecord({ key_id: record.key_id, spki: record.spki });
  const raw = bytes(envelope.payload),
    signature = bytes(envelope.signature, 64);
  const prefix = new TextEncoder().encode(`${kind}-v${version}\0`);
  const message = new Uint8Array(prefix.length + raw.length);
  message.set(prefix);
  message.set(raw, prefix.length);
  insist(
    signature.length === 64 &&
      (await crypto.subtle.verify(
        { name: "ECDSA", hash: "SHA-256" },
        key,
        signature,
        message,
      )),
    "Assinatura inválida. A cópia anterior foi preservada.",
  );
  const data = JSON.parse(
    new TextDecoder("utf-8", { fatal: true }).decode(raw),
  );
  insist(
    data.source_id === trust.source_id && UUID.test(data.source_id),
    "Origem de dados incorreta.",
  );
  return data;
}
export function validateReceipts(data) {
  exact(data.coverage, ["from", "until"]);
  insist(
    timestamp(data.coverage.from) &&
      timestamp(data.coverage.until) &&
      data.coverage.from <= data.coverage.until,
  );
  insist(Array.isArray(data.receipts) && data.receipts.length <= MAX_ITEMS);
  const ids = new Set();
  for (const r of data.receipts) {
    exact(r, [
      "id",
      "movement_id",
      "reference_id",
      "name",
      "date",
      "confirmed_at",
      "bottles",
      "boxes",
      "units",
      "box_capacity",
    ]);
    insist(
      ID.test(r.id) &&
        ID.test(r.movement_id) &&
        ID.test(r.reference_id) &&
        text(r.name, 250),
    );
    insist(
      typeof r.date === "string" &&
        /^\d{4}-\d{2}-\d{2}$/.test(r.date) &&
        !Number.isNaN(Date.parse(r.date)),
    );
    insist(
      timestamp(r.confirmed_at) &&
        r.confirmed_at >= data.coverage.from &&
        r.confirmed_at <= data.coverage.until,
    );
    insist(
      integer(r.bottles, 1) &&
        (r.boxes === null || integer(r.boxes)) &&
        (r.units === null || integer(r.units)) &&
        (r.box_capacity === null || integer(r.box_capacity, 1)) &&
        (!r.boxes || r.box_capacity !== null),
    );
    insist(
      (r.boxes || 0) * (r.box_capacity || 0) + (r.units || 0) === r.bottles &&
        !ids.has(r.id),
    );
    ids.add(r.id);
  }
}
export async function validateStock(
  envelope,
  trust,
  { stored = false, now = Date.now() } = {},
) {
  const data = await verifyEnvelope(envelope, trust, "vertente-stock", 2, {
    stored,
  });
  exact(data, [
    "source_id",
    "update_id",
    "sequence",
    "exported_at",
    "references",
    "receipts",
    "coverage",
  ]);
  insist(
    UUID.test(data.update_id) &&
      integer(data.sequence, 1, Number.MAX_SAFE_INTEGER) &&
      timestamp(data.exported_at),
  );
  if (!stored)
    insist(
      Date.parse(data.exported_at) <= now + 300000,
      "Data futura. Verifique os relógios do dispositivo e do escritório.",
    );
  insist(data.coverage.until === data.exported_at);
  validateReceipts(data);
  insist(Array.isArray(data.references) && data.references.length <= MAX_ITEMS);
  const ids = new Set();
  for (const r of data.references) {
    exact(r, [
      "id",
      "name",
      "bottles",
      "box_capacity",
      "location",
      "sector",
      "minimum",
    ]);
    insist(
      ID.test(r.id) &&
        text(r.name, 250) &&
        text(r.location, 100) &&
        (r.sector === null || text(r.sector, 100)),
    );
    insist(
      integer(r.bottles) &&
        (r.box_capacity === null || integer(r.box_capacity, 1)) &&
        (r.minimum === null || integer(r.minimum)),
    );
    insist(!ids.has(r.id), "Referências repetidas no ficheiro.");
    ids.add(r.id);
  }
  return data;
}
export async function validateRecovery(envelope, trust) {
  const data = await verifyEnvelope(envelope, trust, "vertente-receipts", 1);
  exact(data, [
    "source_id",
    "update_id",
    "exported_at",
    "coverage",
    "receipts",
  ]);
  insist(
    UUID.test(data.update_id) &&
      timestamp(data.exported_at) &&
      Date.parse(data.exported_at) <= Date.now() + 300000,
  );
  insist(data.coverage.until <= data.exported_at);
  validateReceipts(data);
  return data;
}
export async function validateGrant(envelope, trust, device) {
  const d = await verifyEnvelope(envelope, trust, "vertente-device", 1);
  exact(d, [
    "source_id",
    "device_id",
    "device_key_id",
    "role",
    "can_import",
    "revision",
    "grant_id",
    "issued_at",
    "expires_at",
  ]);
  insist(
    d.device_id === device.id && d.device_key_id === device.key_id,
    "A autorização pertence a outro dispositivo.",
  );
  insist(
    ["owner", "employee"].includes(d.role) &&
      typeof d.can_import === "boolean" &&
      integer(d.revision, 1) &&
      UUID.test(d.grant_id),
  );
  insist(
    timestamp(d.issued_at) &&
      timestamp(d.expires_at) &&
      d.issued_at < d.expires_at &&
      Date.parse(d.expires_at) - Date.parse(d.issued_at) <= 365 * 86400000,
  );
  insist(
    Date.parse(d.issued_at) <= Date.now() + 300000 &&
      Date.parse(d.expires_at) > Date.now(),
    "Autorização expirada ou relógio incorreto. Peça renovação à informática.",
  );
  return d;
}
export function normalize(value) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase("pt-PT")
    .trim();
}
export function low(ref) {
  return ref.minimum !== null && ref.bottles <= ref.minimum;
}
export const pending = (o) => ["waiting", "partial"].includes(o.state);
export function summary(refs, orders = []) {
  const ordered = new Set(orders.filter(pending).map((o) => o.reference_id));
  return {
    all: refs.length,
    zero: refs.filter((r) => r.bottles === 0).length,
    low: refs.filter(low).length,
    todo: refs.filter((r) => low(r) && !ordered.has(r.id)).length,
    ordered: orders.filter(pending).length,
  };
}
export function matches(ref, filter, query, orders = []) {
  const open = orders.some((o) => o.reference_id === ref.id && pending(o));
  return (
    {
      all: true,
      positive: ref.bottles > 0,
      zero: ref.bottles === 0,
      low: low(ref),
      todo: low(ref) && !open,
      ordered: open,
    }[filter] && normalize(ref.name).includes(normalize(query))
  );
}
export function mergeCoverage(intervals) {
  const result = [];
  for (const interval of [...intervals].sort((a, b) =>
    a.from.localeCompare(b.from),
  )) {
    exact(interval, ["from", "until"]);
    insist(
      timestamp(interval.from) &&
        timestamp(interval.until) &&
        interval.from <= interval.until,
    );
    const last = result.at(-1);
    if (last && interval.from <= last.until) {
      if (interval.until > last.until) last.until = interval.until;
    } else result.push({ ...interval });
  }
  insist(
    result.length <= 1000,
    "Demasiadas janelas de recuperação; preserve o backup e contacte a assistência.",
  );
  return result;
}
export function covered(intervals, from, until) {
  return (
    until <= from || intervals.some((i) => i.from <= from && i.until >= until)
  );
}
export function orderReceived(vault, orderId) {
  return vault.allocations
    .filter((a) => a.order_id === orderId)
    .reduce((n, a) => n + a.bottles, 0);
}
export function reconcile(vault, incoming, until) {
  const byId = new Map(vault.receipts.map((r) => [r.id, r]));
  for (const r of incoming.receipts) {
    const old = byId.get(r.id);
    insist(
      !old || JSON.stringify(old) === JSON.stringify(r),
      "Uma Entrada já conhecida foi alterada. Nenhum dado foi substituído.",
    );
    byId.set(r.id, r);
  }
  insist(
    byId.size <= 100000,
    "Limite do arquivo local atingido. Exporte uma cópia cifrada e contacte a assistência; não apague receções.",
  );
  vault.receipts = [...byId.values()];
  vault.coverage = mergeCoverage([...vault.coverage, incoming.coverage]);
  const orders = [...vault.orders].sort(
    (a, b) =>
      a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id),
  );
  const entries = [...vault.receipts].sort(
    (a, b) =>
      a.confirmed_at.localeCompare(b.confirmed_at) || BigIntCompare(a.id, b.id),
  );
  for (const r of entries) {
    let remaining =
      r.bottles -
      vault.allocations
        .filter((a) => a.receipt_id === r.id)
        .reduce((n, a) => n + a.bottles, 0);
    for (const o of orders) {
      if (
        !remaining ||
        !pending(o) ||
        o.reference_id !== r.reference_id ||
        r.confirmed_at <= o.created_at
      )
        continue;
      // An earlier pending order with a gap blocks FIFO for this reference.
      if (!covered(vault.coverage, o.created_at, r.confirmed_at)) break;
      const received = orderReceived(vault, o.id),
        need = o.quantity === null ? remaining : o.quantity - received;
      const take = Math.min(remaining, need);
      if (take > 0) {
        vault.allocations.push({
          receipt_id: r.id,
          order_id: o.id,
          bottles: take,
        });
        remaining -= take;
      }
      const total = received + take;
      o.state = (o.quantity === null ? total > 0 : total >= o.quantity)
        ? "received"
        : total > 0
          ? "partial"
          : "waiting";
      if (o.state === "received") o.ended_at = r.confirmed_at;
    }
  }
  for (const o of vault.orders)
    o.gap = pending(o) && !covered(vault.coverage, o.created_at, until);
  return vault;
}
function BigIntCompare(a, b) {
  return BigInt(a) < BigInt(b) ? -1 : BigInt(a) > BigInt(b) ? 1 : 0;
}
