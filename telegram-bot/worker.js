const JSON_HEADERS = { 'content-type': 'application/json; charset=utf-8' };

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body, null, 2), { status, headers: JSON_HEADERS });
}

function textResponse(body, status = 200) {
  return new Response(body, { status, headers: { 'content-type': 'text/plain; charset=utf-8' } });
}

function allowedIds(env) {
  return String(env.TELEGRAM_ALLOWED_USER_IDS || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
}

function isAllowedTelegramUser(update, env) {
  const ids = allowedIds(env);
  if (!ids.length) return false;
  const fromId = update?.callback_query?.from?.id || update?.message?.from?.id;
  return ids.includes(String(fromId));
}

async function telegramApi(env, method, body) {
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(`Telegram ${method} failed: ${response.status} ${JSON.stringify(data)}`);
  }
  return data;
}

async function answerCallback(env, callbackQueryId, text) {
  return telegramApi(env, 'answerCallbackQuery', {
    callback_query_id: callbackQueryId,
    text,
    show_alert: false,
  });
}

function githubConfig(env) {
  const repo = env.GITHUB_REPO || 'jonathanrosvel-dev/tasas-sueldo-real';
  const branch = env.GITHUB_BRANCH || 'main';
  if (!env.GITHUB_TOKEN) throw new Error('Falta GITHUB_TOKEN');
  return { repo, branch, token: env.GITHUB_TOKEN };
}

async function githubGetFile(env, path) {
  const { repo, branch, token } = githubConfig(env);
  const url = `https://api.github.com/repos/${repo}/contents/${encodeURIComponentPath(path)}?ref=${encodeURIComponent(branch)}`;
  const response = await fetch(url, {
    headers: {
      authorization: `Bearer ${token}`,
      accept: 'application/vnd.github+json',
      'user-agent': 'sueldo-real-telegram-bot',
    },
  });
  if (response.status === 404) return null;
  const data = await response.json();
  if (!response.ok) throw new Error(`GitHub get failed: ${response.status} ${JSON.stringify(data)}`);
  const content = decodeBase64Utf8(data.content || '');
  return { sha: data.sha, content, json: JSON.parse(content) };
}

