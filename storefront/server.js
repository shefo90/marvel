import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import compression from 'compression';
import express from 'express';
import { renderPage } from 'vike/server';

const root = dirname(fileURLToPath(import.meta.url));
const isProduction = process.env.NODE_ENV === 'production';
const port = Number(process.env.PORT ?? 3000);

/**
 * The render server.
 *
 * Server-rendered because a crawler must receive the product's title, price and
 * structured data in the first response — section 8A treats client-only
 * rendering of catalogue content as a defect, not a preference. It is also the
 * difference between a largest-contentful-paint measured in one round trip and
 * one measured in three.
 */
async function start() {
  const app = express();
  app.use(compression());
  app.disable('x-powered-by');

  if (isProduction) {
    app.use(express.static(`${root}/dist/client`, { index: false, maxAge: '1y' }));
  } else {
    const vite = await import('vite');
    const devServer = await vite.createServer({
      root,
      server: { middlewareMode: true },
    });
    app.use(devServer.middlewares);
  }

  // "/" carries no language. Redirected rather than rendered, because one
  // address must resolve to one language -- serving the English home page at a
  // locale-less URL would put it at two addresses, which is the duplicate the
  // canonical tag exists to resolve. 307, not 301: the default locale is a
  // decision that may change.
  app.get('/', (_request, response) => response.redirect(307, '/en'));

  app.use(async (request, response, next) => {
    const pageContext = await renderPage({
      urlOriginal: request.originalUrl,
      headersOriginal: request.headers,
    });

    const { httpResponse } = pageContext;
    if (!httpResponse) return next();

    for (const [name, value] of httpResponse.headers) {
      response.setHeader(name, value);
    }
    // Vike sets 404 and 500 here, so a missing page really is a 404 rather
    // than a page that merely says so.
    response.status(httpResponse.statusCode);
    httpResponse.pipe(response);
  });

  app.listen(port, () => {
    process.stdout.write(`storefront listening on http://localhost:${port}\n`);
  });
}

start();
