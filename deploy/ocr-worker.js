// Serve the han2ids OCR page at /ocr, with its assets at the site root behind the Worker.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response('Method Not Allowed', { status: 405 });
    }
    if (url.pathname === '/ocr') {
      return Response.redirect(new URL(`/ocr/${url.search}`, url.origin).href, 308);
    }
    if (url.pathname === '/ocr/' || url.pathname.startsWith('/ocr/')) {
      const path = url.pathname === '/ocr/' ? '/' : url.pathname.slice(4);
      const target = new URL(path + url.search, url.origin);
      const response = await env.ASSETS.fetch(new Request(target, request));
      if (path.startsWith('/models/') || path.startsWith('/ort/') || path.startsWith('/fonts/')) {
        const cached = new Response(response.body, response);
        cached.headers.set('Cache-Control', 'public, max-age=86400');
        return cached;
      }
      return response;
    }
    return new Response('Not found', { status: 404 });
  },
};
