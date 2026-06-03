/* Minimal fetch helpers for the FastAPI backend (HLE-836, P2).
 *
 * Same-origin: the backend serves this SPA *and* the /api routes, so no CORS
 * and the session cookie rides along automatically. Calls reject on a non-2xx
 * or a network error; screens catch and fall back to sample data, so the SPA
 * still renders when opened under a plain static server (design comparison).
 */
(function () {
  async function jsonFetch(path, opts) {
    const res = await fetch(
      path,
      Object.assign(
        { credentials: "same-origin", headers: { "Content-Type": "application/json" } },
        opts || {}
      )
    );
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  window.api = {
    /* start-screen bootstrap: session cookie + saved characters + session cost */
    session() {
      return jsonFetch("/api/session");
    },
    /* paste a story -> extracted character drafts ({characters, cost}) */
    extract(text) {
      return jsonFetch("/api/extract", { method: "POST", body: JSON.stringify({ text: text }) });
    },
    /* pick an extracted draft -> create + persist the character ({character}) */
    createCharacter(name) {
      return jsonFetch("/api/character", { method: "POST", body: JSON.stringify({ name: name }) });
    },
    /* load a character (resume / open saved) -> ({character}) */
    getCharacter(id) {
      return jsonFetch("/api/character/" + encodeURIComponent(id));
    },
    /* persist the edited anketa -> ({character}) */
    saveAnketa(id, anketa) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/anketa", {
        method: "PUT",
        body: JSON.stringify(anketa),
      });
    },
  };
})();
