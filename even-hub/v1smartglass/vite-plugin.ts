import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Plugin } from 'vite'

// Vision One regional hosts — must match permissions.network in app.json.
const ALLOWED_HOSTS = new Set([
  'api.xdr.trendmicro.com',
  'api.eu.xdr.trendmicro.com',
  'api.xdr.trendmicro.co.jp',
  'api.sg.xdr.trendmicro.com',
  'api.au.xdr.trendmicro.com',
  'api.in.xdr.trendmicro.com',
  'api.uae.xdr.trendmicro.com',
])

const PROXY_PATH = '/__v1proxy'

async function readBody(req: IncomingMessage): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = []
    req.on('data', (chunk) => chunks.push(Buffer.from(chunk)))
    req.on('end', () => resolve(Buffer.concat(chunks)))
    req.on('error', reject)
  })
}

export default function v1Proxy(): Plugin {
  return {
    name: 'v1smartglass-proxy',
    configureServer(server) {
      server.middlewares.use(PROXY_PATH, async (req: IncomingMessage, res: ServerResponse) => {
        try {
          const parsed = new URL(req.url ?? '', 'http://localhost')
          const target = parsed.searchParams.get('url')?.trim() ?? ''
          if (!target.startsWith('https://')) {
            res.statusCode = 400
            res.end('Missing or non-HTTPS "url" query parameter')
            return
          }

          const targetUrl = new URL(target)
          if (!ALLOWED_HOSTS.has(targetUrl.hostname)) {
            res.statusCode = 403
            res.end(`Host not in allowlist: ${targetUrl.hostname}`)
            return
          }

          const auth = req.headers['x-v1-auth']
          if (typeof auth !== 'string' || auth.length === 0) {
            res.statusCode = 401
            res.end('Missing X-V1-Auth header')
            return
          }

          const headers: Record<string, string> = {
            Authorization: `Bearer ${auth}`,
            Accept: 'application/json',
            'User-Agent': 'v1smartglass-evenhub/0.1',
          }

          const method = (req.method ?? 'GET').toUpperCase()
          const body = method === 'GET' || method === 'HEAD' ? undefined : await readBody(req)

          const upstream = await fetch(targetUrl, { method, headers, body })
          const text = await upstream.text()

          res.statusCode = upstream.status
          res.setHeader('content-type', upstream.headers.get('content-type') ?? 'application/json')
          res.end(text)
        } catch (error) {
          res.statusCode = 502
          const message = error instanceof Error ? error.message : String(error)
          res.end(`Proxy request failed: ${message}`)
        }
      })
    },
  }
}
