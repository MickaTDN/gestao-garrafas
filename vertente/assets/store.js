import {
  validateStock,
  validateTrust,
  exact,
  insist,
  integer,
  timestamp,
  text,
  ID,
  UUID,
  MAX_ITEMS,
  MAX_FILE,
  bytes,
  encode,
  low,
} from "./domain.js";

const NAME = "vertente-aveludada",
  VERSION = 1;
let connection;
export async function database() {
  if (connection) return connection;
  connection = await new Promise((resolve, reject) => {
    const request = indexedDB.open(NAME, VERSION);
    request.onupgradeneeded = () => {
      for (const store of ["meta", "snapshots", "alerts", "orders", "tracked"])
        request.result.createObjectStore(store, { keyPath: "id" });
    };
    request.onerror = () =>
      reject(
        new Error(
          "Não foi possível abrir o armazenamento local. Não limpe os dados; verifique o espaço e as permissões.",
        ),
      );
    request.onblocked = () =>
      reject(
        new Error(
          "Feche outras janelas da aplicação para atualizar o armazenamento.",
        ),
      );
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => {
        db.close();
        connection = null;
      };
      resolve(db);
    };
  });
  return connection;
}
function result(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
function completion(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = resolve;
    tx.onabort = () =>
      reject(
        new Error(
          "Não foi possível guardar. A cópia anterior foi preservada; verifique o espaço e tente novamente.",
        ),
      );
    tx.onerror = () => {};
  });
}
export async function readAll() {
  const db = await database(),
    tx = db.transaction(
      ["meta", "snapshots", "alerts", "orders", "tracked"],
      "readonly",
    );
  const done = completion(tx);
  const [meta, snapshots, alerts, orders, tracked] = await Promise.all(
    ["meta", "snapshots", "alerts", "orders", "tracked"].map((n) =>
      result(tx.objectStore(n).getAll()),
    ),
  );
  await done;
  return {
    trust: meta.find((x) => x.id === "trust")?.value,
    watermark: meta.find((x) => x.id === "watermark")?.value,
    snapshots,
    alerts,
    orders,
    tracked,
  };
}
export async function state() {
  const saved = await readAll();
  let copy = null,
    recovered = false;
  for (const candidate of [...saved.snapshots].sort((a, b) => b.id - a.id)) {
    try {
      const data = await validateStock(candidate.envelope, saved.trust, {
        stored: true,
      });
      insist(data.sequence === candidate.id);
      copy = { ...candidate, data };
      recovered = data.sequence !== saved.watermark?.sequence;
      break;
    } catch (_) {
      recovered = true;
    }
  }
  return { ...saved, copy, recovered };
}
export async function enroll(bundle, fingerprint) {
  await validateTrust(bundle);
  insist(
    bundle.keys.some((k) => k.key_id === fingerprint.trim().toLowerCase()),
    "Confirme o fingerprint completo por um canal independente.",
  );
  const db = await database(),
    tx = db.transaction("meta", "readwrite"),
    done = completion(tx),
    store = tx.objectStore("meta");
  let message;
  const request = store.get("trust");
  request.onsuccess = () => {
    const old = request.result?.value;
    if (old && old.source_id !== bundle.source_id) {
      message = "A origem está fixada a outra instalação. Não foi alterada.";
      tx.abort();
      return;
    }
    const retired = (old?.keys || [])
      .filter((k) => !bundle.keys.some((n) => n.key_id === k.key_id))
      .map((k) => ({ ...k, revoked: true }));
    if (retired.length + bundle.keys.length > 64) {
      message = "Excesso de chaves históricas. Contacte a informática.";
      tx.abort();
      return;
    }
    store.put({
      id: "trust",
      value: {
        source_id: bundle.source_id,
        keys: [
          ...bundle.keys.map((k) => ({ ...k, revoked: false })),
          ...retired,
        ],
      },
    });
  };
  try {
    await done;
  } catch (error) {
    throw new Error(message || error.message);
  }
}
export async function importSnapshot(envelope) {
  const before = await state(),
    data = await validateStock(envelope, before.trust);
  const db = await database(),
    tx = db.transaction(["meta", "snapshots", "tracked"], "readwrite"),
    done = completion(tx);
  const meta = tx.objectStore("meta");
  let message;
  const requests = [meta.get("trust"), meta.get("watermark")];
  let ready = 0;
  for (const request of requests)
    request.onsuccess = () => {
      if (++ready !== 2) return;
      const trust = requests[0].result?.value,
        mark = requests[1].result?.value;
      if (
        JSON.stringify(trust) !== JSON.stringify(before.trust) ||
        JSON.stringify(mark) !== JSON.stringify(before.watermark)
      ) {
        message = "Os dados mudaram noutra janela. Reveja e volte a importar.";
        tx.abort();
        return;
      }
      if (
        mark &&
        (data.sequence <= mark.sequence ||
          data.update_id === mark.update_id ||
          data.exported_at < mark.exported_at)
      ) {
        message =
          data.update_id === mark.update_id || data.sequence === mark.sequence
            ? "Esta atualização já foi importada."
            : "Esta atualização é anterior à última importação.";
        tx.abort();
        return;
      }
      const snapshots = tx.objectStore("snapshots");
      // Keep the newest VERIFIED previous copy, not a potentially corrupt latest row.
      for (const record of before.snapshots)
        if (record.id !== before.copy?.id) snapshots.delete(record.id);
      snapshots.put({
        id: data.sequence,
        envelope,
        imported_at: new Date().toISOString(),
      });
      meta.put({
        id: "watermark",
        value: {
          sequence: data.sequence,
          update_id: data.update_id,
          exported_at: data.exported_at,
        },
      });
      for (const old of before.tracked) {
        const ref = data.references.find((r) => r.id === old.id);
        if (ref)
          tx.objectStore("tracked").put({
            id: ref.id,
            code: ref.code,
            name: ref.name,
          });
      }
    };
  try {
    await done;
  } catch (error) {
    throw new Error(message || error.message);
  }
  return data;
}
async function edit(storeNames, apply) {
  const db = await database(),
    tx = db.transaction(storeNames, "readwrite"),
    done = completion(tx);
  try {
    apply(tx);
  } catch (error) {
    tx.abort();
    await done.catch(() => {});
    throw error;
  }
  await done;
}
function tracked(ref) {
  return { id: ref.id, code: ref.code, name: ref.name };
}
export async function setAlert(ref, limit) {
  insist(
    ID.test(ref.id) && (limit === null || integer(limit)),
    "Indique um limite inteiro em garrafas.",
  );
  await edit(["alerts", "tracked", "orders"], (tx) => {
    if (limit === null) {
      tx.objectStore("alerts").delete(ref.id);
      const orders = tx.objectStore("orders").getAll();
      orders.onsuccess = () => {
        if (!orders.result.some((order) => order.reference_id === ref.id))
          tx.objectStore("tracked").delete(ref.id);
      };
    } else {
      tx.objectStore("alerts").put({ id: ref.id, limit });
      tx.objectStore("tracked").put(tracked(ref));
    }
  });
}
export async function markOrdered(ref) {
  const saved = await state();
  insist(
    saved.copy?.data.references.some((r) => r.id === ref.id) &&
      low(ref, new Map(saved.alerts.map((a) => [a.id, a]))),
    "Só é possível encomendar uma referência ativa com alerta de stock baixo.",
  );
  await edit(["orders", "tracked"], (tx) => {
    const request = tx.objectStore("orders").getAll();
    request.onsuccess = () => {
      if (
        request.result.some(
          (o) => o.reference_id === ref.id && o.state === "open",
        )
      ) {
        tx.abort();
        return;
      }
      tx.objectStore("orders").put({
        id: crypto.randomUUID(),
        reference_id: ref.id,
        created_at: new Date().toISOString(),
        state: "open",
        ended_at: null,
      });
      tx.objectStore("tracked").put(tracked(ref));
    };
  });
}
export async function finishOrder(id, next) {
  insist(["closed", "cancelled"].includes(next));
  await edit(["orders"], (tx) => {
    const store = tx.objectStore("orders"),
      request = store.get(id);
    request.onsuccess = () => {
      const old = request.result;
      if (!old || old.state !== "open") {
        tx.abort();
        return;
      }
      store.put({ ...old, state: next, ended_at: new Date().toISOString() });
    };
  });
}
export function validatePreferences(data, source) {
  exact(data, [
    "format",
    "version",
    "source_id",
    "alerts",
    "orders",
    "tracked",
  ]);
  insist(
    data.format === "vertente-preferences" &&
      data.version === 1 &&
      UUID.test(data.source_id) &&
      data.source_id === source,
    "As preferências pertencem a outra origem ou formato.",
  );
  for (const field of ["alerts", "orders", "tracked"])
    insist(
      Array.isArray(data[field]) &&
        data[field].length <= MAX_ITEMS &&
        new Set(data[field].map((r) => r.id)).size === data[field].length,
    );
  for (const a of data.alerts) {
    exact(a, ["id", "limit"]);
    insist(ID.test(a.id) && integer(a.limit));
  }
  const open = new Set();
  for (const o of data.orders) {
    exact(o, ["id", "reference_id", "created_at", "state", "ended_at"]);
    insist(
      UUID.test(o.id) &&
        ID.test(o.reference_id) &&
        timestamp(o.created_at) &&
        ["open", "closed", "cancelled"].includes(o.state),
    );
    insist(
      o.state === "open"
        ? o.ended_at === null && !open.has(o.reference_id)
        : timestamp(o.ended_at) && o.ended_at >= o.created_at,
    );
    if (o.state === "open") open.add(o.reference_id);
  }
  for (const r of data.tracked) {
    exact(r, ["id", "code", "name"]);
    insist(ID.test(r.id) && text(r.code, 30) && text(r.name, 250));
  }
  insist(
    [
      ...data.alerts.map((a) => a.id),
      ...data.orders.map((o) => o.reference_id),
    ].every((id) => data.tracked.some((r) => r.id === id)),
  );
  return data;
}
async function backupKey(password, salt, uses) {
  insist(
    typeof password === "string" && password.length >= 12,
    "Use uma frase-passe de pelo menos 12 caracteres. Não a esqueça: não fica guardada.",
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
export async function backupPreferences(password) {
  const saved = await readAll();
  insist(saved.trust, "Configure primeiro a origem.");
  const data = validatePreferences(
    {
      format: "vertente-preferences",
      version: 1,
      source_id: saved.trust.source_id,
      alerts: saved.alerts,
      orders: saved.orders,
      tracked: saved.tracked,
    },
    saved.trust.source_id,
  );
  const salt = crypto.getRandomValues(new Uint8Array(16)),
    iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await backupKey(password, salt, ["encrypt"]);
  const cipher = await crypto.subtle.encrypt(
    {
      name: "AES-GCM",
      iv,
      additionalData: new TextEncoder().encode("vertente-preferences-v1"),
    },
    key,
    new TextEncoder().encode(JSON.stringify(data)),
  );
  const envelope = {
    format: "vertente-preferences-encrypted",
    version: 1,
    kdf: "PBKDF2-SHA256",
    iterations: 600000,
    salt: encode(salt),
    iv: encode(iv),
    ciphertext: encode(new Uint8Array(cipher)),
  };
  insist(
    new TextEncoder().encode(JSON.stringify(envelope)).length <= MAX_FILE,
    "O backup excede 4 MiB. Preserve os dados e contacte a assistência antes de mudar de dispositivo.",
  );
  return envelope;
}
export async function decodePreferences(file, password) {
  exact(file, [
    "format",
    "version",
    "kdf",
    "iterations",
    "salt",
    "iv",
    "ciphertext",
  ]);
  insist(
    file.format === "vertente-preferences-encrypted" &&
      file.version === 1 &&
      file.kdf === "PBKDF2-SHA256" &&
      file.iterations === 600000,
  );
  const salt = bytes(file.salt, 16),
    iv = bytes(file.iv, 12),
    cipher = bytes(file.ciphertext, MAX_FILE);
  insist(salt.length === 16 && iv.length === 12);
  const key = await backupKey(password, salt, ["decrypt"]);
  let raw;
  try {
    raw = await crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv,
        additionalData: new TextEncoder().encode("vertente-preferences-v1"),
      },
      key,
      cipher,
    );
  } catch (_) {
    throw new Error(
      "Frase-passe incorreta ou backup alterado. Os dados locais foram preservados.",
    );
  }
  const saved = await readAll();
  insist(saved.trust, "Configure primeiro a origem autorizada.");
  return validatePreferences(
    JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw)),
    saved.trust.source_id,
  );
}
export async function restorePreferences(data) {
  const saved = await readAll();
  insist(saved.trust, "Configure primeiro a origem autorizada.");
  validatePreferences(data, saved.trust?.source_id);
  await edit(["meta", "alerts", "orders", "tracked"], (tx) => {
    const request = tx.objectStore("meta").get("trust");
    request.onsuccess = () => {
      if (request.result?.value.source_id !== data.source_id) {
        tx.abort();
        return;
      }
      for (const name of ["alerts", "orders", "tracked"]) {
        const store = tx.objectStore(name);
        store.clear();
        for (const record of data[name]) store.put(record);
      }
    };
  });
}
