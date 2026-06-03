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
    /* project STYLE: prompt + refs + lock state */
    getStyle() {
      return jsonFetch("/api/style");
    },
    /* append reference image FILES (multipart — the Space proxy drops big JSON
       bodies); the 5th ref triggers the LLM draft. Accepts a File or File[]. */
    styleRefs(files) {
      const list = Array.isArray(files) ? files : [files];
      const fd = new FormData();
      list.forEach((f) => fd.append("files", f));
      return fetch("/api/style/refs", { method: "POST", credentials: "same-origin", body: fd })
        .then((r) => {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        });
    },
    /* edit the STYLE prompt in place (only before the first generation) */
    styleSave(prompt) {
      return jsonFetch("/api/style", { method: "PUT", body: JSON.stringify({ prompt: prompt }) });
    },
    /* «Изменить стиль»: clear the project style + refs */
    styleReset() {
      return jsonFetch("/api/style/reset", { method: "POST" });
    },
    styleRefUrl(key, w) {
      return "/api/style/ref/" + encodeURIComponent(key) + (w ? "?w=" + w : "");
    },
    /* paste a story -> extracted character drafts ({characters, cost}) */
    extract(text) {
      return jsonFetch("/api/extract", { method: "POST", body: JSON.stringify({ text: text }) });
    },
    /* RU description -> EN layer prompt (+ other-layer suggestions). When
       `current` is a non-empty existing prompt, `text` is applied as a change
       request that modifies it in place instead of rewriting from scratch. */
    translate(text, layer, current) {
      return jsonFetch("/api/translate", {
        method: "POST",
        body: JSON.stringify({ text: text, layer: layer, current: current || "" }),
      });
    },
    /* pick an extracted draft -> create + persist the character ({character}) */
    createCharacter(name) {
      return jsonFetch("/api/character", { method: "POST", body: JSON.stringify({ name: name }) });
    },
    /* load a character (resume / open saved) -> ({character}) */
    getCharacter(id) {
      return jsonFetch("/api/character/" + encodeURIComponent(id));
    },
    /* LLM-compose FACE/BODY/OUTFIT/base-emotion drafts from the trait card */
    composeLayers(id, card, marks) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/compose", {
        method: "POST",
        body: JSON.stringify({ card: card, marks: marks }),
      });
    },
    /* persist the edited anketa -> ({character}) */
    saveAnketa(id, anketa) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/anketa", {
        method: "PUT",
        body: JSON.stringify(anketa),
      });
    },
    /* «Проверить с ИИ» one step -> ({justification, new_prompt, step_key, ok}) */
    check(id, stepKey) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/check", {
        method: "POST", body: JSON.stringify({ step_key: stepKey }),
      });
    },
    checkAccept(id, stepKey, prompt) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/check/accept", {
        method: "POST", body: JSON.stringify({ step_key: stepKey, prompt: prompt }),
      });
    },
    /* «Правка с ИИ» whole character -> ({blocks, note, ok}) */
    edit(id, requestText) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/edit", {
        method: "POST", body: JSON.stringify({ request: requestText }),
      });
    },
    editAccept(id, stepKey, prompt) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/edit/accept", {
        method: "POST", body: JSON.stringify({ step_key: stepKey, prompt: prompt }),
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
    emotionEnable(id, enabled) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/emotions/enable", {
        method: "POST",
        body: JSON.stringify({ enabled: enabled }),
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
    outfitAdd(id) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/outfits/add", { method: "POST" });
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
    /* props phase -> ({props}) */
    getProps(id) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/props");
    },
    propsEnable(id, enabled) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/props/enable", {
        method: "POST",
        body: JSON.stringify({ enabled: enabled }),
      });
    },
    propAdd(id) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/props/add", { method: "POST" });
    },
    propShot(id, action, payload) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/props/shot/" + action, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },
    /* mark the character complete -> ({ok, character}) */
    finishCharacter(id) {
      return jsonFetch("/api/character/" + encodeURIComponent(id) + "/finish", { method: "POST" });
    },
    /* download URL for the finish ZIP (passport.json + approved/ + rejected/) */
    archiveUrl(id) {
      return "/api/character/" + encodeURIComponent(id) + "/archive";
    },
    /* URL of a generated frame image. v busts the cache after a regenerate;
       w requests a downscaled thumbnail (fast review grids). */
    imageUrl(id, stepKey, v, w) {
      return "/api/character/" + encodeURIComponent(id) + "/image/" + encodeURIComponent(stepKey)
        + "?v=" + (v || 0) + (w ? "&w=" + w : "");
    },
  };
})();
