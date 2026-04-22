/*
 * AgentDB sidecar — HTTP JSON server bound to 127.0.0.1 only.
 *
 * Endpoints (all POST, JSON body, JSON response):
 *   POST /store   { namespace, text, metadata, outcome, correlation_id, ttl_seconds? }
 *   POST /search  { namespace, text, k?, min_confidence?, domain_filter? }
 *   POST /prune   { namespace, min_confidence?, min_usage?, max_age_seconds? }
 *   GET  /stats
 *   GET  /healthz
 *
 * Security posture:
 *   - Binds to 127.0.0.1 only — no TCP exposure beyond loopback.
 *   - Shared-secret auth via Authorization: Bearer <token> (env AI_TF_SIDECAR_TOKEN).
 *     On multi-tenant hosts, loopback alone is NOT sufficient isolation.
 *   - No PII/secret scanning here; the Python client's FilterStack runs
 *     BEFORE anything reaches the sidecar.
 */
import http from 'node:http';
import { createAgentDBAdapter } from 'agentic-flow/reasoningbank';

const HOST   = '127.0.0.1';
const PORT   = Number(process.env.AI_TF_SIDECAR_PORT || 7443);
const TOKEN  = process.env.AI_TF_SIDECAR_TOKEN || 'dev-token-not-for-prod';
const DB_PATH = process.env.AI_TF_SIDECAR_DB || '.agentdb/tf-out.db';

// Recipe 2 — balanced performance, per agentdb-optimization skill.
// Scalar quantization keeps accuracy high while giving 4x memory reduction;
// HNSW M=16 + ef=100 is the sweet spot for <100K patterns, which is the scale
// we expect for run-history on this project.
const adapter = await createAgentDBAdapter({
  dbPath: DB_PATH,
  quantizationType: 'scalar',
  cacheSize: 1000,
  hnswM: 16,
  hnswEfConstruction: 200,
  hnswEfSearch: 100,
  enableLearning: true,
  enableReasoning: true,
});

function json(res, status, body) {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}

function authorised(req) {
  const h = req.headers['authorization'] || '';
  return h === `Bearer ${TOKEN}`;
}

async function readJson(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

const handlers = {
  'POST /store': async (body) => {
    const { namespace, text, metadata = {}, outcome = 'unknown', correlation_id = '' } = body;
    if (!text) throw new Error('text is required');
    await adapter.insertPattern({
      id: '',
      type: 'trajectory',
      domain: namespace || 'default',
      pattern_data: JSON.stringify({ text, metadata, outcome, correlation_id }),
      confidence: outcome === 'success' ? 1.0 : (outcome === 'failure' ? 0.3 : 0.5),
      usage_count: 0,
      success_count: outcome === 'success' ? 1 : 0,
      created_at: Date.now(),
      last_used: Date.now(),
    });
    return { stored: true };
  },

  'POST /search': async (body) => {
    const { namespace, text, k = 5, min_confidence = 0.0, domain_filter } = body;
    if (!text) throw new Error('text is required');
    const result = await adapter.retrieveWithReasoning(text, {
      domain: domain_filter || namespace || 'default',
      k,
      minConfidence: min_confidence,
    });
    const patterns = (result?.patterns || []).map((p) => {
      let data = {};
      try { data = JSON.parse(p.pattern_data); } catch { /* noop */ }
      return {
        confidence: p.confidence,
        usage_count: p.usage_count,
        outcome: data.outcome,
        correlation_id: data.correlation_id,
        text_preview: (data.text || '').slice(0, 200),
        metadata: data.metadata || {},
      };
    });
    return { patterns, reasoning: result?.reasoning || '' };
  },

  'POST /prune': async (body) => {
    const { min_confidence = 0.3, min_usage = 0, max_age_seconds } = body;
    const before = (await adapter.getStats()).totalPatterns;
    await adapter.prune({
      minConfidence: min_confidence,
      minUsageCount: min_usage,
      ...(max_age_seconds ? { maxAge: max_age_seconds } : {}),
    });
    const after = (await adapter.getStats()).totalPatterns;
    return { pruned: before - after, before, after };
  },

  'GET /stats': async () => {
    const s = await adapter.getStats();
    return {
      totalPatterns: s.totalPatterns,
      dbSize: s.dbSize,
      avgConfidence: s.avgConfidence,
      cacheHitRate: s.cacheHitRate,
    };
  },

  'GET /healthz': async () => ({ ok: true, dbPath: DB_PATH }),
};

const server = http.createServer(async (req, res) => {
  // Defence in depth: refuse anything not on loopback even if bind is misconfigured.
  const remote = req.socket.remoteAddress;
  if (remote !== '127.0.0.1' && remote !== '::1' && remote !== '::ffff:127.0.0.1') {
    return json(res, 403, { error: 'loopback only' });
  }
  if (!authorised(req)) return json(res, 401, { error: 'unauthorised' });

  const key = `${req.method} ${req.url.split('?')[0]}`;
  const handler = handlers[key];
  if (!handler) return json(res, 404, { error: 'not found' });

  try {
    const body = ['POST', 'PUT'].includes(req.method) ? await readJson(req) : {};
    const out = await handler(body);
    json(res, 200, out);
  } catch (err) {
    console.error('handler error', key, err);
    json(res, 400, { error: String(err?.message || err) });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`ai-tf agentdb sidecar listening on http://${HOST}:${PORT}  db=${DB_PATH}`);
});

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    console.log(`${sig} received — closing`);
    server.close(() => process.exit(0));
  });
}
