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
    /* passport phase -> ({passport}) */
    getPassport(id) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/passport");
    },
    /* edit layers + (re)generate one frame -> ({ok, error, passport}) */
    passportGenerate(id, payload) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/passport/generate", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    /* approve a frame (freeze) -> ({passport}) */
    passportApprove(id, stepKey) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/passport/approve", {
        method: "POST",
        body: JSON.stringify({ step_key: stepKey }),
      });
    },
    /* emotions phase -> ({emotions}) */
    getEmotions(id) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/emotions");
    },
    emotionGenerate(id, index) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/emotions/generate", {
        method: "POST",
        body: JSON.stringify({ index: index }),
      });
    },
    emotionBase(id, value) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/emotions/base", {
        method: "POST",
        body: JSON.stringify({ value: value }),
      });
    },
    emotionDelete(id, index) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/emotions/delete", {
        method: "POST",
        body: JSON.stringify({ index: index }),
      });
    },
    /* outfits phase -> ({outfits}) */
    getOutfits(id) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/outfits");
    },
    outfitGenerate(id, payload) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/outfits/generate", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    outfitComplex(id, index, complex) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/outfits/complex", {
        method: "POST",
        body: JSON.stringify({ index: index, complex: complex }),
      });
    },
    outfitApprove(id, index) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/outfits/approve", {
        method: "POST",
        body: JSON.stringify({ index: index }),
      });
    },
    outfitDetail(id, action, payload) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/outfits/detail/" + action, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    /* URL of a generated frame image (v busts the cache after a regenerate) */
    imageUrl(id, stepKey, v) {
      return "/api/character/" + encodeURIComponent(id) + "/image/" + encodeURIComponent(stepKey) + "?v=" + (v || 0);
    },
  };
})();
