function unauthorized() {
  return new Response("Autenticacion requerida", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="Visor GPS", charset="UTF-8"',
      "Cache-Control": "no-store",
    },
  });
}

function getBasicAuth(request) {
  const header = request.headers.get("Authorization");

  if (!header || !header.startsWith("Basic ")) {
    return null;
  }

  try {
    const decoded = atob(header.slice("Basic ".length));
    const separator = decoded.indexOf(":");

    if (separator === -1) {
      return null;
    }

    return {
      user: decoded.slice(0, separator),
      pass: decoded.slice(separator + 1),
    };
  } catch {
    return null;
  }
}

function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") {
    return false;
  }

  const left = new TextEncoder().encode(a);
  const right = new TextEncoder().encode(b);

  if (left.length !== right.length) {
    return false;
  }

  let diff = 0;

  for (let i = 0; i < left.length; i += 1) {
    diff |= left[i] ^ right[i];
  }

  return diff === 0;
}

export default {
  async fetch(request, env) {
    return new Response("WORKER ACTIVO - prueba", {
      headers: {
        "Content-Type": "text/plain",
        "Cache-Control": "no-store",
      },
    });
  },
};