async function githubPutFile(env, path, content, sha, message) {
  const { repo, branch, token } = githubConfig(env);
  const url = `https://api.github.com/repos/${repo}/contents/${encodeURIComponentPath(path)}`;
  const body = {
    message,
    content: encodeBase64Utf8(content),
    branch,
  };
  if (sha) body.sha = sha;
  const response = await fetch(url, {
    method: 'PUT',
    headers: {
      authorization: `Bearer ${token}`,
      accept: 'application/vnd.github+json',
      'content-type': 'application/json',
      'user-agent': 'sueldo-real-telegram-bot',
    },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(`GitHub put failed: ${response.status} ${JSON.stringify(data)}`);
  return data;
}

function encodeURIComponentPath(path) {
  return String(path).split('/').map(encodeURIComponent).join('/');
}

function encodeBase64Utf8(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function decodeBase64Utf8(base64) {
  const cleaned = String(base64).replace(/\s/g, '');
  const binary = atob(cleaned);
  const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

function parseCallbackData(value) {
  const parts = String(value || '').split(':');
  if (parts.length !== 3 || parts[0] !== 'sr') {
    throw new Error('Callback no reconocido');
  }
  const decision = parts[1];
  const id = parts[2];
  if (!['ok', 'no'].includes(decision)) throw new Error('Decisión inválida');
  if (!/^[a-zA-Z0-9_-]{6,80}$/.test(id)) throw new Error('ID pendiente inválido');
  return { decision, id };
}

function findMatchingItem(list, match) {
  if (!Array.isArray(list)) return null;
  return list.find((item) => Object.entries(match || {}).every(([key, value]) => item?.[key] === value));
}

function getByPath(root, pathArray) {
  let current = root;
  for (const key of pathArray || []) {
    if (current == null) return undefined;
    current = current[key];
  }
  return current;
}

function applyPendingAction(targetJson, pending, decision, userId) {
  const action = pending.action || {};
  const now = new Date().toISOString();

  if (action.kind === 'set_estado_by_match') {
    const list = getByPath(targetJson, action.arrayPath);
    const item = findMatchingItem(list, action.match);
    if (!item) throw new Error('No encontré el registro exacto en el JSON objetivo');
    item.estado = decision === 'ok' ? (action.estadoOk || 'manual_validado') : (action.estadoReject || 'manual_requerido');
    item.validacionTelegram = {
      decision: decision === 'ok' ? 'aprobado' : 'rechazado',
      userId: String(userId),
      fecha: now,
      pendingId: pending.id,
    };
    item.nota = decision === 'ok'
      ? `${item.nota || ''} Validado por Telegram el ${now}.`.trim()
      : `${item.nota || ''} Rechazado por Telegram el ${now}; requiere revisión manual.`.trim();
    return targetJson;
  }

  if (action.kind === 'merge_root_fields') {
    const fields = decision === 'ok' ? (action.fieldsOk || {}) : (action.fieldsReject || {});
    return { ...targetJson, ...fields };
  }

  throw new Error(`Acción no soportada: ${action.kind || 'sin_kind'}`);
}

async function processDecision(env, update) {
  const callback = update.callback_query;
  const userId = callback.from.id;
  const { decision, id } = parseCallbackData(callback.data);
  const pendingPath = `tasas/historico/pendientes/${id}.json`;
  const pendingFile = await githubGetFile(env, pendingPath);
  if (!pendingFile) throw new Error(`No existe pendiente ${id}`);

  const pending = pendingFile.json;
  if (pending.estado && pending.estado !== 'pendiente') {
    return { already: true, message: `Este pendiente ya estaba en estado: ${pending.estado}` };
  }

  let targetResult = null;
  if (pending.targetFile && pending.action) {
    const targetFile = await githubGetFile(env, pending.targetFile);
    if (!targetFile) throw new Error(`No existe archivo objetivo ${pending.targetFile}`);
    const updatedJson = applyPendingAction(targetFile.json, pending, decision, userId);
    const updatedContent = `${JSON.stringify(updatedJson, null, 2)}\n`;
    targetResult = await githubPutFile(
      env,
      pending.targetFile,
      updatedContent,
      targetFile.sha,
      decision === 'ok'
        ? `Validar ${pending.titulo || id} desde Telegram`
        : `Rechazar ${pending.titulo || id} desde Telegram`,
    );
  }

  pending.estado = decision === 'ok' ? 'aprobado' : 'rechazado';
  pending.resueltoPorTelegram = {
    userId: String(userId),
    username: callback.from.username || null,
    fecha: new Date().toISOString(),
    decision,
  };
  const pendingContent = `${JSON.stringify(pending, null, 2)}\n`;
  await githubPutFile(env, pendingPath, pendingContent, pendingFile.sha, `Resolver pendiente ${id} desde Telegram`);

  return {
    decision,
    title: pending.titulo || id,
    targetFile: pending.targetFile,
    commitUrl: targetResult?.commit?.html_url || null,
  };
}

function resultText(result) {
  if (result.already) return `ℹ️ ${result.message}`;
  if (result.decision === 'ok') {
    return `✅ Listo, Jonathan.\n\nValidé: ${result.title}\nArchivo: ${result.targetFile || 'pendiente registrado'}\n\nLa app podrá usar el dato desde GitHub cuando descargue el JSON remoto.`;
  }
  return `🟡 Entendido, Jonathan.\n\nDejé rechazado o pendiente de revisión: ${result.title}\nArchivo: ${result.targetFile || 'pendiente registrado'}\n\nNo lo marqué como validado.`;
}

async function handleTelegramUpdate(request, env) {
  const update = await request.json();
  if (!isAllowedTelegramUser(update, env)) {
    const callbackId = update?.callback_query?.id;
    if (callbackId) await answerCallback(env, callbackId, 'No autorizado');
    return jsonResponse({ ok: false, error: 'Usuario no autorizado' }, 403);
  }

  if (update.callback_query) {
    try {
      await answerCallback(env, update.callback_query.id, 'Procesando...');
      const result = await processDecision(env, update);
      await telegramApi(env, 'sendMessage', {
        chat_id: update.callback_query.message.chat.id,
        text: resultText(result),
        disable_web_page_preview: true,
      });
      return jsonResponse({ ok: true, result });
    } catch (error) {
      await telegramApi(env, 'sendMessage', {
        chat_id: update.callback_query.message.chat.id,
        text: `⚠️ No pude procesar la decisión.\n\n${error.message}`,
        disable_web_page_preview: true,
      });
      return jsonResponse({ ok: false, error: error.message }, 500);
    }
  }

  return jsonResponse({ ok: true, ignored: true });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === 'GET') {
      if (url.pathname === '/health') return jsonResponse({ ok: true, service: 'sueldo-real-telegram-bot' });
      return textResponse('Sueldo Real Chile Telegram Bot OK');
    }
    if (request.method === 'POST') {
      return handleTelegramUpdate(request, env);
    }
    return textResponse('Method not allowed', 405);
  },
};
