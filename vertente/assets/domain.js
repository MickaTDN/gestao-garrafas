// File protocol v1. Verification uses the exact signed bytes, never a reserialized JSON.
export const MAX_FILE = 4 * 1024 * 1024;
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
  exact(bundle, ["format", "version", "source_id", "keys"]);
  insist(
    bundle.format === "vertente-trust" &&
      bundle.version === 1 &&
      UUID.test(bundle.source_id),
  );
  insist(
    Array.isArray(bundle.keys) &&
      bundle.keys.length > 0 &&
      bundle.keys.length <= 8,
  );
  insist(new Set(bundle.keys.map((k) => k.key_id)).size === bundle.keys.length);
  for (const record of bundle.keys) await keyRecord(record);
  return bundle;
}
export async function validateStock(
  envelope,
  trust,
  { stored = false, now = Date.now() } = {},
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
    envelope.format === "vertente-stock" && envelope.version === 1,
    "Formato ou versão de stock não suportados.",
  );
  insist(envelope.algorithm === "ES256" && HEX.test(envelope.key_id));
  insist(trust, "Configure primeiro a origem e a chave pública autorizadas.");
  const record = trust.keys.find(
    (k) => k.key_id === envelope.key_id && (stored || !k.revoked),
  );
  insist(
    record,
    "Chave não autorizada ou revogada. Confirme a rotação com a informática.",
  );
  const key = await keyRecord({ key_id: record.key_id, spki: record.spki });
  const payload = bytes(envelope.payload),
    signature = bytes(envelope.signature, 64);
  insist(
    signature.length === 64 &&
      (await crypto.subtle.verify(
        { name: "ECDSA", hash: "SHA-256" },
        key,
        signature,
        payload,
      )),
    "Assinatura inválida. A cópia anterior foi preservada.",
  );
  const data = JSON.parse(
    new TextDecoder("utf-8", { fatal: true }).decode(payload),
  );
  exact(data, [
    "source_id",
    "update_id",
    "sequence",
    "exported_at",
    "references",
  ]);
  insist(
    UUID.test(data.source_id) && data.source_id === trust.source_id,
    "A atualização pertence a outra instalação de origem.",
  );
  insist(
    UUID.test(data.update_id) &&
      integer(data.sequence, 1, Number.MAX_SAFE_INTEGER) &&
      timestamp(data.exported_at),
  );
  if (!stored)
    insist(
      Date.parse(data.exported_at) <= now + 300000,
      "A data está no futuro. Verifique os relógios do Android e do escritório.",
    );
  insist(Array.isArray(data.references) && data.references.length <= MAX_ITEMS);
  const ids = new Set(),
    codes = new Set();
  for (const ref of data.references) {
    exact(ref, ["id", "code", "name", "bottles", "box_capacity"]);
    insist(
      typeof ref.id === "string" &&
        ID.test(ref.id) &&
        text(ref.code, 30) &&
        text(ref.name, 250),
    );
    insist(
      integer(ref.bottles) &&
        (ref.box_capacity === null || integer(ref.box_capacity, 1)),
    );
    insist(
      !ids.has(ref.id) && !codes.has(ref.code),
      "Existem referências duplicadas no ficheiro.",
    );
    ids.add(ref.id);
    codes.add(ref.code);
  }
  return data;
}
export function normalize(value) {
  return value
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase("pt-PT")
    .trim();
}
export function low(ref, alerts) {
  return alerts.has(ref.id) && ref.bottles <= alerts.get(ref.id).limit;
}
export function summary(refs, alerts, orders) {
  const open = new Set(
    orders.filter((o) => o.state === "open").map((o) => o.reference_id),
  );
  return {
    all: refs.length,
    zero: refs.filter((r) => r.bottles === 0).length,
    low: refs.filter((r) => low(r, alerts)).length,
    todo: refs.filter((r) => low(r, alerts) && !open.has(r.id)).length,
    ordered: open.size,
    missingOrdered: [...open].filter((id) => !refs.some((r) => r.id === id))
      .length,
  };
}
export function matches(ref, filter, query, alerts, orders) {
  const open = orders.some(
    (o) => o.reference_id === ref.id && o.state === "open",
  );
  const match = {
    all: true,
    positive: ref.bottles > 0,
    zero: ref.bottles === 0,
    low: low(ref, alerts),
    todo: low(ref, alerts) && !open,
    ordered: open,
  };
  return (
    match[filter] &&
    normalize(ref.name + " " + ref.code).includes(normalize(query))
  );
}
