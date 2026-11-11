// Serve the han2ids OCR page at /ocr, with its assets at the site root behind the Worker.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method Not Allowed', { status: 405, headers: { 'Cache-Control': 'no-store' } });
    }
    if (url.pathname === '/ocr') {
      return Response.redirect(new URL(`/ocr/${url.search}`, url.origin).href, 308);
    }
    if (url.pathname === '/ocr/' || url.pathname.startsWith('/ocr/')) {
      const path = url.pathname === '/ocr/' ? '/' : url.pathname.slice(4);
      const target = new URL(path + url.search, url.origin);
      const response = await env.ASSETS.fetch(new Request(target, request));
      const result = new Response(response.body, response);
      if (response.ok || response.status === 304) {
        // Asset URLs are unversioned; validate stored bytes against the current deployment.
        if (!/(?:^|,)\s*no-store\s*(?:,|$)/i.test(response.headers.get('Cache-Control') || '')) {
          result.headers.set('Cache-Control', 'no-cache');
        }
      } else {
        result.headers.set('Cache-Control', 'no-store');
      }
      return result;
    }
    return new Response('Not found', { status: 404, headers: { 'Cache-Control': 'no-store' } });
  },
};
